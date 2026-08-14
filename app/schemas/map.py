from typing import Annotated

from app.schemas.base import APISchema, NumToStr


class Map(APISchema):
    id: int | None = None
    # The xlsx import passes these cells straight through, so a numeric
    # map name or shortname arrives as a number.
    name: Annotated[str | None, NumToStr] = None
    shortname: Annotated[str | None, NumToStr] = None
    image: Annotated[str | None, NumToStr] = None

    @classmethod
    def from_dbmap(cls, map):
        return cls(
            id=map.id,
            name=map.name,
            shortname=map.shortname,
            image=map.image,
        )

    @staticmethod
    def schema():
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "shortname": {"type": "string"},
                "image": {"type": "string"},
            },
            "required": ["name", "shortname"],
        }
