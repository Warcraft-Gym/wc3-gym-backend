from collections.abc import Callable, Sequence

from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.base import ident
from app.models.map import LadderMapRow, Map, MapCreate, MapPublic, MapUpdate
from app.services import blob, ladder_maps


def _known(maps: Sequence[Map]) -> Callable[[str], int | None]:
    """The map behind a ladder name: exact, else its one lineage twin."""
    by_name = {map.name.lower(): ident(map) for map in maps if map.name}
    by_base: dict[str, list[int]] = {}
    for map in maps:
        if map.name:
            by_base.setdefault(ladder_maps.folded_base(map.name), []).append(ident(map))

    def known(name: str) -> int | None:
        exact = by_name.get(name.lower())
        if exact is not None:
            return exact
        lineage = by_base.get(ladder_maps.folded_base(name), [])
        return lineage[0] if len(lineage) == 1 else None

    return known


class MapService:
    def add(self, map: MapCreate) -> MapPublic:
        with Session.begin() as session:
            new_map = Map.add(session, map.model_dump())
            return MapPublic.model_validate(new_map)

    def update(self, map_id: int, map: MapUpdate) -> MapPublic:
        with Session.begin() as session:
            updated = Map.update(session, map_id, **map.model_dump(exclude_unset=True))
            if not updated:
                raise NotFoundError("Map not found")
            return MapPublic.model_validate(updated)

    def delete(self, map_id: int) -> None:
        with Session.begin() as session:
            Map.delete(session, map_id)

    def get(self, map_id: int) -> MapPublic:
        with Session.begin() as session:
            map = Map.get_by_id(session, map_id)
            if not map:
                raise NotFoundError(f"Map not found by Id: {map_id}")
            return MapPublic.model_validate(map)

    def search(
        self, query: QueryElement | None, limit: int | None = None, offset: int = 0
    ) -> list[MapPublic]:
        with Session.begin() as session:
            maps = Map.search(
                session,
                QueryUtil.convert_query_to_db_filter(Map, query),
                limit=limit,
                offset=offset,
            )
            return [MapPublic.model_validate(map) for map in maps]

    def update_icon(self, map_id: int, file: bytes) -> None:
        """Put the picture in the store, then point the row at it, the way a team logo is stored."""
        # at the boundary the bytes arrive at, so it holds whatever the store is or is stubbed to be
        blob.icon_type(file)
        # the store is not part of the transaction, so the put happens first: a put that is never
        # committed leaves an unreferenced blob, which is cheap, while a committed row pointing at
        # a blob that was never written is a broken image
        url = blob.put_icon(f"maps/{map_id}", file)
        with Session.begin() as session:
            # locked: two uploads for one map would otherwise read the same previous URL, and the
            # loser's blob would be left behind with nothing pointing at it
            map = session.get(Map, map_id, with_for_update=True)
            if not map:
                raise NotFoundError(f"Map not found by Id: {map_id}")
            previous = map.image
            map.image = url
        if previous and blob.ours(previous):
            blob.delete_blob(previous)

    def get_image_url(self, map_id: int) -> str | None:
        """Where the picture is published, or None for a map without one."""
        with Session.begin() as session:
            return session.scalar(select(col(Map.image)).where(col(Map.id) == map_id))

    def get_all(self, limit: int | None = None, offset: int = 0) -> list[MapPublic]:
        with Session.begin() as session:
            maps = Map.get_all(session, limit=limit, offset=offset)
            return [MapPublic.model_validate(map) for map in maps]

    def ladder_import_preview(self) -> list[LadderMapRow]:
        """Every 1v1 ladder map, and whether the app already holds it, then
        every map the app holds off the ladder whose picture warcraft3.info has."""
        with Session.begin() as session:
            maps = Map.get_all(session)
            known = _known(maps)
            shortnames = {ident(map): map.shortname for map in maps}
            taken = {map.shortname.lower() for map in maps if map.shortname}
            unpictured = [
                (ident(map), map.name, map.shortname)
                for map in maps
                if map.name and not map.image
            ]
        by_base = ladder_maps.map_index()
        rows = ladder_maps.ladder_rows(by_base)
        on_ladder = set()
        for row in rows:
            map_id = known(row.w3c_name)
            if map_id is not None:
                # the short name shown is the one the map will have: a known map keeps its own
                row.status = "known"
                row.shortname = shortnames[map_id]
                on_ladder.add(map_id)
            elif map_id is None:
                row.shortname = ladder_maps.free_shortname(
                    row.shortname, row.w3c_name, taken
                )
                taken.add(row.shortname.lower())
        for map_id, name, shortname in unpictured:
            if map_id in on_ladder:
                continue
            found = ladder_maps.lookup(name, by_base)
            if found.image_url:
                rows.append(
                    LadderMapRow(
                        w3c_name=name,
                        matched_name=found.matched_name,
                        shortname=shortname,
                        image_url=found.image_url,
                        status="off_ladder",
                    )
                )
        return rows

    def import_ladder_maps(self, names: list[str]) -> list[int]:
        """The ids of these ladder maps, in the order named; the w3champions name is the truth.

        A map the app knows under an older name or spelling of the same lineage
        is renamed to the ladder name and keeps its id, results and short name;
        a missing picture is filled. Only a map with no lineage here is created.
        A name off the ladder is a map the app holds: its picture is filled
        from warcraft3.info and nothing else changes. No season pool changes.

        The picture is kept as the url warcraft3.info publishes it at, never copied into our own
        store: those bytes are already served from a CDN and cost us nothing where they are.
        """
        by_base = ladder_maps.map_index()
        wanted = {
            row.w3c_name: row
            for row in ladder_maps.ladder_rows(by_base)
            if row.w3c_name in set(names)
        }
        with Session.begin() as session:
            maps = Map.get_all(session)
            known = _known(maps)
            # a map that already has a picture, uploaded or published, is left alone
            pictured = set(
                session.scalars(select(col(Map.id)).where(col(Map.image).is_not(None)))
            )
            taken = {map.shortname.lower() for map in maps if map.shortname}

        map_ids = []
        with Session.begin() as session:
            for name in dict.fromkeys(names):
                row = wanted.get(name)
                map_id = known(name)
                if not row:
                    if map_id is None or map_id in pictured:
                        continue
                    found = ladder_maps.lookup(name, by_base)
                    if found.image_url:
                        Map.update(session, map_id, image=found.image_url)
                        map_ids.append(map_id)
                    continue
                if map_id is None:
                    shortname = ladder_maps.free_shortname(row.shortname, name, taken)
                    taken.add(shortname.lower())
                    map = Map.add(
                        session,
                        {"name": name, "shortname": shortname, "image": row.image_url},
                    )
                    map_id = ident(map)
                elif row.image_url and map_id not in pictured:
                    Map.update(session, map_id, name=name, image=row.image_url)
                else:
                    Map.update(session, map_id, name=name)
                map_ids.append(map_id)
        return map_ids
