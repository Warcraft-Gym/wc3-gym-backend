"""The event routes. Reads are open; a write asks for a runner of the event:
an admin, or an organizer the event names. A GNL season and a KOTH night name
no organizer, so their writes stay the admins'."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import (
    EventServiceDep,
    GnlEventServiceDep,
    OptionalLogin,
    RequireEventRunner,
    RequireLogin,
    RequireOrganizer,
    UserServiceDep,
    edge_cache,
    event_edge_cache,
    phase_edge_cache,
    require_admin,
    require_event_runner,
)
from app.api.search import SearchQuery
from app.models.cup_overall import CupOverallPublic
from app.models.cup_recurrence import (
    CupOccurrenceCreate,
    CupRecurrencePublic,
    CupRecurrenceRow,
    CupRecurrenceUpdate,
    CupRecurrenceWrite,
)
from app.models.cup_rounds import (
    CupLegCheckinWrite,
    CupLegPublic,
    CupLegUpdate,
    CupLegWrite,
)
from app.models.cup_series import CupStagePublic
from app.models.cup_settings import CupPinWrite
from app.models.cup_team import (
    CupTeamAdd,
    CupTeamCreate,
    MemberReplace,
    TeamInviteCreate,
    TeamInvitePublic,
)
from app.models.enums import EventKind, Race
from app.models.event_award import EventAwardPublic
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
    SeasonMapIds,
)
from app.models.series import ChallengerAdd, StageSeriesPublic, StageSeriesRow
from app.services import (
    awards,
    cup_engine,
    cup_recurrence,
    cup_rounds,
    cup_teams,
    discord_posts,
    organizers,
    stage_engine,
)
from app.services.koth import night

router = APIRouter(tags=["events"])


@router.get("/events")
def get_events(
    service: EventServiceDep,
    claims: OptionalLogin,
    response: Response,
    kind: EventKind | None = None,
    league_id: int | None = None,
    published: bool | None = None,
    archived: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EventPublic]:
    """Return one page of events, at most 500, newest start first, each with
    its computed phase. The header counts every event the filter keeps.

    `archived=false` leaves out the archived KOTH nights, `archived=true` keeps
    only them. A draft reads for an admin only; every other caller sees the
    published events whatever the filter asks for.
    """
    if claims is None:
        # An anonymous caller always sees the published-only page; an admin's
        # bearer never reaches the edge, so this never caches a draft.
        edge_cache(response, "settled")
    events, total = service.get_all(
        kind=kind,
        league_id=league_id,
        published=published,
        archived=archived,
        limit=limit,
        offset=offset,
        claims=claims,
    )
    response.headers["X-Total-Count"] = str(total)
    return events


@router.post("/events/search")
def search_events(
    service: EventServiceDep,
    claims: OptionalLogin,
    query: SearchQuery,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EventPublic]:
    """Search event fields with the same visibility and payload as the list."""
    return service.search(query, limit=limit, offset=offset, claims=claims)


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
    event_id: int, service: EventServiceDep, claims: OptionalLogin, response: Response
) -> EventPublic:
    """Return one event with its stages, its divisions and its entrant count.

    A draft reads for an admin only; every other caller is answered not found.
    """
    answer = service.get(event_id, claims=claims)
    if claims is None:
        # An admin's answer holds drafts, so only the anonymous answer is shared.
        phase_edge_cache(response, answer.phase)
    return answer


@router.post("/events", status_code=201)
def add_event(
    data: EventCreate,
    service: EventServiceDep,
    gnl: GnlEventServiceDep,
    claims: RequireOrganizer,
) -> EventPublic:
    """Create an event, applying the creation rules of the league it runs in.

    An organizer creates a small event and runs it from then on; an admin
    creates any event.
    """
    organizers.hold_to_small_events(
        claims, data.model_dump(), [stage.format for stage in data.stages]
    )
    if gnl.owns(data.league_id):
        return service.get(gnl.add(data), claims=claims)
    event = service.add(data, str(claims["sub"]))
    if claims["sub"] != "admin":
        organizers.add_to_event(event.id, claims["sub"], claims["sub"])
    return event


@router.put("/events/{event_id}")
def update_event(
    event_id: int,
    data: EventUpdate,
    service: EventServiceDep,
    claims: RequireEventRunner,
) -> EventPublic:
    """Change the event fields the body names."""
    organizers.hold_to_small_events(claims, data.model_dump(exclude_unset=True))
    return service.update(event_id, data)


@router.delete(
    "/events/{event_id}", status_code=204, dependencies=[Depends(require_event_runner)]
)
def delete_event(event_id: int, service: EventServiceDep) -> None:
    """Delete an event and the rows owned by it."""
    service.delete(event_id)


@router.put("/events/{event_id}/stages")
def set_stages(
    event_id: int,
    stages: list[EventStageWrite],
    service: EventServiceDep,
    claims: RequireEventRunner,
) -> EventPublic:
    """Replace the stage list; the order of the body is the order they play in."""
    organizers.hold_to_small_events(claims, {}, [stage.format for stage in stages])
    return service.set_stages(event_id, stages)


@router.put("/events/{event_id}/maps", dependencies=[Depends(require_event_runner)])
def set_pool(
    event_id: int, data: SeasonMapIds, service: EventServiceDep
) -> EventPublic:
    """Replace the map pool, in the order given, before any series vetoes from it."""
    return service.set_pool(event_id, data.map_ids)


@router.post("/events/{event_id}/finish", dependencies=[Depends(require_event_runner)])
def finish_event(event_id: int) -> list[EventAwardPublic]:
    """Close the event: write the places its last stage's table pays.

    The answer is the award list, best place first per division. Closing an
    event that is already closed rewrites its places.
    """
    return awards.finish(event_id)


@router.post("/events/{event_id}/reopen", dependencies=[Depends(require_event_runner)])
def reopen_event(
    event_id: int, service: EventServiceDep, claims: RequireLogin
) -> EventPublic:
    """Take the close back: the event reads by its series again and its places go."""
    awards.reopen(event_id)
    return service.get(event_id, claims=claims)


@router.post("/events/{event_id}/cancel")
def cancel_event(
    event_id: int, service: EventServiceDep, claims: RequireEventRunner
) -> EventPublic:
    """Call the event off: it reads finished, pays no place and takes no signup.

    A reopen takes the cancel back.
    """
    awards.cancel(event_id)
    return service.get(event_id, claims=claims)


@router.post("/events/{event_id}/discord-post", dependencies=[Depends(require_admin)])
def post_event_card(event_id: int, data: EventDiscordPost) -> dict[str, str]:
    """Post the event card with its two buttons, or edit the one in the channel.

    A draft has no page to send anyone to and is answered not found.
    """
    return {"status": discord_posts.post_event(event_id, data.channel_id)}


@router.get("/events/{event_id}/entrants")
def get_entrants(
    event_id: int, service: EventServiceDep, claims: OptionalLogin, response: Response
) -> list[EventEntrantPublic]:
    """Every entrant of the event, with its rating on the signup race and warnings."""
    if claims is None:
        # A runner reads seeds an event may hide, so only the anonymous answer is shared.
        event_edge_cache(response, event_id)
    return service.get_entrants(event_id, claims)


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
    dependencies=[Depends(require_event_runner)],
)
def add_entrant_as_admin(
    event_id: int, data: EntrantAdd, service: EventServiceDep
) -> EventEntrantPublic:
    """Enter any player or team, whether signups stand open or not."""
    return service.add_entrant_as_admin(event_id, data)


@router.post(
    "/events/{event_id}/entrants/{entrant_id}/replace",
    dependencies=[Depends(require_event_runner)],
)
def replace_entrant(
    event_id: int, entrant_id: int, data: EntrantAdd, service: EventServiceDep
) -> EventEntrantPublic:
    """Put another player in the place, the seed and the series of one who has
    not played yet, so a drawn bracket takes a late change without a redraw."""
    return service.replace_entrant(event_id, entrant_id, data)


@router.post("/events/{event_id}/cup-teams", status_code=201)
def sign_up_team(
    event_id: int, data: CupTeamCreate, claims: RequireLogin
) -> EventEntrantPublic:
    """Sign a team up for a team cup: the caller captains it and invites the rest."""
    return cup_teams.sign_up(event_id, data, claims)


@router.post(
    "/events/{event_id}/cup-teams/admin",
    status_code=201,
    dependencies=[Depends(require_event_runner)],
)
def add_team(event_id: int, data: CupTeamAdd) -> EventEntrantPublic:
    """Enter a whole team by hand, every player confirmed."""
    return cup_teams.add_by_hand(event_id, data)


@router.post("/events/{event_id}/cup-teams/{team_id}/accept", status_code=204)
def accept_invite(event_id: int, team_id: int, claims: RequireLogin) -> None:
    """Join the team that invited the caller."""
    cup_teams.accept(event_id, team_id, claims)


@router.post("/events/{event_id}/cup-teams/{team_id}/decline", status_code=204)
def decline_invite(event_id: int, team_id: int, claims: RequireLogin) -> None:
    """Say no to the team that invited the caller."""
    cup_teams.decline(event_id, team_id, claims)


@router.post("/events/{event_id}/cup-teams/{team_id}/invites", status_code=204)
def invite_player(
    event_id: int, team_id: int, data: TeamInviteCreate, claims: RequireLogin
) -> None:
    """The captain invites one more player into a free place of the team."""
    cup_teams.invite(event_id, team_id, data.user_id, claims)


@router.delete(
    "/events/{event_id}/cup-teams/{team_id}/invites/{user_id}", status_code=204
)
def take_back_invite(
    event_id: int, team_id: int, user_id: int, claims: RequireLogin
) -> None:
    """The captain takes back an invite still unanswered."""
    cup_teams.take_back(event_id, team_id, user_id, claims)


@router.delete("/events/{event_id}/cup-teams/{team_id}/members/me", status_code=204)
def leave_team(event_id: int, team_id: int, claims: RequireLogin) -> None:
    """A player who is not the captain leaves the team before it plays."""
    cup_teams.leave(event_id, team_id, claims)


@router.delete("/events/{event_id}/cup-teams/{team_id}", status_code=204)
def withdraw_team(event_id: int, team_id: int, claims: RequireLogin) -> None:
    """The captain withdraws the team, and its open invites go with it."""
    cup_teams.withdraw(event_id, team_id, claims)


@router.post(
    "/events/{event_id}/cup-teams/{team_id}/members/{user_id}/replace",
    dependencies=[Depends(require_event_runner)],
)
def replace_team_member(
    event_id: int, team_id: int, user_id: int, data: MemberReplace
) -> EventEntrantPublic:
    """Put another player in a team's place of one who leaves it, before it plays."""
    return cup_teams.replace_member(event_id, team_id, user_id, data.user_id)


@router.get("/me/team-invites")
def get_my_team_invites(claims: RequireLogin) -> list[TeamInvitePublic]:
    """The team invitations the caller has not answered yet, newest first."""
    return cup_teams.invites_for(claims)


@router.delete("/events/{event_id}/entrants/me", status_code=204)
def withdraw(
    event_id: int,
    claims: RequireLogin,
    service: EventServiceDep,
    race: Race | None = None,
) -> None:
    """Withdraw the caller's own signup, or the one race named; the row stays."""
    service.withdraw(event_id, claims, race)


@router.post(
    "/events/{event_id}/entrants/{entrant_id}/admit",
    dependencies=[Depends(require_event_runner)],
)
def admit_entrant(
    event_id: int, entrant_id: int, service: EventServiceDep
) -> EventEntrantPublic:
    """A runner lets one entrant in off the waitlist before the draw, past the
    cap if need be; after the draw a waiting player takes a place by a swap."""
    return service.admit_entrant(event_id, entrant_id)


@router.post(
    "/events/{event_id}/entrants/{entrant_id}/withdraw",
    status_code=204,
    dependencies=[Depends(require_event_runner)],
)
def withdraw_entrant(event_id: int, entrant_id: int, service: EventServiceDep) -> None:
    """A runner withdraws one entrant: the row stays, and on a drawn cup the
    entrant forfeits every series it still owes."""
    service.withdraw_entrant(event_id, entrant_id)


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
    dependencies=[
        Depends(require_event_runner),
        Depends(night.removes_on_its_run_page),
    ],
)
def remove_entrant(event_id: int, entrant_id: int, service: EventServiceDep) -> None:
    """Remove one entrant row; a KOTH night removes its rows on its run page."""
    service.remove_entrant(event_id, entrant_id)


@router.put(
    "/events/{event_id}/entrants/{entrant_id}",
    dependencies=[Depends(require_event_runner), Depends(night.still_open)],
)
def place_entrant(
    event_id: int,
    entrant_id: int,
    data: EntrantPlacement,
    service: EventServiceDep,
) -> EventEntrantPublic:
    """Move one entrant into a division and mark it placed by hand."""
    return service.place_entrant(event_id, entrant_id, data)


@router.put(
    "/events/{event_id}/entrants/{entrant_id}/pins",
    dependencies=[Depends(require_event_runner)],
)
def pin_cup_entrant(
    event_id: int,
    entrant_id: int,
    data: CupPinWrite,
    service: EventServiceDep,
) -> EventEntrantPublic:
    """Pin a cup player to its division, or its seed, so a new cut or a
    reshuffle leaves it where it is."""
    return service.set_pins(event_id, entrant_id, data)


@router.post(
    "/events/{event_id}/legs",
    status_code=201,
    dependencies=[Depends(require_event_runner)],
)
def add_leg(event_id: int, data: CupLegWrite) -> list[CupLegPublic]:
    """Add a round after the last one of a cup over rounds, playing the same
    stages as the others."""
    return cup_rounds.add_leg(event_id, data)


@router.put(
    "/events/{event_id}/legs/{leg_id}",
    dependencies=[Depends(require_event_runner)],
)
def update_leg(event_id: int, leg_id: int, data: CupLegUpdate) -> list[CupLegPublic]:
    """Rename a round or move its start; the first round's start is the cup's."""
    return cup_rounds.update_leg(event_id, leg_id, data)


@router.delete(
    "/events/{event_id}/legs/{leg_id}",
    dependencies=[Depends(require_event_runner)],
)
def remove_leg(event_id: int, leg_id: int) -> list[CupLegPublic]:
    """Remove a round that is not drawn; a cup keeps two rounds or more."""
    return cup_rounds.remove_leg(event_id, leg_id)


@router.post("/events/{event_id}/legs/{leg_id}/checkins")
def check_in_for_leg(
    event_id: int, leg_id: int, data: CupLegCheckinWrite, claims: RequireLogin
) -> list[CupLegPublic]:
    """Check a player in for one round of a cup while the round is not drawn:
    the caller's own entry, or any entry the body names for a runner."""
    return cup_rounds.check_in(event_id, leg_id, data.entrant_id, claims, True)


@router.delete("/events/{event_id}/legs/{leg_id}/checkins")
def check_out_of_leg(
    event_id: int,
    leg_id: int,
    claims: RequireLogin,
    entrant_id: Annotated[int | None, Query()] = None,
) -> list[CupLegPublic]:
    """Take a round's check-in back while the round is not drawn."""
    return cup_rounds.check_in(event_id, leg_id, entrant_id, claims, False)


@router.post(
    "/events/{event_id}/legs/{leg_id}/checkins/everyone",
    dependencies=[Depends(require_event_runner)],
)
def check_everyone_in(event_id: int, leg_id: int) -> list[CupLegPublic]:
    """Check every playing entrant of the cup in for one round."""
    return cup_rounds.check_in_everyone(event_id, leg_id)


@router.post(
    "/events/{event_id}/legs/{leg_id}/finish",
    dependencies=[Depends(require_event_runner)],
)
def finish_leg(event_id: int, leg_id: int) -> list[CupLegPublic]:
    """Finish a played round: its places pay points into the overall table."""
    return cup_rounds.finish_leg(event_id, leg_id)


@router.delete(
    "/events/{event_id}/legs/{leg_id}/finish",
    dependencies=[Depends(require_event_runner)],
)
def reopen_leg(event_id: int, leg_id: int) -> list[CupLegPublic]:
    """Take a round's finish back while the cup is open."""
    return cup_rounds.reopen_leg(event_id, leg_id)


@router.get("/events/{event_id}/overall")
def get_overall(event_id: int, response: Response) -> CupOverallPublic:
    """A cup's overall table: the points each finished round paid, added up."""
    event_edge_cache(response, event_id)
    return cup_rounds.overall(event_id)


@router.post("/events/{event_id}/recurrence", status_code=201)
def repeat_cup(
    event_id: int, data: CupRecurrenceWrite, claims: RequireEventRunner
) -> CupRecurrencePublic:
    """Set up a rule that repeats the cup; the cup becomes its first occurrence."""
    return cup_recurrence.create(event_id, data, claims)


@router.get("/cup-recurrences")
def list_cup_recurrences(response: Response) -> list[CupRecurrenceRow]:
    """Every recurring cup, newest first, with its next day and its latest cup."""
    edge_cache(response, "running")
    return cup_recurrence.listing()


@router.get("/cup-recurrences/{recurrence_id}")
def get_cup_recurrence(
    recurrence_id: int, claims: OptionalLogin, response: Response
) -> CupRecurrencePublic:
    """A recurring cup: its rule, the cups made from it and its next eight days."""
    if claims is None:
        # a runner creates from this page, so only the anonymous answer is shared
        edge_cache(response, "running")
    return cup_recurrence.get(recurrence_id)


@router.put("/cup-recurrences/{recurrence_id}")
def update_cup_recurrence(
    recurrence_id: int, data: CupRecurrenceUpdate, claims: RequireLogin
) -> CupRecurrencePublic:
    """Rename the rule, move its start time or set its last day; a runner of
    its latest cup alone."""
    return cup_recurrence.update(recurrence_id, data, claims)


@router.delete("/cup-recurrences/{recurrence_id}", status_code=204)
def delete_cup_recurrence(recurrence_id: int, claims: RequireLogin) -> None:
    """Stop repeating; every cup made from the rule stays."""
    cup_recurrence.delete(recurrence_id, claims)


@router.post("/cup-recurrences/{recurrence_id}/occurrences", status_code=201)
def create_cup_occurrence(
    recurrence_id: int, data: CupOccurrenceCreate, claims: RequireLogin
) -> EventPublic:
    """Make the rule's cup on one of its coming days, a copy of the latest cup
    with its organizers; a runner of that cup alone."""
    return cup_recurrence.create_occurrence(recurrence_id, data.on, claims)


@router.put(
    "/events/{event_id}/divisions",
    dependencies=[Depends(require_event_runner), Depends(night.keeps_its_brackets)],
)
def set_divisions(
    event_id: int, divisions: list[EventDivisionWrite], service: EventServiceDep
) -> EventPublic:
    """Replace the division list; the order of the body is their position."""
    return service.set_divisions(event_id, divisions)


@router.post(
    "/events/{event_id}/divisions/assign",
    dependencies=[Depends(require_event_runner), Depends(night.cuts_itself)],
)
def assign_divisions(event_id: int, service: EventServiceDep) -> EventPublic:
    """Cut the entrants into divisions and answer the count each one holds."""
    return service.assign_divisions(event_id)


@router.put(
    "/events/{event_id}/stages/{stage_id}/seeds",
    dependencies=[Depends(require_event_runner), Depends(night.keeps_its_line)],
)
def set_seeds(
    event_id: int, stage_id: int, data: SeedWrite, service: EventServiceDep
) -> list[EventEntrantPublic]:
    """Seed the entrants 1..n inside each division, in seed order.

    The sources that seed are mmr, random, manual, invitation and
    previous_stage, which takes the standings of the stage before and
    generates nothing. A qualifier answers not_built.
    """
    return service.set_seeds(event_id, stage_id, data)


@router.put(
    "/events/{event_id}/stages/{stage_id}/seeds/redraw",
    dependencies=[Depends(require_event_runner)],
)
def redraw_seeds(
    event_id: int,
    stage_id: int,
    data: SeedWrite,
    service: EventServiceDep,
    confirm: bool = False,
) -> list[EventEntrantPublic]:
    """Change the seeds of a cup's first stage after its draw and draw it again
    from them, in one write. A stage whose series hold results answers 409
    until the call sends `confirm=true`, which deletes those results."""
    return service.redraw_seeds(event_id, stage_id, data, confirm)


@router.post(
    "/events/{event_id}/stages/{stage_id}/seeds/lock",
    dependencies=[Depends(require_event_runner)],
)
def lock_seeds(
    event_id: int, stage_id: int, service: EventServiceDep
) -> EventStagePublic:
    """Lock the seeds of the stage; a later seed write is refused."""
    return service.lock_seeds(event_id, stage_id)


@router.delete(
    "/events/{event_id}/stages/{stage_id}/seeds/lock",
    dependencies=[Depends(require_event_runner)],
)
def unlock_seeds(
    event_id: int, stage_id: int, service: EventServiceDep
) -> EventStagePublic:
    """Unlock the seeds of the stage; a stage that holds series answers 409."""
    return service.unlock_seeds(event_id, stage_id)


@router.post(
    "/events/{event_id}/stages/{stage_id}/generate",
    dependencies=[Depends(require_event_runner)],
)
def generate_stage(
    event_id: int, stage_id: int, service: EventServiceDep
) -> dict[str, int]:
    """Seed the unseeded entrants, then create every series of the stage from
    the seeds, one bracket per division, and lock the seeds. A refused draw
    writes no seed. Only a cup's stages are drawn."""
    return cup_engine.generate(event_id, stage_id, fill=service.seed_for_draw)


@router.post(
    "/events/{event_id}/stages/{stage_id}/rounds",
    dependencies=[Depends(require_event_runner)],
)
def draw_next_round(
    event_id: int, stage_id: int, service: EventServiceDep
) -> CupStagePublic:
    """Draw one more round of a stage that pairs a round at a time.

    It answers the round it drew and the series in it. The stage refuses while
    a series already drawn carries no result, and once it has drawn every
    round it plays. The first round seeds the unseeded entrants first, and a
    refused round writes no seed.
    """
    return cup_engine.generate_next_round(
        event_id, stage_id, fill=service.seed_for_draw
    )


@router.delete(
    "/events/{event_id}/stages/{stage_id}/series",
    dependencies=[Depends(require_event_runner)],
)
def undraw_stage(event_id: int, stage_id: int, confirm: bool = False) -> dict[str, int]:
    """Take the stage's draw back: every round and series of it goes, and the
    seeds open again, so the field may change and be drawn anew. A stage whose
    series hold results answers 409 until the call sends `confirm=true`."""
    return cup_engine.undraw(event_id, stage_id, confirm)


@router.get("/events/{event_id}/stages/{stage_id}/series")
def get_stage_series(
    event_id: int, stage_id: int, claims: OptionalLogin, response: Response
) -> CupStagePublic | StageSeriesPublic:
    """The rounds of the stage and every series it holds, for the run page: a
    cup's from its own tables, a KOTH night's from the series it plays."""
    if claims is None:
        # A runner reads seeds an event may hide, so only the anonymous answer is shared.
        event_edge_cache(response, event_id)
    if cup_engine.is_cup(event_id):
        return cup_engine.series_of(event_id, stage_id, claims)
    return stage_engine.series_of(event_id, stage_id, claims)


@router.post(
    "/events/{event_id}/stages/{stage_id}/series",
    dependencies=[Depends(require_event_runner)],
)
def add_stage_series(
    event_id: int, stage_id: int, data: ChallengerAdd
) -> StageSeriesRow:
    """Append one challenger to the end of the chain his division plays."""
    return stage_engine.add_challenger(event_id, stage_id, data.entrant_id)


@router.get("/events/{event_id}/stages/{stage_id}/standings")
def get_standings(
    event_id: int, stage_id: int, response: Response
) -> list[DivisionStandings]:
    """The table of every division of the stage, computed on the read."""
    event_edge_cache(response, event_id)
    if cup_engine.is_cup(event_id):
        return cup_engine.standings_of(event_id, stage_id)
    return stage_engine.standings_of(event_id, stage_id)


@router.post(
    "/events/{event_id}/stages/{stage_id}/advance",
    dependencies=[Depends(require_event_runner)],
)
def advance_stage(event_id: int, stage_id: int) -> dict[str, int]:
    """Seed the next stage from the top places of every division's table."""
    return cup_engine.advance(event_id, stage_id)
