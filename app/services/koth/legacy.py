"""The old /koth/* payloads, answered from the event model.

Nightbot, the stream overlay and the bookmarks of the run crew still call
these paths, so every read maps a night's event, its entrants and its series
onto the shapes the KOTH service answered before. The four koth_* tables are
dropped, so app/models/koth_legacy.py holds those shapes alone.

A signup is an entrant, a match is a series of the chain, a bracket is a
division and the king is the winner of the last scored series of his chain.
"""

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.battle_tags import fold
from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.base import ident
from app.models.enums import EventKind, Race, SignupChannel
from app.models.event_division import EventDivision
from app.models.event_entrant import EntrantPlacement, EventEntrant
from app.models.event_stage import EventStage
from app.models.koth_legacy import (
    KothEventCreate,
    KothEventPublic,
    KothEventSummary,
    KothEventUpdate,
    KothMatchCreate,
    KothMatchParticipantPublic,
    KothMatchPublic,
    KothMatchUpdate,
    KothSignupPublic,
)
from app.models.koth_night import NightOpen
from app.models.relationships import DBEventRound
from app.models.season import EventUpdate, Season
from app.models.series import Series, SeriesUpdate
from app.models.types import utcnow
from app.models.user import User
from app.services import stage_engine
from app.services.battle_tags import person_by_tag
from app.services.events import EventService, _stats_for, _users_for, _w3c_season
from app.services.koth import carry, night, nightbot
from app.services.series import SeriesService

# A KOTH series is one player against one player, so every match reads this way
GAME_MODE = "1v1"
TEAMS = 2
# The thresholds a night reads when it carries no divisions
DEFAULT_THRESHOLDS = (1450, 1600)
NO_MANUAL_KING = (
    "The night decides the king by results. Score the throne series instead."
)


# ============ Events ============
def all_events() -> list[KothEventSummary]:
    """Every night, oldest first, without its signups and matches."""
    with Session.begin() as session:
        rows = _nights(session)
        bounds = _thresholds(session, [ident(row) for row in rows])
        return [
            KothEventSummary(**_fields(row, bounds.get(ident(row)))) for row in rows
        ]


def active_event() -> KothEventPublic:
    """The night that takes signups: the newest published one still open."""
    with Session.begin() as session:
        row = night.last_night(session, open_only=True)
        if row is None:
            raise NotFoundError("No active KOTH event found")
        return _public(session, row)


def event(event_id: int) -> KothEventPublic:
    """One night with its signups and its matches."""
    with Session.begin() as session:
        return _public(session, _night(session, event_id))


def add_event(data: KothEventCreate) -> KothEventPublic:
    """Open a night from the old create body: the date and the two thresholds."""
    opened = night.open_night(
        NightOpen(
            starts_at=data.event_date,
            name=data.name,
            lower_bounds=[0, data.bracket_1_threshold, data.bracket_2_threshold],
        )
    )
    if not data.is_active:
        EventService().update(opened.id, EventUpdate(signups_open=False))
    return event(opened.id)


def update_event(event_id: int, data: KothEventUpdate) -> KothEventPublic:
    """Write the fields the old body names; the thresholds move the brackets."""
    named = data.model_dump(exclude_unset=True)
    with Session.begin() as session:
        _night(session, event_id)
    write: dict[str, Any] = {}
    if "name" in named:
        write["name"] = data.name
    if "description" in named:
        write["description"] = data.description
    if "event_date" in named:
        write["starts_at"] = data.event_date
    if "is_active" in named:
        write["signups_open"] = data.is_active
    if write:
        EventService().update(event_id, EventUpdate(**write))
    if "bracket_1_threshold" in named or "bracket_2_threshold" in named:
        _move_thresholds(event_id, data.bracket_1_threshold, data.bracket_2_threshold)
    return event(event_id)


def activate_event(event_id: int) -> KothEventPublic:
    """Open this night and close every other one, the way the old flag did."""
    with Session.begin() as session:
        row = _night(session, event_id)
        session.execute(
            update(Season)
            .where(col(Season.kind) == EventKind.koth, col(Season.id) != event_id)
            .values(signups_open=False),
            execution_options={"synchronize_session": False},
        )
        row.published = True
        row.signups_open = True
    return event(event_id)


def delete_event(event_id: int) -> None:
    """Delete a night: its series and its rounds first, then the event row."""
    with Session.begin() as session:
        _night(session, event_id)
        rounds = select(col(DBEventRound.id)).where(
            col(DBEventRound.season_id) == event_id
        )
        session.execute(delete(Series).where(col(Series.round_id).in_(rounds)))
        session.execute(
            delete(DBEventRound).where(col(DBEventRound.season_id) == event_id)
        )
        session.execute(delete(Season).where(col(Season.id) == event_id))


# ============ Signups ============
def signups_of(
    event_id: int, limit: int | None = None, offset: int = 0
) -> list[KothSignupPublic]:
    """One page of the signups of a night, the brackets in order."""
    with Session.begin() as session:
        rows, _ = _payloads(session, _night(session, event_id))
    return rows[offset : offset + limit if limit is not None else None]


def create_signups(
    battle_tag: str,
    races: list[str] | None = None,
    event_id: int | None = None,
    channel: SignupChannel = SignupChannel.twitch,
) -> list[KothSignupPublic]:
    """Enter one player in a night; his entrants are the list the old route gave.

    A night holds one entrant per race, so a body naming several races writes
    one row per race.
    """
    with Session.begin() as session:
        event_id = (
            ident(night.tonight(session))
            if event_id is None
            else ident(_night(session, event_id))
        )
    for race in races or [None]:
        nightbot.enter(event_id, battle_tag, race, channel)
    return _mine(event_id, battle_tag)


def withdraw(battle_tag: str, race: str | None = None) -> None:
    """Withdraw the player from the night that takes signups.

    A command that names a race withdraws that race alone; one that names none
    withdraws every race the player entered.
    """
    named = _race(race)
    with Session.begin() as session:
        event_id = ident(night.tonight(session))
        # Any tag the person holds withdraws them
        user = person_by_tag(session, battle_tag)
        if user is None:
            raise NotFoundError("No active signup to withdraw")
        statement = select(EventEntrant).where(
            col(EventEntrant.event_id) == event_id,
            col(EventEntrant.user_id) == user.id,
            col(EventEntrant.withdrawn_at).is_(None),
        )
        if named is not None:
            statement = statement.where(col(EventEntrant.race) == named)
        rows = session.scalars(statement).all()
        if not rows:
            raise NotFoundError("No active signup to withdraw")
        for row in rows:
            row.withdrawn_at = utcnow()
        stage_engine.uncrown(session, [ident(row) for row in rows])


def set_bracket(signup_id: int, bracket: int) -> KothSignupPublic:
    """Move one entrant into the division that is the bracket named."""
    if bracket not in (1, 2, 3):
        raise BadRequestError("Bracket must be 1, 2, or 3")
    with Session.begin() as session:
        row = _entrant(session, signup_id)
        event_id = row.event_id
        wanted = {
            number: division_id
            for division_id, number in _brackets(session, event_id).items()
        }
        if bracket not in wanted:
            raise BadRequestError(f"This night runs no bracket {bracket}")
        division_id = wanted[bracket]
    EventService().place_entrant(
        event_id, signup_id, EntrantPlacement(division_id=division_id)
    )
    return _one_signup(event_id, signup_id)


def crown(signup_id: int) -> KothSignupPublic:
    """Put this player on the throne seat of his chain, before any result.

    The night decides the king by results, so the crown only moves while the
    chain is unplayed: the move swaps the two sides of the opening series.
    """
    with Session.begin() as session:
        row = _entrant(session, signup_id)
        event_id = row.event_id
        chain = _chain(night.series_of(session, event_id), row.division_id)
        if not chain or any(stage_engine.scored(series) for series in chain):
            raise BadRequestError(NO_MANUAL_KING)
        first = chain[0]
        if row.user_id not in (first.player1_id, first.player2_id):
            raise BadRequestError(NO_MANUAL_KING)
        if first.player1_id != row.user_id:
            first.player1_id, first.player2_id = first.player2_id, first.player1_id
            first.host_player_id = first.player1_id or 0
    return _one_signup(event_id, signup_id)


def delete_signup(signup_id: int) -> None:
    """Remove one entrant from its night."""
    with Session.begin() as session:
        event_id = _entrant(session, signup_id).event_id
    EventService().remove_entrant(event_id, signup_id)


def kings_of(event_id: int) -> dict[int, list[KothSignupPublic]]:
    """The king of each bracket: at most one, the winner of its last series."""
    kings: dict[int, list[KothSignupPublic]] = {}
    for row in signups_of(event_id):
        if row.is_king == 1:
            kings.setdefault(row.bracket, []).append(row)
    return kings


# ============ Matches ============
def matches_of(
    event_id: int, limit: int | None = None, offset: int = 0
) -> list[KothMatchPublic]:
    """One page of the series of a night, the brackets in order."""
    with Session.begin() as session:
        _, rows = _payloads(session, _night(session, event_id))
    return rows[offset : offset + limit if limit is not None else None]


def create_match(
    data: KothMatchCreate, participants: list[dict[str, int]]
) -> KothMatchPublic:
    """Write one series at the end of the chain the two entrants play in."""
    teams = {row["team_number"] for row in participants}
    if len(teams) != data.num_teams:
        raise BadRequestError(
            f"Expected {data.num_teams} teams, but participants are assigned"
            f" to {len(teams)} teams"
        )
    for number in range(1, data.num_teams + 1):
        if number not in teams:
            raise BadRequestError(f"Team {number} has no participants")
    if data.num_teams != TEAMS or len(participants) != TEAMS:
        raise BadRequestError("A KOTH series is one player against one player")
    with Session.begin() as session:
        sides = {
            row["team_number"]: _entrant(session, row["signup_id"])
            for row in participants
        }
        first, second = sides[1], sides[2]
        if (first.event_id, first.division_id) != (second.event_id, second.division_id):
            raise BadRequestError("All participants must be in the same bracket")
        event_id = first.event_id
        stage = _stage(session, event_id)
        chain = _chain(night.series_of(session, event_id), first.division_id)
        row = Series(
            round_id=ident(_round_of(session, stage, chain)),
            division_id=first.division_id,
            sequence=(chain[-1].sequence or len(chain)) + 1 if chain else 1,
            host_player_id=first.user_id or 0,
            player1_id=first.user_id,
            player2_id=second.user_id,
            entrant1_id=ident(first),
            entrant2_id=ident(second),
        )
        session.add(row)
        session.flush()
        series_id = ident(row)
    return _one_match(event_id, series_id)


def update_match(match_id: int, data: KothMatchUpdate) -> KothMatchPublic:
    """Write what a series of a chain carries: its bracket and its result."""
    named = data.model_dump(exclude_unset=True)
    if named.get("winner_team_number") is not None:
        return match_result(match_id, data.winner_team_number or 0)
    with Session.begin() as session:
        row = _series(session, match_id)
        event_id = _event_of(session, row)
        if named.get("bracket") is not None:
            wanted = {
                number: division_id
                for division_id, number in _brackets(session, event_id).items()
            }
            if data.bracket not in wanted:
                raise BadRequestError(f"This night runs no bracket {data.bracket}")
            row.division_id = wanted[data.bracket or 0]
    return _one_match(event_id, match_id)


def match_result(match_id: int, winner_team_number: int) -> KothMatchPublic:
    """Score the series: the winner takes the maps a win of this stage takes."""
    if winner_team_number < 1 or winner_team_number > TEAMS:
        raise BadRequestError(f"Winner team number must be between 1 and {TEAMS}")
    with Session.begin() as session:
        row = _series(session, match_id)
        event_id = _event_of(session, row)
        wins = stage_engine.series_wins(session, row)
    first, second = (wins, 0) if winner_team_number == 1 else (0, wins)
    SeriesService().update(
        match_id,
        SeriesUpdate(player1_score=first, player2_score=second),
        force=True,
    )
    return _one_match(event_id, match_id)


def delete_match(match_id: int) -> None:
    """Remove one series from its chain."""
    with Session.begin() as session:
        _series(session, match_id)
    SeriesService().delete(match_id)


# ============ Reads behind the payloads ============
def _night(session: OrmSession, event_id: int) -> Season:
    """The night behind an old event id; another kind of event is no night."""
    row = session.get(Season, event_id)
    if row is None or row.kind is not EventKind.koth:
        raise NotFoundError(f"KOTH Event not found by Id: {event_id}")
    return row


def _is_night(session: OrmSession, event_id: int | None) -> bool:
    """Whether that event id names a KOTH night, so these paths may write it."""
    row = session.get(Season, event_id) if event_id is not None else None
    return row is not None and row.kind is EventKind.koth


def _nights(session: OrmSession) -> list[Season]:
    return list(
        session.scalars(
            select(Season)
            .where(col(Season.kind) == EventKind.koth)
            .order_by(col(Season.id))
        )
    )


def _entrant(session: OrmSession, signup_id: int) -> EventEntrant:
    """The signup behind an old id; a signup of another kind of event is none."""
    row = session.get(EventEntrant, signup_id)
    if row is None or not _is_night(session, row.event_id):
        raise NotFoundError(f"Signup not found by Id: {signup_id}")
    return row


def _series(session: OrmSession, match_id: int) -> Series:
    """The series behind an old id; a series of another kind of event is none."""
    row = session.get(Series, match_id)
    if row is None:
        raise NotFoundError(f"Match not found by Id: {match_id}")
    round_row = session.get(DBEventRound, row.round_id)
    if round_row is None or not _is_night(session, round_row.season_id):
        raise NotFoundError(f"Match not found by Id: {match_id}")
    return row


def _event_of(session: OrmSession, row: Series) -> int:
    """The night a series is played in, through the round it sits in."""
    round_row = session.get(DBEventRound, row.round_id)
    if round_row is None:
        raise NotFoundError(f"Match not found by Id: {ident(row)}")
    return round_row.season_id


def _stage(session: OrmSession, event_id: int) -> EventStage:
    stage = session.scalars(
        select(EventStage)
        .where(col(EventStage.event_id) == event_id)
        .order_by(col(EventStage.position))
    ).first()
    if stage is None:
        raise BadRequestError("This night runs no stage to play a match in")
    return stage


def _round_of(
    session: OrmSession, stage: EventStage, chain: list[Series]
) -> DBEventRound:
    """The round a new series is played in: the chain's own, else the stage's."""
    held = session.get(DBEventRound, chain[-1].round_id) if chain else None
    if held is not None:
        return held
    first = session.scalars(
        select(DBEventRound)
        .where(col(DBEventRound.stage_id) == stage.id)
        .order_by(col(DBEventRound.number))
    ).first()
    if first is not None:
        return first
    highest = session.scalar(
        select(func.max(col(DBEventRound.number))).where(
            col(DBEventRound.season_id) == stage.event_id
        )
    )
    row = DBEventRound(
        stage_id=ident(stage),
        season_id=stage.event_id,
        number=(highest or 0) + 1,
        name="Round 1",
    )
    session.add(row)
    session.flush()
    return row


def _brackets(session: OrmSession, event_id: int) -> dict[int, int]:
    """Each division of a night by its bracket number; position 1 is the top."""
    rows = night.divisions_of(session, event_id)
    return {ident(row): len(rows) + 1 - row.position for row in rows}


def _thresholds(
    session: OrmSession, event_ids: list[int]
) -> dict[int, tuple[int, int]]:
    """The two MMR thresholds of each night, from the bounds of its brackets."""
    rows = session.scalars(
        select(EventDivision)
        .where(col(EventDivision.event_id).in_(event_ids))
        .order_by(col(EventDivision.position))
    ).all()
    bounds: dict[int, list[int]] = {}
    for row in rows:
        bounds.setdefault(row.event_id, []).append(row.lower_bound or 0)
    return {
        event_id: (
            band[1] if len(band) > 1 else DEFAULT_THRESHOLDS[0],
            band[0],
        )
        for event_id, band in bounds.items()
    }


def _move_thresholds(event_id: int, first: int | None, second: int | None) -> None:
    """Move the bounds of the brackets; the entrants keep the divisions they hold."""
    with Session.begin() as session:
        rows = night.divisions_of(session, event_id)
        if len(rows) > 1 and first is not None:
            rows[1].lower_bound = first
        if rows and second is not None:
            rows[0].lower_bound = second


def _chain(rows: list[Series], division_id: int | None) -> list[Series]:
    """The series of one division, in the order the chain plays them."""
    return [row for row in rows if row.division_id == division_id]


def _fields(event: Season, bounds: tuple[int, int] | None) -> dict[str, Any]:
    """The old event columns, read off the night; a closed night is not active."""
    band = bounds or DEFAULT_THRESHOLDS
    fields: dict[str, Any] = {
        "id": ident(event),
        "name": event.name,
        "description": event.description,
        "is_active": bool(event.published and event.signups_open),
        "bracket_1_threshold": band[0],
        "bracket_2_threshold": band[1],
    }
    if event.starts_at is not None:
        fields["event_date"] = event.starts_at
    return fields


def _public(session: OrmSession, event: Season) -> KothEventPublic:
    signups, matches = _payloads(session, event)
    bounds = _thresholds(session, [ident(event)])
    return KothEventPublic(
        **_fields(event, bounds.get(ident(event))), signups=signups, matches=matches
    )


def _payloads(
    session: OrmSession, event: Season
) -> tuple[list[KothSignupPublic], list[KothMatchPublic]]:
    """The signups and the matches of one night, in the shapes the old routes gave."""
    event_id = ident(event)
    brackets = _brackets(session, event_id)
    rows = list(
        session.scalars(
            select(EventEntrant)
            .where(col(EventEntrant.event_id) == event_id)
            .order_by(col(EventEntrant.id))
        )
    )
    season = _w3c_season(session)
    users = _users_for(session, rows, season)
    chains: dict[int | None, list[Series]] = {}
    for row in night.series_of(session, event_id):
        chains.setdefault(row.division_id, []).append(row)
    kings: set[int | None] = set(carry.kings_of(session, event).values())
    beaten = {
        _loser(row)
        for chain in chains.values()
        for row in chain
        if stage_engine.scored(row)
    } - {None}
    signups = [
        _signup(event_id, row, users.get(row.user_id), brackets, season, kings, beaten)
        for row in rows
    ]
    by_user = {
        row.user_id: public
        for row, public in zip(rows, signups, strict=True)
        if row.user_id is not None
    }
    signups.sort(key=lambda row: (row.bracket, -row.mmr, row.id))
    matches = [
        _match(event_id, row, brackets, by_user)
        for chain in chains.values()
        for row in chain
    ]
    matches.sort(key=lambda row: (row.bracket, row.id))
    return signups, matches


def _loser(row: Series) -> int | None:
    """The side a scored series sends home; a draw sends neither."""
    winner = stage_engine.winner_of(row)
    if winner is None:
        return None
    return row.player2_id if winner == row.player1_id else row.player1_id


def _signup(
    event_id: int,
    row: EventEntrant,
    user: User | None,
    brackets: dict[int, int],
    season: int,
    kings: set[int | None],
    beaten: set[int | None],
) -> KothSignupPublic:
    """One entrant as the old signup shape; the king and the crown are derived."""
    rating = _stats_for(user, row.race, season)[0] if user is not None else None
    tag = (user.battleTag if user is not None else None) or ""
    return KothSignupPublic(
        id=ident(row),
        event_id=event_id,
        # The model stores the channel a signup came through, never a Twitch name
        twitch_username=None,
        battle_tag=tag,
        w3c_name=tag,
        race=row.race,
        mmr=row.mmr_at_seed or rating or 0,
        bracket=brackets.get(row.division_id or 0, 1),
        is_king=1 if row.user_id in kings else 0,
        is_active=0 if row.withdrawn_at is not None or row.user_id in beaten else 1,
        country=user.country if user is not None else None,
    )


def _match(
    event_id: int,
    row: Series,
    brackets: dict[int, int],
    by_user: dict[int, KothSignupPublic],
) -> KothMatchPublic:
    """One series of a chain as the old match shape: two sides, one map."""
    winner = stage_engine.winner_of(row)
    series_id = ident(row)
    return KothMatchPublic(
        id=series_id,
        event_id=event_id,
        bracket=brackets.get(row.division_id or 0, 1),
        game_mode=GAME_MODE,
        num_teams=TEAMS,
        winner_team_number=None
        if winner is None
        else (1 if winner == row.player1_id else 2),
        participants=[
            KothMatchParticipantPublic(
                id=signup.id,
                match_id=series_id,
                signup_id=signup.id,
                team_number=team,
                signup=signup,
            )
            for team, user_id in ((1, row.player1_id), (2, row.player2_id))
            if user_id is not None and (signup := by_user.get(user_id)) is not None
        ],
    )


def _mine(event_id: int, battle_tag: str) -> list[KothSignupPublic]:
    """The signups of the person who holds the battle tag in a night. A row
    shows the person's active tag, which a second tag differs from."""
    with Session.begin() as session:
        user = person_by_tag(session, battle_tag)
        tag = fold((user.battleTag if user is not None else None) or battle_tag)
    return [
        row
        for row in signups_of(event_id)
        if (row.battle_tag or "").strip().lower() == tag
    ]


def _one_signup(event_id: int, signup_id: int) -> KothSignupPublic:
    """One signup read back after a write."""
    for row in signups_of(event_id):
        if row.id == signup_id:
            return row
    raise NotFoundError(f"Signup not found by Id: {signup_id}")


def _one_match(event_id: int, match_id: int) -> KothMatchPublic:
    """One match read back after a write."""
    for row in matches_of(event_id):
        if row.id == match_id:
            return row
    raise NotFoundError(f"Match not found by Id: {match_id}")


def _race(race: str | None) -> Race | None:
    """The race a query names; an unknown one answers 400 as it always did."""
    if not race:
        return None
    try:
        return Race.from_text(race)
    except ValueError as error:
        raise BadRequestError(f"Invalid race '{race}'") from error
