"""The event routes. Reads are open; every write asks for an admin."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    EventServiceDep,
    OptionalLogin,
    RequireLogin,
    UserServiceDep,
    require_admin,
)
from app.models.enums import EventKind
from app.models.event_division import EventDivisionWrite
from app.models.event_entrant import (
    EntrantAdd,
    EntrantPlacement,
    EntrantSignup,
    EventEntrantPublic,
    SeedWrite,
)
from app.models.event_stage import (
    DivisionStandings,
    EventStagePublic,
    EventStageWrite,
)
from app.models.season import (
    EventCreate,
    EventDiscordPost,
    EventPublic,
    EventUpdate,
    MemberEventRow,
)
from app.models.series import StageSeriesPublic
from app.services import discord_posts, stage_engine

router = APIRouter(tags=["events"])


@router.get("/events")
def get_events(
    service: EventServiceDep,
    claims: OptionalLogin,
    kind: EventKind | None = None,
    league_id: int | None = None,
    published: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EventPublic]:
    """Return one page of events, at most 500, each with its computed phase.

    A draft reads for an admin only; every other caller sees the published
    events whatever the filter asks for.
    """
    return service.get_all(
        kind=kind,
        league_id=league_id,
        published=published,
        limit=limit,
        offset=offset,
        claims=claims,
    )


@router.get("/me/events")
def get_my_events(
    service: EventServiceDep, users: UserServiceDep, claims: RequireLogin
) -> list[MemberEventRow]:
    """Return the published events with the caller's own state on each.

    One read for every kind: the entrant, the check-in shape and window, the
    next round and the one action the page offers.
    """
    return service.events_for_member(users.id_by_discord_id(claims["sub"]))


@router.get("/events/{event_id}")
def get_event(
    event_id: int, service: EventServiceDep, claims: OptionalLogin
) -> EventPublic:
    """Return one event with its stages, its divisions and its entrant count.

    A draft reads for an admin only; every other caller is answered not found.
    """
    return service.get(event_id, claims=claims)


@router.post("/events", status_code=201, dependencies=[Depends(require_admin)])
def add_event(data: EventCreate, service: EventServiceDep) -> EventPublic:
    """Create an event with the stages the body names, or one default stage."""
    return service.add(data)


@router.put("/events/{event_id}", dependencies=[Depends(require_admin)])
def update_event(
    event_id: int, data: EventUpdate, service: EventServiceDep
) -> EventPublic:
    """Change the event fields the body names."""
    return service.update(event_id, data)


@router.put("/events/{event_id}/stages", dependencies=[Depends(require_admin)])
def set_stages(
    event_id: int, stages: list[EventStageWrite], service: EventServiceDep
) -> EventPublic:
    """Replace the stage list; the order of the body is the order they play in."""
    return service.set_stages(event_id, stages)


@router.post("/events/{event_id}/discord-post", dependencies=[Depends(require_admin)])
def post_event_card(event_id: int, data: EventDiscordPost) -> dict[str, str]:
    """Post the event card with its two buttons, or edit the one in the channel.

    A draft has no page to send anyone to and is answered not found.
    """
    return {"status": discord_posts.post_event(event_id, data.channel_id)}


@router.get("/events/{event_id}/entrants")
def get_entrants(event_id: int, service: EventServiceDep) -> list[EventEntrantPublic]:
    """Every entrant of the event, with its rating on the signup race and warnings."""
    return service.get_entrants(event_id)


@router.post("/events/{event_id}/entrants", status_code=201)
def add_entrant(
    event_id: int,
    data: EntrantSignup,
    claims: OptionalLogin,
    service: EventServiceDep,
) -> EventEntrantPublic:
    """Sign the caller up, or the team the caller captains."""
    return service.add_entrant(event_id, data, claims)


@router.post(
    "/events/{event_id}/entrants/admin",
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def add_entrant_as_admin(
    event_id: int, data: EntrantAdd, service: EventServiceDep
) -> EventEntrantPublic:
    """Enter any player or team, whether signups stand open or not."""
    return service.add_entrant_as_admin(event_id, data)


@router.delete("/events/{event_id}/entrants/me", status_code=204)
def withdraw(event_id: int, claims: RequireLogin, service: EventServiceDep) -> None:
    """Withdraw the caller's own signup; the row stays and reads withdrawn."""
    service.withdraw(event_id, claims)


@router.post("/events/{event_id}/entrants/{entrant_id}/checkin")
def check_in(
    event_id: int,
    entrant_id: int,
    claims: RequireLogin,
    service: EventServiceDep,
) -> EventEntrantPublic:
    """Check one entrant in: the caller's own row, or any row for an admin."""
    return service.check_in(event_id, entrant_id, claims)


@router.delete(
    "/events/{event_id}/entrants/{entrant_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def remove_entrant(event_id: int, entrant_id: int, service: EventServiceDep) -> None:
    """Remove one entrant row."""
    service.remove_entrant(event_id, entrant_id)


@router.put(
    "/events/{event_id}/entrants/{entrant_id}",
    dependencies=[Depends(require_admin)],
)
def place_entrant(
    event_id: int,
    entrant_id: int,
    data: EntrantPlacement,
    service: EventServiceDep,
) -> EventEntrantPublic:
    """Move one entrant into a division and mark it placed by hand."""
    return service.place_entrant(event_id, entrant_id, data)


@router.put("/events/{event_id}/divisions", dependencies=[Depends(require_admin)])
def set_divisions(
    event_id: int, divisions: list[EventDivisionWrite], service: EventServiceDep
) -> EventPublic:
    """Replace the division list; the order of the body is their position."""
    return service.set_divisions(event_id, divisions)


@router.post(
    "/events/{event_id}/divisions/assign", dependencies=[Depends(require_admin)]
)
def assign_divisions(event_id: int, service: EventServiceDep) -> EventPublic:
    """Cut the entrants into divisions and answer the count each one holds."""
    return service.assign_divisions(event_id)


@router.put(
    "/events/{event_id}/stages/{stage_id}/seeds",
    dependencies=[Depends(require_admin)],
)
def set_seeds(
    event_id: int, stage_id: int, data: SeedWrite, service: EventServiceDep
) -> list[EventEntrantPublic]:
    """Seed the entrants 1..n inside each division, in seed order."""
    return service.set_seeds(event_id, stage_id, data)


@router.post(
    "/events/{event_id}/stages/{stage_id}/seeds/lock",
    dependencies=[Depends(require_admin)],
)
def lock_seeds(
    event_id: int, stage_id: int, service: EventServiceDep
) -> EventStagePublic:
    """Lock the seeds of the stage; a later seed write is refused."""
    return service.lock_seeds(event_id, stage_id)


@router.post(
    "/events/{event_id}/stages/{stage_id}/generate",
    dependencies=[Depends(require_admin)],
)
def generate_stage(event_id: int, stage_id: int) -> dict[str, int]:
    """Create every series of the stage from the seeds, one bracket per division."""
    return stage_engine.generate(event_id, stage_id)


@router.get("/events/{event_id}/stages/{stage_id}/series")
def get_stage_series(event_id: int, stage_id: int) -> StageSeriesPublic:
    """The rounds of the stage and every series it holds, for the run page."""
    return stage_engine.series_of(event_id, stage_id)


@router.get("/events/{event_id}/stages/{stage_id}/standings")
def get_standings(event_id: int, stage_id: int) -> list[DivisionStandings]:
    """The table of every division of the stage, computed on the read."""
    return stage_engine.standings_of(event_id, stage_id)


@router.post(
    "/events/{event_id}/stages/{stage_id}/advance",
    dependencies=[Depends(require_admin)],
)
def advance_stage(event_id: int, stage_id: int) -> dict[str, int]:
    """Seed the next stage from the top places of every division's table."""
    return stage_engine.advance(event_id, stage_id)
