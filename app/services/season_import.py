"""The season import pipeline.

Reads an exported season workbook and writes it in one transaction: one
lookup statement per sheet, then the inserts and updates that sheet needs.
A failure leaves the database as it was.
"""

import io
import logging
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import openpyxl
from pydantic import ValidationError
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.battle_tags import has_login, is_real_tag
from app.core.db import Session
from app.core.exceptions import BadRequestError
from app.core.scoring import DEFAULT_SYSTEM, SYSTEMS
from app.models.base import ident
from app.models.discord_role_binding import (
    DiscordRoleBinding,
    DiscordRoleBindingCreate,
)
from app.models.enums import Race, RoleKind, RoleScope
from app.models.fantasy_bet import FantasyBet, FantasyBetCreate
from app.models.fantasy_team import FantasyTeam, FantasyTeamCreate
from app.models.map import Map, MapCreate
from app.models.match import Match, MatchCreate
from app.models.relationships import (
    DBFantasyTeamPlayer,
    DBMapSeason,
    DBUserSeasonSignup,
)
from app.models.season import Season, SeasonCreate
from app.models.series import Series, SeriesCreate
from app.models.series_cast import SeriesCast, channel_url
from app.models.series_side import SeriesSide
from app.models.team import Team, TeamCreate
from app.models.team_season import DBTeamSeason
from app.models.types import utcnow
from app.models.user import User, UserCreate
from app.models.user_battle_tag import UserBattleTag
from app.models.user_team_season import DBUserTeamSeason
from app.services.battle_tags import people_by_names, people_by_tags
from app.services.series import both_scores, in_season

logger = logging.getLogger(__name__)

type Cells = tuple[Any, ...]
type Row = dict[str, Any]
type Sheets = dict[str, list[Row]]


class ImportedSeason(NamedTuple):
    """The season the workbook wrote."""

    id: int
    name: str
    duplicate_bets: int


@dataclass
class Users:
    """The users the workbook names, by the id it carries and by `_key`."""

    by_old_id: dict[int, User] = field(default_factory=dict)
    by_tag: dict[str, User] = field(default_factory=dict)


def _key(value: UserCreate) -> str:
    """A row's person: its real tag, else its name, folded."""
    if is_real_tag(value.battleTag):
        return folded(value.battleTag)
    return f"name:{folded(value.name)}"


def folded[T](value: T) -> T | str:
    """The key a lookup matches on. Text folds to lower case, so a cell
    finds the stored row whatever the case it was typed in."""
    return value.strip().lower() if isinstance(value, str) else value


def whole_number(value: str | float | None) -> int | None:
    """Read a cell that holds a whole number."""
    if value is None or value == "":
        return None
    return int(float(value)) if isinstance(value, str) else int(value)


def read_workbook(file_bytes: bytes) -> dict[str, list[Cells]]:
    """Every sheet of the workbook as rows of cells, the header row first.
    Text cells are stripped, empty cells read None, short rows are padded
    to the width of the sheet."""
    workbook = openpyxl.load_workbook(
        io.BytesIO(file_bytes), read_only=True, data_only=True
    )
    sheets: dict[str, list[Cells]] = {}
    for worksheet in workbook.worksheets:
        rows = [
            tuple(value.strip() if isinstance(value, str) else value for value in row)
            for row in worksheet.iter_rows(values_only=True)
        ]
        width = max(map(len, rows), default=0)
        sheets[worksheet.title] = [row + (None,) * (width - len(row)) for row in rows]
    workbook.close()
    return sheets


def load_sheets(file_bytes: bytes) -> Sheets:
    """Every sheet of the workbook as one dict per data row, keyed by the
    header row."""
    return {
        name: [dict(zip(rows[0], row, strict=True)) for row in rows[1:]] if rows else []
        for name, rows in read_workbook(file_bytes).items()
    }


def import_season_workbook(
    file_bytes: bytes, create_new: bool, score_system: str | None = None
) -> ImportedSeason:
    """Read the workbook and write the season it holds."""
    sheets = load_sheets(file_bytes)
    with Session.begin() as session:
        return _write(session, sheets, create_new, score_system)


def _rows(rows: list[Row] | None, required: list[str]) -> list[Row]:
    """The rows of a sheet that carry every column the import reads. A
    workbook without an optional sheet answers no rows."""
    if rows is None:
        return []
    return [
        row for row in rows if all(row.get(column) is not None for column in required)
    ]


def _cells(row: Row, columns: dict[str, str]) -> dict[str, Any]:
    """The fields the row carries. An empty cell leaves its field unset, so a
    re-import keeps the value the database already holds."""
    return {
        name: row[column]
        for name, column in columns.items()
        if row.get(column) is not None
    }


def _write(
    session: OrmSession, sheets: Sheets, create_new: bool, score_system: str | None
) -> ImportedSeason:
    """Write every sheet of the workbook through one session."""
    season = _season(session, sheets, create_new, _score_system(sheets, score_system))
    maps = _maps(session, sheets, season)
    teams = _teams(session, sheets, season)
    users = _players(session, sheets, season, teams)
    matches = _matches(session, sheets, season, teams, maps)
    series = _series(session, sheets, matches, users)
    _fantasy_users(session, sheets, users)
    fantasy_teams = _fantasy_teams(session, sheets, season, teams, users)
    _fantasy_players(session, sheets, fantasy_teams, users)
    duplicate_bets = _fantasy_bets(session, sheets, season, series, users)
    logger.info(f"Import completed for season: {season.name}")
    return ImportedSeason(
        id=ident(season), name=season.name, duplicate_bets=duplicate_bets
    )


def _known_system(system: str) -> str:
    """A score system the scoring rule knows."""
    if system not in SYSTEMS:
        raise BadRequestError(f"Unknown score system: {system}")
    return system


def _numeric(value: str | float | None) -> float | None:
    """The number a cell holds, or None for text and empty cells."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _detected_system(sheets: Sheets) -> str:
    """The score system the played series imply. A series pays 3 points
    across both sides under standard and 4 under helpstone."""
    columns = ["Player1 Points", "Player2 Points"]
    # A losing side writes an empty cell, so a played row carries one value
    played = [
        points
        for row in sheets.get("Series", [])
        if (
            points := [
                value
                for column in columns
                if (value := _numeric(row.get(column))) is not None
            ]
        )
    ]
    if not played:
        logger.info(f"Score system {DEFAULT_SYSTEM}: the workbook has no played series")
        return DEFAULT_SYSTEM

    mean = sum(sum(points) for points in played) / len(played)
    system = "helpstone" if mean >= 3.5 else DEFAULT_SYSTEM
    logger.info(
        f"Score system {system}: {len(played)} played series mean {mean:.2f} points"
    )
    return system


def _score_system(sheets: Sheets, override: str | None) -> str:
    """The score system of the import: the request, then the Season sheet,
    then what the played series imply."""
    if override is not None:
        logger.info(f"Score system {override}: named by the request")
        return _known_system(override)

    row = sheets["Season"][0]
    if row.get("Score System") is not None:
        system = str(row["Score System"])
        logger.info(f"Score system {system}: named by the Season sheet")
        return _known_system(system)

    return _detected_system(sheets)


def _season(
    session: OrmSession, sheets: Sheets, create_new: bool, score_system: str
) -> Season:
    """The season row. Its name matches it, because the id the file carries
    belongs to the database the file was exported from."""
    row = sheets["Season"][0]
    values = SeasonCreate(
        name=row["Name"],
        round_count=whole_number(row["Number of Weeks"]) or 0,
        series_per_round=whole_number(row["Series Per Week"]) or 0,
        score_system=score_system,
        **_cells(
            row,
            {
                "pick_ban": "Pick Ban",
                "discordRole": "Discord Role",
                "start_date": "Start Date",
                "end_date": "End Date",
                "signups_open": "Signups Open",
            },
        ),
    )

    stored = None
    if not create_new:
        stored = session.scalars(
            select(Season).where(func.lower(Season.name) == folded(values.name))
        ).first()
    from app.services.seasons import fill_rounds, gnl_league

    league = gnl_league(session)

    if stored:
        # A stored event keeps the league it already stands in: a change is
        # refused while teams are linked to it
        if stored.league_id is None:
            stored.league_id = ident(league)
            stored.entrant_kind = league.entrant_kind
        elif stored.league_id != ident(league):
            raise BadRequestError("The workbook names an event of another league")
        stored.sqlmodel_update(values.model_dump(exclude_unset=True))
        fill_rounds(session, stored, values.round_count or 0)
        logger.info(f"Updating season {values.name} with ID: {stored.id}")
        return stored

    season = Season(
        **values.model_dump(),
        league_id=ident(league),
        entrant_kind=league.entrant_kind,
    )
    session.add(season)
    session.flush()
    # The round rows are the round count, so the import writes them too
    fill_rounds(session, season, values.round_count or 0)
    logger.info(f"Created new season with ID: {season.id}")
    return season


def _maps(session: OrmSession, sheets: Sheets, season: Season) -> dict[int, int]:
    """The map pool of the season, matched by shortname."""
    rows = _rows(sheets.get("Maps"), ["Name"])
    values = [
        MapCreate(
            name=row["Name"],
            **_cells(row, {"shortname": "Shortname", "image": "Image URL"}),
        )
        for row in rows
    ]
    wanted = {folded(value.shortname) for value in values if value.shortname}
    stored: dict[str, Map] = {}
    if wanted:
        stored = {
            folded(map_obj.shortname): map_obj
            for map_obj in session.scalars(
                select(Map).where(func.lower(Map.shortname).in_(wanted))
            )
        }

    written: list[Map] = []
    pool: list[Map] = []
    old_ids: dict[int, Map] = {}
    for row, value in zip(rows, values, strict=True):
        map_obj = stored.get(folded(value.shortname))
        if map_obj:
            map_obj.sqlmodel_update(value.model_dump(exclude_unset=True))
        else:
            map_obj = Map(**value.model_dump())
            written.append(map_obj)
            if value.shortname:
                stored[folded(value.shortname)] = map_obj
        pool.append(map_obj)
        old_id = whole_number(row["ID"])
        if old_id:
            old_ids[old_id] = map_obj
    session.add_all(written)
    session.flush()

    if pool:
        linked = set(
            session.scalars(
                select(col(DBMapSeason.map_id)).where(
                    col(DBMapSeason.season_id) == season.id
                )
            )
        )
        # A map the sheet adds joins the pool behind the ones already in it
        position = session.scalar(
            select(func.coalesce(func.max(col(DBMapSeason.position)), -1)).where(
                col(DBMapSeason.season_id) == season.id
            )
        )
        for map_id in dict.fromkeys(ident(map_obj) for map_obj in pool):
            if map_id in linked:
                continue
            position += 1
            session.add(
                DBMapSeason(season_id=ident(season), map_id=map_id, position=position)
            )
    return {
        old_id: map_obj.id
        for old_id, map_obj in old_ids.items()
        if map_obj.id is not None
    }


def _bind_team_role(session: OrmSession, team_id: int, role: Any) -> None:  # noqa: ANN401  # a cell holds text or a number
    """The Discord Role cell of a team binds that role to the team."""
    # Teams and their rosters are all-time, so the binding reads every season
    value = DiscordRoleBindingCreate(
        kind=RoleKind.team, scope=RoleScope.all, team_id=team_id, discord_role=role
    )
    binding = session.scalars(
        select(DiscordRoleBinding).where(
            col(DiscordRoleBinding.kind) == RoleKind.team,
            col(DiscordRoleBinding.team_id) == team_id,
        )
    ).first()
    if binding:
        binding.discord_role = value.discord_role
    else:
        session.add(DiscordRoleBinding(**value.model_dump()))


def _teams(session: OrmSession, sheets: Sheets, season: Season) -> dict[int, int]:
    """The teams of the season, matched by name."""
    rows = _rows(sheets["Teams"], ["Name"])
    values = [
        TeamCreate(
            name=row["Name"],
            **_cells(row, {"long_name": "Long Name"}),
        )
        for row in rows
    ]
    stored = {
        folded(team.name): team
        for team in session.scalars(
            select(Team).where(
                col(Team.league_id) == season.league_id,
                func.lower(Team.name).in_({folded(value.name) for value in values}),
            )
        )
    }

    written: list[Team] = []
    old_ids: dict[int, Team] = {}
    roles: list[tuple[Team, Any]] = []
    for row, value in zip(rows, values, strict=True):
        team = stored.get(folded(value.name))
        if team:
            team.sqlmodel_update(value.model_dump(exclude_unset=True))
        else:
            if season.league_id is None:
                raise BadRequestError("The imported event must belong to a league")
            team = Team(**value.model_dump(), league_id=season.league_id)
            written.append(team)
            stored[folded(value.name)] = team
        old_id = whole_number(row["ID"])
        if old_id:
            old_ids[old_id] = team
        cell = _cells(row, {"discord_role": "Discord Role"})
        if cell:
            roles.append((team, cell["discord_role"]))
    session.add_all(written)
    session.flush()

    for team, role in roles:
        _bind_team_role(session, ident(team), role)
    session.flush()

    team_ids = {ident(team) for team in old_ids.values()}
    if team_ids:
        linked = set(
            session.scalars(
                select(col(DBTeamSeason.team_id)).where(
                    col(DBTeamSeason.season_id) == season.id
                )
            )
        )
        session.add_all(
            [
                DBTeamSeason(season_id=ident(season), team_id=team_id)
                for team_id in team_ids - linked
            ]
        )
    return {old_id: team.id for old_id, team in old_ids.items() if team.id is not None}


def _player_values(row: Row) -> UserCreate:
    """A player of the Players sheet. An empty cell leaves the field unset,
    so a column the workbook does not carry writes nothing."""
    columns = {
        "name": "Name",
        "discordTag": "Discord Tag",
        "discordId": "Discord ID",
        "race": "Race",
        "mmr": "MMR",
        "country": "Country",
    }
    try:
        return UserCreate(battleTag=row.get("Battle Tag") or "", **_cells(row, columns))
    except ValidationError as error:
        missing = ", ".join(str(detail["loc"][0]) for detail in error.errors())
        raise BadRequestError(
            f"Player {row['ID']} of the Players sheet has no {missing}"
        ) from error


def _players(
    session: OrmSession, sheets: Sheets, season: Season, teams: dict[int, int]
) -> Users:
    """The rostered players, matched by battle tag, or a stand-in tag by
    name. A stored player is reused as it stands, so the workbook overwrites no profile. A row signs
    its player up for the season on the race it carries; a stored signup is
    reused as it stands too."""
    rows = _rows(sheets["Players"], ["ID"])
    values = [_player_values(row) for row in rows]
    users = Users(by_tag=_people(session, values))
    _new_people(session, values, users)

    signups = {
        signup.user_id: signup
        for signup in session.scalars(
            select(DBUserSeasonSignup).where(
                col(DBUserSeasonSignup.season_id) == season.id
            )
        )
    }
    roster: set[tuple[int, int]] = set()
    for row, value in zip(rows, values, strict=True):
        user = users.by_tag[_key(value)]
        if ident(user) not in signups:
            signups[ident(user)] = DBUserSeasonSignup(
                user_id=ident(user),
                season_id=ident(season),
                race=value.race,
                played_as=value.battleTag if is_real_tag(value.battleTag) else None,
            )
            session.add(signups[ident(user)])
        old_id = whole_number(row["ID"])
        if not old_id:
            continue
        users.by_old_id[old_id] = user
        team_id = teams.get(whole_number(row["Team ID"]))
        if team_id:
            roster.add((ident(user), team_id))

    if roster:
        linked = set(
            session.execute(
                select(
                    col(DBUserTeamSeason.user_id), col(DBUserTeamSeason.team_id)
                ).where(col(DBUserTeamSeason.season_id) == season.id)
            ).all()
        )
        session.add_all(
            [
                DBUserTeamSeason(
                    user_id=user_id, team_id=team_id, season_id=ident(season)
                )
                for user_id, team_id in roster - linked
            ]
        )
    return users


def _matches(
    session: OrmSession,
    sheets: Sheets,
    season: Season,
    teams: dict[int, int],
    maps: dict[int, int],
) -> dict[int, Match]:
    """The matches of the season, matched by the two teams and the playday."""
    rows = _rows(sheets["Matches"], ["Team1 ID", "Team2 ID", "Playday"])
    stored = {
        (match.team1_id, match.team2_id, match.playday): match
        for match in session.scalars(
            select(Match).where(col(Match.season_id) == season.id)
        )
    }

    written: list[Match] = []
    old_ids: dict[int, Match] = {}
    for row in rows:
        team1_id = teams.get(whole_number(row["Team1 ID"]))
        team2_id = teams.get(whole_number(row["Team2 ID"]))
        if not team1_id or not team2_id:
            raise BadRequestError(f"Match {row['ID']} names a team the workbook lacks")
        playday = whole_number(row["Playday"])
        if playday is None:
            raise BadRequestError(f"Match {row['ID']} has no playday")
        values = MatchCreate(
            team1_id=team1_id,
            team2_id=team2_id,
            season_id=ident(season),
            playday=playday,
            fixed_map_id=maps.get(whole_number(row.get("Fixed Map ID"))),
        )
        key = (team1_id, team2_id, values.playday)
        match = stored.get(key)
        if match:
            match.sqlmodel_update(values.model_dump(exclude_unset=True))
        else:
            match = Match(**values.model_dump())
            written.append(match)
            stored[key] = match
        old_id = whole_number(row["ID"])
        if old_id:
            old_ids[old_id] = match
    session.add_all(written)
    session.flush()
    return old_ids


def _series_values(
    row: Row, match_id: int, player1: User, player2: User, host: User
) -> SeriesCreate:
    """A series of the Series sheet. An empty date or off race leaves the field
    unset, so a stored series keeps the time and the races it already holds."""
    data: dict[str, Any] = {
        "match_id": match_id,
        "player1_id": player1.id,
        "player2_id": player2.id,
        "player1_score": whole_number(row.get("Player1 Score")),
        "player2_score": whole_number(row.get("Player2 Score")),
        "host_player_id": host.id,
        "is_fantasy_match": bool(row.get("Is Fantasy Match")),
    }
    if row.get("Date Time") is not None:
        data["date_time"] = row["Date Time"]
    for side, column in (
        ("player1_off_race", "Player1 Off Race"),
        ("player2_off_race", "Player2 Off Race"),
    ):
        if row.get(column):
            data[side] = Race.from_text(str(row[column]))
    return SeriesCreate(**data)


def _series(
    session: OrmSession, sheets: Sheets, matches: dict[int, Match], users: Users
) -> dict[int, int]:
    """The series of those matches, matched by match and the two players."""
    rows = _rows(sheets["Series"], ["Match ID", "Player1 ID", "Player2 ID"])
    match_ids = {ident(match) for match in matches.values()}
    stored: dict[tuple[int, int, int], Series] = {}
    if match_ids:
        stored = {
            (series.match_id, series.player1_id, series.player2_id): series
            for series in session.scalars(
                select(Series).where(col(Series.match_id).in_(match_ids))
            )
        }

    written: list[Series] = []
    touched: list[Series] = []
    old_ids: dict[int, Series] = {}
    casters: list[tuple[Series, str]] = []
    # A 2v2 series and its two sides, each side as its two players
    pairs: list[tuple[Series, tuple[User, User], tuple[User, User]]] = []
    for row in rows:
        match = matches.get(whole_number(row["Match ID"]))
        player1 = users.by_old_id.get(whole_number(row["Player1 ID"]))
        player2 = users.by_old_id.get(whole_number(row["Player2 ID"]))
        if not match or not player1 or not player2:
            raise BadRequestError(
                f"Series {row['ID']} names a match or a player the workbook lacks"
            )
        host = users.by_old_id.get(whole_number(row["Host Player ID"])) or player1
        values = _series_values(row, ident(match), player1, player2, host)
        partners = _partners(row, users)
        key = (ident(match), player1.id, player2.id)
        series = stored.get(key)
        if series:
            series.sqlmodel_update(values.model_dump(exclude_unset=True))
        else:
            series = Series(**values.model_dump())
            written.append(series)
            stored[key] = series
        touched.append(series)
        if partners:
            series.side_size = 2
            pairs.append((series, (player1, partners[0]), (player2, partners[1])))
        old_id = whole_number(row["ID"])
        if old_id:
            old_ids[old_id] = series
        if row.get("Caster"):
            casters.append((series, str(row["Caster"])))
    session.add_all(written)
    session.flush()
    # The rules SeriesService applies; a refused row rolls the import back
    for series in touched:
        both_scores(series)
        in_season(series)
    # A Caster cell is a channel link or a Twitch login; the cast has no account
    for series, caster in casters:
        url = _cast_url(caster)
        if all(cast.channel_url != url for cast in series.casts):
            series.casts.append(SeriesCast(channel_url=url))
    _sides(session, pairs)
    session.flush()
    return {
        old_id: series.id for old_id, series in old_ids.items() if series.id is not None
    }


def _partners(row: Row, users: Users) -> tuple[User, User] | None:
    """The second player of each side of a 2v2 row: the Player1b ID and
    Player2b ID cells. A row without both is a 1v1."""
    if row.get("Player1b ID") is None or row.get("Player2b ID") is None:
        return None
    partner1 = users.by_old_id.get(whole_number(row["Player1b ID"]))
    partner2 = users.by_old_id.get(whole_number(row["Player2b ID"]))
    if not partner1 or not partner2:
        raise BadRequestError(f"Series {row['ID']} names a player the workbook lacks")
    return partner1, partner2


def _sides(
    session: OrmSession,
    pairs: list[tuple[Series, tuple[User, User], tuple[User, User]]],
) -> None:
    """The `series_side` rows of the 2v2 series: side 1 is player1 and his
    partner, side 2 is player2 and his. The series keeps player1 and player2,
    so the GNL reads that know only those columns still find the series."""
    # ponytail: adds missing rows only; a re-import that swaps a partner keeps the old row
    if not pairs:
        return
    held = {
        (side.series_id, side.side_no, side.user_id)
        for side in session.scalars(
            select(SeriesSide).where(
                col(SeriesSide.series_id).in_([ident(series) for series, *_ in pairs])
            )
        )
    }
    for series, *teams in pairs:
        for side_no, team in enumerate(teams, start=1):
            for player in team:
                key = (ident(series), side_no, ident(player))
                if key not in held:
                    held.add(key)
                    session.add(
                        SeriesSide(series_id=key[0], side_no=side_no, user_id=key[2])
                    )


def _cast_url(caster: str) -> str:
    try:
        return channel_url(caster)
    except ValueError:
        return f"https://www.twitch.tv/{caster.strip().lstrip('@').lower()}"


def _people(session: OrmSession, values: list[UserCreate]) -> dict[str, User]:
    """The stored person behind each row, by `_key`. A real tag matches its
    tag row; a blank or stand-in tag, a person with no tag of the same name."""
    found = people_by_tags(session, [v.battleTag for v in values])
    names = [v.name for v in values if not is_real_tag(v.battleTag)]
    for name, user in people_by_names(session, names).items():
        found[f"name:{name}"] = user
    return found


def _new_people(session: OrmSession, values: list[UserCreate], users: Users) -> None:
    """Write a person for every row no one stored: a real tag becomes their
    active tag, a blank or stand-in tag none. A gnl- stand-in Discord id is no
    login, so it is written null, and so is the stand-in Discord tag the
    history import paired with it."""
    written: dict[str, User] = {}
    tags: dict[str, str] = {}
    for value in values:
        key = _key(value)
        if key in users.by_tag:
            continue
        data = value.model_dump(exclude={"battleTag"})
        if data["discordId"] and not has_login(data["discordId"]):
            data["discordId"] = None
            tag = data["discordTag"] or ""
            if "#GNL" in tag or folded(tag) == folded(value.battleTag):
                data["discordTag"] = None
        users.by_tag[key] = written[key] = User(**data)
        tags[key] = value.battleTag.strip()
    session.add_all(written.values())
    session.flush()
    now = utcnow()
    # One bulk statement: the tag rows need no ids read back
    rows = [
        {
            "user_id": ident(user),
            "tag": tags[key],
            "source": "sheet",
            "is_active": True,
            "first_seen": now,
            "last_seen": now,
        }
        for key, user in written.items()
        if is_real_tag(tags[key])
    ]
    if rows:
        session.execute(insert(UserBattleTag), rows)


def _fantasy_users(session: OrmSession, sheets: Sheets, users: Users) -> None:
    """The captains and bettors on no roster, mapped before the sheets that
    name them. A stored player is reused as it stands."""
    rows = _rows(sheets.get("Fantasy Users"), ["ID"])
    values = [
        UserCreate(
            battleTag=row.get("Battle Tag") or "",
            # A fantasy user plays no series, and the sheet carries no race
            race=Race.RANDOM,
            name=row.get("Name") or row.get("Battle Tag") or "",
            discordTag=row.get("Discord Tag") or "",
            discordId=row.get("Discord ID") or "",
        )
        for row in rows
    ]
    unknown = [v for v in values if _key(v) not in users.by_tag]
    if unknown:
        users.by_tag |= _people(session, unknown)
    _new_people(session, values, users)

    for row, value in zip(rows, values, strict=True):
        old_id = whole_number(row["ID"])
        if old_id is not None:
            users.by_old_id.setdefault(old_id, users.by_tag[_key(value)])


def _fantasy_teams(
    session: OrmSession,
    sheets: Sheets,
    season: Season,
    teams: dict[int, int],
    users: Users,
) -> dict[int, int]:
    """The fantasy teams of the season, matched by captain."""
    rows = _rows(sheets.get("Fantasy Teams"), ["Name", "Captain ID"])
    stored = {
        fteam.captain_id: fteam
        for fteam in session.scalars(
            select(FantasyTeam).where(col(FantasyTeam.season_id) == season.id)
        )
    }

    written: list[FantasyTeam] = []
    old_ids: dict[int, FantasyTeam] = {}
    for row in rows:
        captain = users.by_old_id.get(whole_number(row["Captain ID"]))
        if not captain:
            logger.warning(f"Skipping fantasy team - captain not named: {row['Name']}")
            continue
        values = FantasyTeamCreate(
            name=row["Name"],
            season_id=ident(season),
            captain_id=ident(captain),
            drafted_team_id=teams.get(whole_number(row["Drafted Team ID"])),
            drafted_race=row.get("Drafted Race"),
        )
        fteam = stored.get(captain.id)
        if fteam:
            fteam.sqlmodel_update(values.model_dump(exclude_unset=True))
        else:
            fteam = FantasyTeam(**values.model_dump())
            written.append(fteam)
            stored[captain.id] = fteam
        old_id = whole_number(row["ID"])
        if old_id:
            old_ids[old_id] = fteam
    session.add_all(written)
    session.flush()
    return {
        old_id: fteam.id for old_id, fteam in old_ids.items() if fteam.id is not None
    }


def _fantasy_players(
    session: OrmSession, sheets: Sheets, fantasy_teams: dict[int, int], users: Users
) -> None:
    """The drafted players of each fantasy team."""
    drafted: set[tuple[int, int]] = set()
    for row in _rows(
        sheets.get("Fantasy Team Players"), ["Fantasy Team ID", "Player ID"]
    ):
        fteam_id = fantasy_teams.get(whole_number(row["Fantasy Team ID"]))
        user = users.by_old_id.get(whole_number(row["Player ID"]))
        if fteam_id and user:
            drafted.add((fteam_id, ident(user)))
    if not drafted:
        return

    linked = set(
        session.execute(
            select(
                col(DBFantasyTeamPlayer.fantasy_team_id),
                col(DBFantasyTeamPlayer.user_id),
            ).where(
                col(DBFantasyTeamPlayer.fantasy_team_id).in_(
                    set(fantasy_teams.values())
                )
            )
        ).all()
    )
    session.add_all(
        [
            DBFantasyTeamPlayer(fantasy_team_id=fteam_id, user_id=user_id)
            for fteam_id, user_id in drafted - linked
        ]
    )


def _fantasy_bets(
    session: OrmSession,
    sheets: Sheets,
    season: Season,
    series: dict[int, int],
    users: Users,
) -> int:
    """The bets of the season, matched by series and bettor. Answers how
    many rows repeat a key an earlier row of the sheet already held."""
    rows = _rows(sheets.get("Fantasy Bets"), ["Series ID", "User ID", "Winner ID"])
    if not rows:
        return 0
    stored = {
        (bet.series_id, bet.user_id): bet
        for bet in session.scalars(
            select(FantasyBet).where(col(FantasyBet.season_id) == season.id)
        )
    }

    written: list[FantasyBet] = []
    seen: set[tuple[int, int]] = set()
    duplicates = 0
    for row in rows:
        series_id = series.get(whole_number(row["Series ID"]))
        user = users.by_old_id.get(whole_number(row["User ID"]))
        winner = users.by_old_id.get(whole_number(row["Winner ID"]))
        if not series_id or not user or not winner:
            logger.warning(
                f"Skipping fantasy bet - row not in the workbook: {row['ID']}"
            )
            continue
        values = FantasyBetCreate(
            season_id=ident(season),
            series_id=series_id,
            user_id=ident(user),
            winner_id=ident(winner),
            bet_points=whole_number(row["Bet Points"]) or 0,
        )
        key = (series_id, ident(user))
        if key in seen:
            duplicates += 1
        seen.add(key)
        bet = stored.get(key)
        if bet:
            bet.sqlmodel_update(values.model_dump(exclude_unset=True))
        else:
            bet = FantasyBet(**values.model_dump())
            written.append(bet)
            stored[key] = bet
    session.add_all(written)
    if duplicates:
        logger.warning(f"Skipped {duplicates} repeated rows of the Fantasy Bets sheet")
    return duplicates
