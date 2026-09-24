"""Merge one person into another: every column that holds a user id moves.

The columns come from the table metadata, so a new table with a foreign key
to users.id joins the merge by itself. Two rows that would share a unique key
once the source's id reads as the target's stop the merge, except in the
tables whose rows are copies of one W3Champions fact: there the copy goes.
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import (
    Column,
    PrimaryKeyConstraint,
    RowMapping,
    Table,
    UniqueConstraint,
    and_,
    delete,
    or_,
    select,
    update,
)
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import SQLModel, col

from app.core.battle_tags import has_login
from app.core.exceptions import ApiError
from app.models.user import User
from app.models.user_battle_tag import MergePlan, UserBattleTag
from app.services.battle_tags import active_row

# User id columns that carry no foreign key: 0 on series_side means no player
NO_FOREIGN_KEY = {
    ("series", "host_player_id"),
    ("draft_series", "host_player_id"),
    ("series_side", "user_id"),
}
# One person sits once in a series, though the key also holds the side
EXTRA_KEYS = {"series_side": [("series_id", "user_id")]}
# Copies of one W3Champions fact: a duplicate goes, the newest ledger row stays
REMOVABLE = {"w3c_ladder_matches", "ladder_sync", "w3cstats"}
TAGS = "user_battle_tag"

# The words a plan counts rows in; a table missing here reads as its name
NOUNS = {
    "ladder_sync": ("ladder sync row", "ladder sync rows"),
    "player_career_stats": ("career stats row", "career stats rows"),
    TAGS: ("battle tag", "battle tags"),
    "user_block": ("repeating block", "repeating blocks"),
    "user_busy": ("busy day", "busy days"),
    "w3cstats": ("W3C stats row", "W3C stats rows"),
    "fantasy_teams": ("fantasy team", "fantasy teams"),
    "team_season_captain": ("captain seat", "captain seats"),
    "user_season_signup": ("signup", "signups"),
    "user_team_season": ("team season seat", "team season seats"),
    "w3c_ladder_matches": ("ladder match", "ladder matches"),
    "event_entrant": ("event entry", "event entries"),
    "fantasy_team_player": ("fantasy team pick", "fantasy team picks"),
    "event_award": ("award", "awards"),
    "round_availability": ("round availability", "round availabilities"),
    "match_draft_mark": ("draft ready mark", "draft ready marks"),
    "series": ("series", "series"),
    "draft_series": ("draft series", "draft series"),
    "fantasy_bets": ("fantasy bet", "fantasy bets"),
    "series_cast": ("cast", "casts"),
    "series_replay": ("replay upload", "replay uploads"),
    "series_veto_step": ("veto step", "veto steps"),
    "series_side": ("series seat", "series seats"),
}


def _noun(table: str, n: int = 1) -> str:
    one, many = NOUNS.get(table, (f"{table} row", f"{table} rows"))
    return one if n == 1 else many


def user_columns() -> dict[str, list[str]]:
    """Every column that holds a user id, per table."""
    users = SQLModel.metadata.tables["users"].c.id
    found: dict[str, list[str]] = {}
    for table in SQLModel.metadata.sorted_tables:
        names = [
            column.name
            for column in table.columns
            if any(fk.column is users for fk in column.foreign_keys)
            or (table.name, column.name) in NO_FOREIGN_KEY
        ]
        if names:
            found[table.name] = names
    return found


def _keys(table: Table) -> list[tuple[str, ...]]:
    """The plain-column unique keys of a table; expression and partial
    indexes are left out."""
    keys = [
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, PrimaryKeyConstraint | UniqueConstraint)
    ]
    for index in table.indexes:
        partial = index.dialect_options["postgresql"]["where"] is not None
        plain = [e for e in index.expressions if isinstance(e, Column)]
        if index.unique and not partial and len(plain) == len(index.expressions):
            keys.append(tuple(column.name for column in plain))
    return keys + EXTRA_KEYS.get(table.name, [])


def unique_keys() -> dict[str, list[tuple[str, ...]]]:
    """The unique keys that hold a user id column, per table."""
    keys: dict[str, list[tuple[str, ...]]] = {}
    for name, columns in user_columns().items():
        table = SQLModel.metadata.tables[name]
        keys[name] = [key for key in _keys(table) if set(key) & set(columns)]
    return keys


Removal = tuple[Table, dict[str, Any]]


def _table_plan(
    session: OrmSession, name: str, columns: list[str], source: int, target: int
) -> tuple[list[str], list[Removal], int]:
    """The stops, the rows to remove and the count of rows that move, for one
    table."""
    table = SQLModel.metadata.tables[name]
    pk = [column.name for column in table.primary_key.columns]
    keys = [key for key in _keys(table) if set(key) & set(columns)]
    wanted = {*pk, *columns, *(n for key in keys for n in key)}
    if name == "ladder_sync":
        wanted.add("synced_at")
    rows: Sequence[RowMapping] = (
        session.execute(
            select(*(table.c[n] for n in sorted(wanted))).where(
                or_(*(table.c[c].in_([source, target]) for c in columns))
            )
        )
        .mappings()
        .all()
    )

    def from_source(row: RowMapping) -> bool:
        return any(row[c] == source for c in columns)

    def after(row: RowMapping, key: tuple[str, ...]) -> tuple[object, ...]:
        return tuple(
            target if n in columns and row[n] == source else row[n] for n in key
        )

    stops: list[str] = []
    gone: set[int] = set()
    for key in keys:
        groups: dict[tuple[Any, ...], list[int]] = defaultdict(list)
        for at, row in enumerate(rows):
            groups[after(row, key)].append(at)
        for group in groups.values():
            if len(group) < 2 or not any(from_source(rows[at]) for at in group):
                continue
            if name in REMOVABLE:
                if name == "ladder_sync":
                    keep = max(group, key=lambda at: rows[at]["synced_at"])
                else:
                    keep = next(
                        (at for at in group if not from_source(rows[at])), group[0]
                    )
                gone.update(at for at in group if at != keep)
                continue
            where = ", ".join(
                f"{n} {rows[group[0]][n]}" for n in key if n not in columns
            )
            stop = f"Both hold the same {_noun(name)} ({where})"
            if stop not in stops:
                stops.append(stop)
    if {"player1_id", "player2_id"} <= set(columns):
        stops += [
            f"They play each other in {_noun(name)} {row['id']}"
            for row in rows
            if {row["player1_id"], row["player2_id"]} == {source, target}
        ]
    removals = [(table, {n: rows[at][n] for n in pk}) for at in sorted(gone)]
    moving = sum(
        1 for at, row in enumerate(rows) if from_source(row) and at not in gone
    )
    return stops, removals, moving


def plan(
    session: OrmSession, source: User, target: User
) -> tuple[MergePlan, list[Removal]]:
    """What merging source into target does, and the rows it removes."""
    result = MergePlan()
    removals: list[Removal] = []
    if has_login(source.discordId) and has_login(target.discordId):
        result.stops.append("Both have a Discord login")
    for name, columns in user_columns().items():
        stops, removed, moving = _table_plan(
            session, name, columns, source.id or 0, target.id or 0
        )
        result.stops += stops
        removals += removed
        if removed:
            n = len(removed)
            result.removes.append(f"{n} duplicate {_noun(name, n)}")
        if moving:
            result.moves.append(f"{moving} {_noun(name, moving)}")
    return result, removals


def merge(session: OrmSession, source: User, target: User) -> None:
    """Repoint every user id column from source to target, move the tags and
    remove source. The target keeps its active tag and its profile; a target
    with no login takes the source's Discord account."""
    result, removals = plan(session, source, target)
    if result.stops:
        raise ApiError(
            409,
            {
                "error": f"{source.name} and {target.name} both hold rows that"
                " cannot be joined. Resolve the stops first.",
                **result.model_dump(),
            },
        )
    for table, pk in removals:
        session.execute(
            delete(table).where(and_(*(table.c[n] == v for n, v in pk.items())))
        )
    s, t = source.id, target.id
    kept = active_row(session, t or 0)
    login = (
        (source.discordId, source.discordTag)
        if not has_login(target.discordId)
        else None
    )
    # discordId and discordTag are unique, so the source lets go first
    session.execute(
        update(User).where(col(User.id) == s).values(discordId=None, discordTag=None)
    )
    if kept is not None:
        session.execute(
            update(UserBattleTag)
            .where(col(UserBattleTag.user_id) == s)
            .values(is_active=False)
        )
    for name, columns in user_columns().items():
        table = SQLModel.metadata.tables[name]
        for c in columns:
            session.execute(update(table).where(table.c[c] == s).values({c: t}))
    if login is not None and has_login(login[0]):
        session.execute(
            update(User)
            .where(col(User.id) == t)
            .values(discordId=login[0], discordTag=login[1])
        )
    session.execute(delete(User).where(col(User.id) == s))
    session.expire_all()
