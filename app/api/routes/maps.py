import hashlib
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile

from app.api.deps import MapServiceDep, require_admin
from app.api.search import SearchQuery
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.map import MapCreate, MapPublic, MapUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["maps"])


def _media_type(image: bytes) -> str:
    """What the first bytes of the upload say the picture is."""
    if image.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if image.startswith(b"\x89PN"):
        return "image/png"
    return "application/octet-stream"


@router.post(
    "/maps",
    status_code=201,
    response_model=MapPublic,
    dependencies=[Depends(require_admin)],
)
def add_map(data: MapCreate, service: MapServiceDep) -> MapPublic:
    """Create a new map with the provided details."""
    return service.add(data)


@router.put(
    "/maps/{map_id}", response_model=MapPublic, dependencies=[Depends(require_admin)]
)
def update_map(map_id: int, data: MapUpdate, service: MapServiceDep) -> MapPublic:
    """Update the details of an existing map."""
    return service.update(map_id, data)


@router.delete("/maps/{map_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_map(map_id: int, service: MapServiceDep) -> None:
    """Delete a map by their ID."""
    service.delete(map_id)


@router.get("/maps/{map_id}", response_model=MapPublic)
def get_map(map_id: int, service: MapServiceDep) -> MapPublic:
    """Retrieve a map by their ID."""
    return service.get(map_id)


@router.get("/maps", response_model=list[MapPublic])
def get_all_maps(
    service: MapServiceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MapPublic]:
    """Retrieve one page of maps, at most 500."""
    return service.get_all(limit=limit, offset=offset)


@router.post("/maps/search", response_model=list[MapPublic])
def search_maps(
    service: MapServiceDep,
    query: SearchQuery,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MapPublic]:
    """Search maps by criteria using a custom query format."""
    return service.search(query, limit=limit, offset=offset)


@router.post("/maps/{map_id}/image", dependencies=[Depends(require_admin)])
def upload_map_image(
    map_id: int,
    service: MapServiceDep,
    image: Annotated[UploadFile | None, File()] = None,
) -> dict[str, str]:
    """Upload or replace the picture of a map, stored in binary format."""
    if image is None:
        raise BadRequestError("No image provided")

    service.update_icon(map_id, image.file.read())

    return {"message": "Image uploaded successfully"}


@router.get("/maps/{map_id}/image")
def get_map_image(map_id: int, request: Request, service: MapServiceDep) -> Response:
    """Fetch the stored picture of a map."""
    icon = service.get_icon(map_id)
    if not icon:
        raise NotFoundError("Image not found")

    # The tag is the content, so a replaced picture answers a new one.
    etag = f'"{hashlib.sha256(icon).hexdigest()}"'
    headers = {"Cache-Control": "public, max-age=86400", "ETag": etag}
    if etag in [
        tag.strip() for tag in request.headers.get("if-none-match", "").split(",")
    ]:
        return Response(status_code=304, headers=headers)

    return Response(content=icon, media_type=_media_type(icon), headers=headers)
