import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import UserServiceDep, require_admin
from app.models.user import UserCreate, UserPublic, UserUpdate
from app.utils.query_util import QueryUtil

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
    return service.create_user(data)


@router.put(
    "/users/{user_id}",
    response_model=UserPublic,
    dependencies=[Depends(require_admin)],
)
def update_user(user_id: int, data: UserUpdate, service: UserServiceDep) -> UserPublic:
    """Update the details of an existing user."""
    return service.update_user(user_id, data)


@router.delete(
    "/users/{user_id}", status_code=204, dependencies=[Depends(require_admin)]
)
def delete_user(user_id: int, service: UserServiceDep) -> None:
    """Delete a user by their ID."""
    service.delete_user(user_id)


@router.get("/users/{user_id}")
def get_user(user_id: int, service: UserServiceDep) -> dict[str, Any] | None:
    """Retrieve a user by their ID."""
    user = service.get_user(user_id)
    return user.to_dict() if user else None


@router.get("/users")
def get_all_users(service: UserServiceDep) -> list[dict[str, Any]]:
    """Retrieve all users."""
    return [user.to_dict() for user in service.getAll() or []]


@router.post("/users/search")
def search_users(service: UserServiceDep, query: str = "") -> list[dict[str, Any]]:
    """Search users by criteria using a custom query format."""
    parsed_query = QueryUtil.parseQuery(query)
    if not parsed_query or not parsed_query.elementA:
        raise Exception(f"No valid query found: {query}")
    return [user.to_dict() for user in service.search(parsed_query) or []]


@router.post("/users/w3c_sync/{user_id}", dependencies=[Depends(require_admin)])
def sync_w3c_user(user_id: int, service: UserServiceDep) -> dict[str, Any] | None:
    """Sync w3c information for a user_id"""
    user = service.updateW3CStats_ById(user_id)
    return user.to_dict() if user else None
