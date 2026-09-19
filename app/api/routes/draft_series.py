import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import (
    DraftSeriesServiceDep,
    MatchServiceDep,
    UserServiceDep,
    claim_seats,
    require_admin,
    require_captain,
)
from app.core.db import Session
from app.core.exceptions import ApiError
from app.models.draft_board import DraftBoard
from app.models.draft_series import (
    DraftSeriesCreate,
    DraftSeriesPublic,
    DraftSeriesUpdate,
)
from app.models.match import MatchPublic
from app.models.match_draft import (
    MatchDraftStatePublic,
    MaxMmrDifferenceWrite,
    ReadyWrite,
    ReplacePreviewPublic,
)
from app.models.series import SeriesPublic
from app.services import draft_board, draft_series
from app.services.matches import MatchService
from app.services.users import UserService

# The board answers one caller's match, so no shared cache may hold it
PRIVATE_CACHE = "private, max-age=30"

logger = logging.getLogger(__name__)

router = APIRouter(tags=["draft-series"])

RequireCaptain = Annotated[dict[str, Any], Depends(require_captain)]


def _is_admin(claims: dict[str, Any]) -> bool:
    return claims.get("role") == "admin" or claims["sub"] == "admin"


def _own_match(
    claims: dict[str, Any], match_id: int | None, matches: MatchService
) -> None:
    """A captain drafts the matches their team plays; an admin drafts any."""
    if _is_admin(claims):
        return
    match = matches.get(match_id) if match_id is not None else None
    seats = claim_seats(claims)
    if match is None or not seats & {
        (match.team1_id, match.season_id),
        (match.team2_id, match.season_id),
    }:
        raise ApiError(403, {"error": "Your team does not play this match"})


def _own_side(claims: dict[str, Any], match: MatchPublic, team_id: int) -> None:
    """A captain marks his own team's side of the fixture; an admin marks either."""
    if team_id not in (match.team1_id, match.team2_id):
        raise ApiError(400, {"error": "That team does not play this match"})
    if _is_admin(claims):
        return
    if (team_id, match.season_id) not in claim_seats(claims):
        raise ApiError(403, {"error": "Your team does not play this match"})


def _seated_team(claims: dict[str, Any], match: MatchPublic) -> int | None:
    """The team the caller captains in this fixture; nothing for an admin."""
    seats = claim_seats(claims)
    for team_id in (match.team1_id, match.team2_id):
        if team_id is not None and (team_id, match.season_id) in seats:
            return team_id
    return None


def _caller_id(claims: dict[str, Any], users: UserService) -> int | None:
    """The player row behind the session; null for the admin token login."""
    return users.id_by_discord_id(str(claims["sub"]))


def _rules(
    match_id: int | None,
    players: tuple[int | None, ...],
    pairing: tuple[int | None, ...],
    *,
    draft_series_id: int | None = None,
    replaces_series_id: int | None = None,
    creating: bool = False,
) -> None:
    """The rules of one drafted pairing, in one transaction.

    A drafted series of a fixture names a player its siblings do not: a mixed
    fixture, the Altar of Champions Clan War, plays several drafted series, and
    a player plays one of them. An edit skips its own row. A new pairing also
    counts against the round, and a replacement names an open series of the
    same fixture. `players` is what the write names, `pairing` the pair it ends
    up with.
    """
    with Session.begin() as session:
        draft_series.refuse_repeat(
            session, match_id, players, skip_draft_id=draft_series_id
        )
        draft_series.refuse_bad_replacement(
            session,
            match_id,
            replaces_series_id,
            pairing,
            skip_draft_id=draft_series_id,
        )
        if creating:
            draft_series.refuse_full(session, match_id, replaces_series_id)


@router.post(
    "/draft-series",
    status_code=201,
    response_model=DraftSeriesPublic,
)
def add_draft_series(
    data: DraftSeriesCreate,
    service: DraftSeriesServiceDep,
    matches: MatchServiceDep,
    users: UserServiceDep,
    claims: RequireCaptain,
) -> DraftSeriesPublic:
    """Create a new draft series for a match the caller's team plays."""
    _own_match(claims, data.match_id, matches)
    pairing = (data.player1_id, data.player2_id)
    _rules(
        data.match_id,
        pairing,
        pairing,
        replaces_series_id=data.replaces_series_id,
        creating=True,
    )
    return service.add(data, _caller_id(claims, users))


@router.put(
    "/draft-series/{draft_series_id}",
    response_model=DraftSeriesPublic,
)
def update_draft_series(
    draft_series_id: int,
    data: DraftSeriesUpdate,
    service: DraftSeriesServiceDep,
    matches: MatchServiceDep,
    users: UserServiceDep,
    claims: RequireCaptain,
) -> DraftSeriesPublic:
    """Update a draft series of a match the caller's team plays."""
    existing = service.get(draft_series_id)
    _own_match(claims, existing.match_id, matches)
    if data.match_id is not None and data.match_id != existing.match_id:
        _own_match(claims, data.match_id, matches)
    _rules(
        data.match_id or existing.match_id,
        (data.player1_id, data.player2_id),
        (
            data.player1_id or existing.player1_id,
            data.player2_id or existing.player2_id,
        ),
        draft_series_id=draft_series_id,
        replaces_series_id=existing.replaces_series_id,
        # A pairing moved to another fixture counts against that fixture's round
        creating=data.match_id is not None and data.match_id != existing.match_id,
    )
    return service.update(draft_series_id, data, _caller_id(claims, users))


@router.delete(
    "/draft-series/{draft_series_id}",
    status_code=204,
)
def delete_draft_series(
    draft_series_id: int,
    service: DraftSeriesServiceDep,
    matches: MatchServiceDep,
    claims: RequireCaptain,
) -> None:
    """Delete a draft series of a match the caller's team plays."""
    _own_match(claims, service.get(draft_series_id).match_id, matches)
    service.delete(draft_series_id)


@router.get("/draft-series/{draft_series_id}", dependencies=[Depends(require_captain)])
def get_draft_series(
    draft_series_id: int, service: DraftSeriesServiceDep
) -> DraftSeriesPublic:
    """Retrieve a draft series by its ID."""
    return service.get(draft_series_id)


@router.get("/draft-series/match/{match_id}", dependencies=[Depends(require_captain)])
def get_draft_series_by_match(
    match_id: int,
    service: DraftSeriesServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DraftSeriesPublic]:
    """Return one page of the draft series of a match, at most 500."""
    return service.get_by_match_id(match_id, limit=limit, offset=offset)


@router.get("/matches/{match_id}/draft-board")
def get_draft_board(
    match_id: int,
    matches: MatchServiceDep,
    claims: RequireCaptain,
    response: Response,
) -> DraftBoard:
    """Every figure the draft board of one match draws, in one read.

    A captain of either team of the match reads it, and an admin reads any.
    It answers figures, never rows: per player the signup race, the rating on
    it, the games rule, the record against each race and the recent form; per
    pairing the shared hours of the round and the head-to-head score of the
    two. The MMR difference is not sent; the browser subtracts.
    """
    _own_match(claims, match_id, matches)
    # the answer is this caller's, so no shared cache may store a copy, and the
    # browser's own copy is keyed on the bearer that names the caller
    response.headers["Cache-Control"] = PRIVATE_CACHE
    response.headers["Vary"] = "Authorization"
    return draft_board.board(match_id)


@router.delete(
    "/draft-series/match/{match_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def delete_all_draft_series_for_match(
    match_id: int, service: DraftSeriesServiceDep
) -> None:
    """Delete all draft series for a specific match"""
    service.delete_by_match_id(match_id)


@router.post(
    "/draft-series/{draft_series_id}/promote",
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def promote_draft_series(
    draft_series_id: int, service: DraftSeriesServiceDep
) -> SeriesPublic:
    """Publish a draft series and delete the draft, in one transaction.

    A draft that names a series it replaces removes that series too; a series
    that holds a result or a replay answers 409 and nothing changes.
    """
    return service.promote(draft_series_id)


@router.get(
    "/draft-series/{draft_series_id}/replaces",
    dependencies=[Depends(require_captain)],
)
def get_replace_preview(
    draft_series_id: int, service: DraftSeriesServiceDep
) -> ReplacePreviewPublic:
    """What promoting this draft takes away: the booked time and the veto."""
    return service.replace_preview(draft_series_id)


@router.get("/draft-series/match/{match_id}/state")
def get_match_draft_state(
    match_id: int,
    service: DraftSeriesServiceDep,
    matches: MatchServiceDep,
    claims: RequireCaptain,
) -> MatchDraftStatePublic:
    """The Ready marks of both teams, the caller's seen stamp and the MMR values."""
    return service.state(match_id, _seated_team(claims, matches.get(match_id)))


@router.put("/draft-series/match/{match_id}/teams/{team_id}/ready")
def set_match_draft_ready(
    match_id: int,
    team_id: int,
    data: ReadyWrite,
    service: DraftSeriesServiceDep,
    matches: MatchServiceDep,
    users: UserServiceDep,
    claims: RequireCaptain,
) -> MatchDraftStatePublic:
    """Mark the team ready, or take the mark back. It blocks no promote."""
    match = matches.get(match_id)
    _own_side(claims, match, team_id)
    return service.set_ready(match_id, team_id, data.ready, _caller_id(claims, users))


@router.put("/draft-series/match/{match_id}/teams/{team_id}/seen", status_code=204)
def set_match_draft_seen(
    match_id: int,
    team_id: int,
    service: DraftSeriesServiceDep,
    matches: MatchServiceDep,
    claims: RequireCaptain,
) -> None:
    """Record that the team read the pairings; a captain of that team writes it."""
    match = matches.get(match_id)
    _own_side(claims, match, team_id)
    if (team_id, match.season_id) not in claim_seats(claims):
        raise ApiError(403, {"error": "Your team does not play this match"})
    service.set_seen(match_id, team_id)


@router.put("/draft-series/match/{match_id}/max-mmr-difference")
def set_match_draft_max_mmr_difference(
    match_id: int,
    data: MaxMmrDifferenceWrite,
    service: DraftSeriesServiceDep,
    matches: MatchServiceDep,
    claims: RequireCaptain,
) -> MatchDraftStatePublic:
    """The working largest MMR difference of the fixture; null reads the stage."""
    match = matches.get(match_id)
    _own_match(claims, match_id, matches)
    return service.set_max_mmr_difference(
        match_id, data.max_mmr_difference, _seated_team(claims, match)
    )
