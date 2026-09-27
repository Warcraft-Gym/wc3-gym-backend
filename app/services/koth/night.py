"""Open and close a KOTH night.

The night is an event of the KOTH league: one stage of format koth, best of
one, and three divisions that are the brackets. Nothing new is stored for
"tonight" or "finished": tonight is the newest published KOTH event nobody
closed that started less than a day ago, and closing it deletes the series
nobody played, so every series left carries a result. One night is open at a
time, and opening the next one closes a night that expired.
"""

from datetime import datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.base import ident
from app.models.enums import EventKind, LeagueKind, SignupPolicy, StageFormat
from app.models.event_division import EventDivision, EventDivisionWrite
from app.models.event_history import KothHistoryEvent
from app.models.event_stage import EventStageWrite
from app.models.koth_night import NightOpen
from app.models.league import League
from app.models.relationships import DBEventRound
from app.models.season import EventCreate, EventPublic, Season
from app.models.series import Series
from app.models.types import utcnow
from app.services import awards, stage_engine
from app.services.events import EventService

# The MMR each bracket opens at, weakest first, before any night has run
DEFAULT_BOUNDS = (0, 1450, 1600)
LEAGUE_SHORT_NAME = "KOTH"
BRACKETS = 3
ADMIN = {"role": "admin"}
# A night nobody closed stops being tonight this long after it starts
NIGHT_EXPIRES_AFTER = timedelta(hours=24)


def open_night(data: NightOpen) -> EventPublic:
    """Write tonight's night: the event, its koth stage and its brackets."""
    name = data.name or _in_words(data.starts_at)
    with Session.begin() as session:
        unclosed = _unclosed(session)
        if unclosed is not None and is_tonight(unclosed):
            raise ApiError(409, {"error": "Close the open night first."})
        expired = ident(unclosed) if unclosed is not None else None
    # A night that expired unclosed is closed now, so its series and awards settle
    if expired is not None:
        close_night(expired)
    with Session.begin() as session:
        league_id = _league(session)
        bounds = list(data.lower_bounds or _last_bounds(session) or DEFAULT_BOUNDS)
        if len(bounds) != BRACKETS:
            raise BadRequestError(
                f"A night takes {BRACKETS} lower bounds, weakest first"
            )
        if _named(session, name) is not None:
            raise BadRequestError(f"An event is already named {name}")
    service = EventService()
    night = service.add(
        EventCreate(
            name=name,
            league_id=league_id,
            kind=EventKind.koth,
            signup_policy=SignupPolicy.anyone,
            published=True,
            starts_at=data.starts_at,
            checkin_enabled=False,
            multi_entry=True,
            stages=[EventStageWrite(format=StageFormat.koth, best_of=1)],
        )
    )
    # The divisions read strongest first, so the highest bracket takes position 1
    return service.set_divisions(
        night.id,
        [
            EventDivisionWrite(name=f"Bracket {number}", lower_bound=bound)
            for number, bound in reversed(list(enumerate(bounds, start=1)))
        ],
    )


def close_night(event_id: int) -> EventPublic:
    """Delete the series at the end of every chain nobody played, and close it.

    A chain grows while the admin names series, so nothing but this call ends
    the night: it stamps `closed_at`, which is what makes the night read
    finished, and the closed night takes no further signup. The close then
    pays the night's awards, so the king of every bracket holds its champion
    place.
    """
    with Session.begin() as session:
        night = session.get(Season, event_id)
        if night is None or night.kind is not EventKind.koth:
            raise NotFoundError(f"KOTH night not found by id: {event_id}")
        if session.get(KothHistoryEvent, event_id) is not None:
            raise BadRequestError(
                "An archived night is already closed; its source results are preserved"
            )
        chains: dict[int | None, list[Series]] = {}
        for row in series_of(session, event_id):
            chains.setdefault(row.division_id, []).append(row)
        for chain in chains.values():
            while chain and not stage_engine.scored(chain[-1]):
                session.delete(chain.pop())
        night.signups_open = False
        night.closed_at = utcnow()
        session.flush()
        awards.close_event(session, event_id)
    return EventService().get(event_id, claims=ADMIN)


def tonight(session: OrmSession) -> Season:
    """The night that runs: the newest published one nobody closed yet."""
    night = last_night(session, open_only=True)
    if night is None:
        raise BadRequestError("No KOTH night is open")
    return night


def taking_signups(session: OrmSession) -> Season:
    """Tonight, refused while its signups stand closed."""
    night = tonight(session)
    if not night.signups_open:
        raise BadRequestError("Signups are closed")
    return night


def is_tonight(night: Season) -> bool:
    """Whether the night is still tonight: nobody closed it and it has not expired."""
    return (
        night.closed_at is None
        and night.starts_at is not None
        and night.starts_at > utcnow() - NIGHT_EXPIRES_AFTER
    )


def _unclosed(session: OrmSession) -> Season | None:
    """The night nobody closed, published or not, expired or not."""
    return session.scalars(
        _koth_nights()
        .where(col(Season.closed_at).is_(None))
        .order_by(col(Season.id).desc())
    ).first()


def _koth_nights() -> Select[tuple[Season]]:
    """Every KOTH night that is not archived."""
    return select(Season).where(
        col(Season.kind) == EventKind.koth,
        ~col(Season.id).in_(select(col(KothHistoryEvent.event_id))),
    )


def last_night(session: OrmSession, open_only: bool = False) -> Season | None:
    """The newest KOTH night, or tonight: published, not closed, not expired."""
    statement = _koth_nights().order_by(col(Season.id).desc())
    if open_only:
        statement = statement.where(
            col(Season.published).is_(True),
            col(Season.closed_at).is_(None),
            col(Season.starts_at) > utcnow() - NIGHT_EXPIRES_AFTER,
        )
    return session.scalars(statement).first()


def divisions_of(session: OrmSession, event_id: int) -> list[EventDivision]:
    """The brackets of the night, the strongest first."""
    return list(
        session.scalars(
            select(EventDivision)
            .where(col(EventDivision.event_id) == event_id)
            .order_by(col(EventDivision.position))
        )
    )


def series_of(session: OrmSession, event_id: int) -> list[Series]:
    """Every series of the night, each chain in the order it is played."""
    rounds = select(col(DBEventRound.id)).where(col(DBEventRound.season_id) == event_id)
    return list(
        session.scalars(
            select(Series)
            .where(col(Series.round_id).in_(rounds))
            .order_by(col(Series.sequence), col(Series.id))
        )
    )


def _league(session: OrmSession) -> int:
    """The KOTH league, written the first time a night opens."""
    league = session.scalars(
        select(League).where(col(League.short_name) == LEAGUE_SHORT_NAME)
    ).first()
    if league is None:
        league = League(
            name="King of the Hill",
            short_name=LEAGUE_SHORT_NAME,
            kind=LeagueKind.koth,
        )
        session.add(league)
        session.flush()
    return ident(league)


def _last_bounds(session: OrmSession) -> list[int] | None:
    """The bounds of the night before, weakest first; none before the first night."""
    night = last_night(session)
    if night is None:
        return None
    bounds = [
        division.lower_bound
        for division in reversed(divisions_of(session, ident(night)))
    ]
    return None if not bounds or None in bounds else [bound or 0 for bound in bounds]


def _named(session: OrmSession, name: str) -> Season | None:
    """The event that already carries this name; the name column is unique."""
    folded = func.lower(func.trim(col(Season.name)))
    return session.scalars(select(Season).where(folded == name.strip().lower())).first()


def _in_words(when: datetime) -> str:
    """The night's date in words, which is the name a night takes by default."""
    return f"{when.day} {when:%B %Y}"
