import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import (
    LadderServiceDep,
    OptionalLogin,
    RequireMember,
    SoftBlockServiceDep,
    UserServiceDep,
    edge_cache,
    require_admin,
)
from app.api.search import SearchQuery
from app.core.exceptions import ApiError
from app.core.security import is_admin
from app.models.draft_board import PairMeeting
from app.models.link_prompt import LinkPromptPublic, PromptAnswer
from app.models.player_history import PlayerHistory
from app.models.user import (
    UserCreate,
    UserListPublic,
    UserMemberListPublic,
    UserMemberPublic,
    UserPublic,
    UserUpdate,
)
from app.models.user_battle_tag import MergePlan, MergeWrite, TagMoveWrite, TagWrite
from app.models.user_block import SoftBlocksPublic
from app.models.w3c_ladder_match import LadderPlayer
from app.services import draft_board, player_history

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])


@router.post(
    "/users",
    status_code=201,
    response_model=UserPublic,
    dependencies=[Depends(require_admin)],
)
def add_user(data: UserCreate, service: UserServiceDep) -> UserPublic:
    """Create a new user with the provided details."""
    return service.add(data)


def _discord_id(claims: dict[str, Any]) -> str:
    """The Discord id of a member session; the admin token names no person."""
    if claims["sub"] == "admin":
        raise ApiError(401, {"error": "not_a_discord_member"})
    return str(claims["sub"])


@router.post("/users/me/tags")
def add_my_tag(
    data: TagWrite, claims: RequireMember, service: UserServiceDep
) -> UserPublic:
    """Add a tag I also played as. W3Champions must know it; a tag a person
    with no login holds moves to me, one another login holds answers 409."""
    return service.add_own_tag(_discord_id(claims), data.tag)


@router.get("/users/me/prompts")
def my_prompts(
    claims: RequireMember, service: UserServiceDep
) -> list[LinkPromptPublic]:
    """My open suggestions of an earlier player, and notices of a tag another
    login verified. Only my own answer closes one."""
    return service.own_prompts(_discord_id(claims))


@router.post("/users/me/prompts/{prompt_id}")
def answer_my_prompt(
    prompt_id: int, data: PromptAnswer, claims: RequireMember, service: UserServiceDep
) -> UserPublic:
    """Accept a suggestion to join the player, unverified, or close a prompt."""
    return service.answer_own_prompt(_discord_id(claims), prompt_id, data.accept)


@router.put("/users/me/tags/{tag_id}/active")
def activate_my_tag(
    tag_id: int, claims: RequireMember, service: UserServiceDep
) -> UserPublic:
    """Make one of my tags the active one; battleTag follows."""
    return service.activate_own_tag(_discord_id(claims), tag_id)


@router.delete("/users/me/tags/{tag_id}")
def remove_my_tag(
    tag_id: int, claims: RequireMember, service: UserServiceDep
) -> UserPublic:
    """Remove an unverified, inactive tag of mine and the games fetched under it."""
    return service.remove_own_tag(_discord_id(claims), tag_id)


@router.post(
    "/users/{user_id}/tags/{tag_id}/move", dependencies=[Depends(require_admin)]
)
def move_tag(
    user_id: int, tag_id: int, data: TagMoveWrite, service: UserServiceDep
) -> UserPublic:
    """Move one tag row to another person; answers that person."""
    return service.give_tag(user_id, tag_id, data.to_user_id)


@router.post("/users/{user_id}/merge", dependencies=[Depends(require_admin)])
def merge_user(
    user_id: int, data: MergeWrite, service: UserServiceDep
) -> MergePlan | UserPublic:
    """Merge a person into another. A dry run answers the plan; a real run
    with a stop answers 409 with the plan and an error."""
    return service.merge_into(user_id, data.into_user_id, data.dry_run)


@router.put(
    "/users/{user_id}",
    response_model=UserPublic,
    dependencies=[Depends(require_admin)],
)
def update_user(user_id: int, data: UserUpdate, service: UserServiceDep) -> UserPublic:
    """Update the details of an existing user."""
    return service.update(user_id, data)


@router.delete(
    "/users/{user_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_user(user_id: int, service: UserServiceDep) -> None:
    """Delete a user by their ID."""
    service.delete(user_id)


@router.put(
    "/users/{user_id}/ban", status_code=204, dependencies=[Depends(require_admin)]
)
def ban_user(user_id: int, service: UserServiceDep) -> None:
    """Ban a player. The entrant rows of every event warn; none of them refuse."""
    service.set_banned(user_id, True)


@router.delete(
    "/users/{user_id}/ban", status_code=204, dependencies=[Depends(require_admin)]
)
def unban_user(user_id: int, service: UserServiceDep) -> None:
    """Lift the ban."""
    service.set_banned(user_id, False)


@router.get("/users/{user_id}/blocks", dependencies=[Depends(require_admin)])
def get_user_blocks(user_id: int, service: SoftBlockServiceDep) -> SoftBlocksPublic:
    """One player's repeating blocks and busy days, for an admin."""
    return service.for_user(user_id)


@router.get("/users/{key}")
def get_user(
    key: str, service: UserServiceDep, response: Response, login: OptionalLogin
) -> UserPublic | UserMemberPublic:
    """Retrieve a user by id, or by battle tag: `/users/thanks%2311187`.
    A logged-in caller also gets the Discord account."""
    user = service.get(key)
    if login is not None:
        return UserMemberPublic.model_validate(dict(user))
    edge_cache(response, "running")
    return user


def for_caller(
    users: list[UserListPublic], login: dict[str, Any] | None
) -> list[UserListPublic] | list[UserMemberListPublic]:
    """The rows as sent: an admin also gets the Discord account."""
    if not is_admin(login):
        return users
    return [UserMemberListPublic.model_validate(dict(user)) for user in users]


@router.get("/users")
def get_all_users(
    service: UserServiceDep,
    response: Response,
    login: OptionalLogin,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    no_discord: bool = False,
    tag_source: str | None = None,
) -> list[UserListPublic] | list[UserMemberListPublic]:
    """Retrieve one page of users, at most 500, ordered by id.

    no_discord keeps the people with no login; tag_source keeps the people
    holding a tag of that source, such as `claim`.
    """
    users, total = service.get_all(
        limit=limit, offset=offset, no_discord=no_discord, tag_source=tag_source
    )
    response.headers["X-Total-Count"] = str(total)
    return for_caller(users, login)


@router.post("/users/search")
def search_users(
    service: UserServiceDep,
    query: SearchQuery,
    login: OptionalLogin,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserListPublic] | list[UserMemberListPublic]:
    """Search users by criteria using a custom query format, 100 a page."""
    return for_caller(service.search(query, limit=limit, offset=offset), login)


@router.post("/users/{user_id}/w3c-sync", dependencies=[Depends(require_admin)])
def sync_w3c_user(
    user_id: int, service: UserServiceDep, ladder: LadderServiceDep
) -> UserPublic:
    """Sync this player's stats, and his matches of the season running today."""
    ladder.sync_user(user_id)
    return service.get(user_id)


@router.get("/users/{user_id}/ladder")
def get_user_ladder(
    user_id: int,
    service: LadderServiceDep,
    response: Response,
    season_id: int | None = None,
) -> LadderPlayer:
    """One player's ladder record, on the race the league scores him on.

    Without a season the answer covers every match the player has. The
    matches themselves stay on w3champions, which the client links to.
    """
    edge_cache(response, "running")
    return service.user_ladder(user_id, season_id)


@router.get("/users/{user_id}/history")
def get_user_history(user_id: int, response: Response) -> PlayerHistory:
    """Every GNL season this player took part in, and every opponent they met."""
    edge_cache(response, "running")
    return player_history.history(user_id)


@router.get("/users/{user_a}/meetings/{user_b}")
def get_pair_meetings(
    user_a: int,
    user_b: int,
    response: Response,
    claims: RequireMember,
) -> list[PairMeeting]:
    """Every finished series the two players played, newest first, at most 20.

    Each meeting carries its date, its event, the score in the order of the
    path, the race each side played and the MMR each held going into it.
    """
    # the answer is one member's detail read, so no shared cache may store it,
    # and the browser's own copy is keyed on the bearer that names the member
    response.headers["Cache-Control"] = "private, max-age=30"
    response.headers["Vary"] = "Authorization"
    return draft_board.meetings(user_a, user_b)
