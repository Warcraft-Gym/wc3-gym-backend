import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import UserServiceDep, require_admin
from app.core.exceptions import BadRequestError
from app.core.query import QueryUtil
from app.models.user import UserCreate, UserListPublic, UserPublic, UserUpdate

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


@router.get("/users/{user_id}")
def get_user(user_id: int, service: UserServiceDep) -> UserPublic:
    """Retrieve a user by their ID."""
    return service.get(user_id)


@router.get("/users")
def get_all_users(
    service: UserServiceDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserListPublic]:
    """Retrieve one page of users, at most 500, ordered by id."""
    users, total = service.getAll(limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return users or []


@router.post("/users/search")
def search_users(
    service: UserServiceDep,
    query: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserListPublic]:
    """Search users by criteria using a custom query format."""
    parsed_query = QueryUtil.parseQuery(query)
    if not parsed_query or not parsed_query.elementA:
        raise BadRequestError(f"No valid query found: {query}")
    return service.search(parsed_query, limit=limit, offset=offset) or []


@router.post("/users/w3c_sync/{user_id}", dependencies=[Depends(require_admin)])
def sync_w3c_user(user_id: int, service: UserServiceDep) -> UserPublic:
    """Sync w3c information for a user_id"""
    return service.updateW3CStats_ById(user_id)
