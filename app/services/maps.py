import logging
from collections.abc import Callable, Sequence
from time import monotonic

from sqlalchemy import func, or_, select
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import BadRequestError, ExternalServiceError, NotFoundError
from app.core.query import QueryElement, QueryUtil
from app.models.base import ident
from app.models.map import (
    MAP_NAME_LENGTH,
    LadderMapRow,
    Map,
    MapCreate,
    MapPublic,
    MapSourcePublic,
    MapUpdate,
    SourceMapPick,
    SourceMapRow,
)
from app.models.types import map_modes
from app.services import blob, ladder_maps, map_sources
from app.services.map_sources.base import read

logger = logging.getLogger(__name__)

# Seconds one call may spend copying pictures, so that it ends inside the function's time limit
COPY_SECONDS = 40


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


def _ladder_row(
    name: str, hit: map_sources.Hit | None, unreached: list[str]
) -> LadderMapRow:
    """One map of the ladder import, and what the source that knew it holds."""
    if hit is None:
        return LadderMapRow(w3c_name=name, status="no_match", unreached=unreached)
    source, row = hit
    return LadderMapRow(
        w3c_name=name,
        matched_name=row.name,
        shortname=row.shortname,
        # a picture still to copy is not ours, and the site can refuse it to a page
        image_url=None if source.copies_pictures else row.picture_url,
        source=source.title,
        unreached=unreached,
    )


class MapService:
    def add(self, map: MapCreate) -> MapPublic:
        with Session.begin() as session:
            new_map = Map.add(session, map.model_dump())
            return MapPublic.model_validate(new_map)

    def add_custom(self, name: str) -> MapPublic:
        """The custom game map of that name: the one the app holds under it as
        its name or its short name, or a new map marked `custom`, its short
        name kept apart from every other map's."""
        wanted = name.strip()
        if not wanted:
            raise BadRequestError("Name the map")
        key = wanted.lower()
        with Session.begin() as session:
            found = session.scalars(
                select(Map).where(
                    or_(
                        func.lower(func.trim(col(Map.name))) == key,
                        func.lower(func.trim(col(Map.shortname))) == key,
                    )
                )
            ).first()
            if found is not None:
                return MapPublic.model_validate(found)
            taken = set(
                session.scalars(
                    select(func.lower(func.trim(col(Map.shortname)))).where(
                        func.lower(func.trim(col(Map.shortname))).like(f"{key[:40]}%")
                    )
                )
            )
            short, number = wanted[:50], 2
            while short.lower() in taken:
                short = f"{wanted[:44]} ({number})"
                number += 1
            made = Map(name=wanted, shortname=short, modes="custom")
            session.add(made)
            session.flush()
            return MapPublic.model_validate(made)

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

    def update_icon(
        self, map_id: int, file: bytes, keep_existing: bool = False
    ) -> None:
        """Put the picture in the store, then point the row at it, the way a team logo is stored.
        `keep_existing` drops this picture instead when the map has gained one meanwhile."""
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
            if keep_existing and map.image:
                unused = url
            else:
                unused, map.image = map.image, url
        if unused and blob.ours(unused):
            blob.delete_blob(unused)

    def get_image_url(self, map_id: int) -> str | None:
        """Where the picture is published, or None for a map without one."""
        with Session.begin() as session:
            return session.scalar(select(col(Map.image)).where(col(Map.id) == map_id))

    def get_all(self, limit: int | None = None, offset: int = 0) -> list[MapPublic]:
        with Session.begin() as session:
            maps = Map.get_all(session, limit=limit, offset=offset)
            return [MapPublic.model_validate(map) for map in maps]

    def _fill_pictures(self, pictures: list[tuple[int, map_sources.Hit]]) -> None:
        """Give each map its source's picture while it still has none, after the
        maps are committed: kept at its url, or copied into our store. A picture
        that cannot be copied, or that the time runs out for, is logged and the map
        stays without one until the next import."""
        deadline = monotonic() + COPY_SECONDS
        for map_id, (source, row) in pictures:
            if not row.picture_url:
                continue
            if source.copies_pictures:
                if monotonic() > deadline:
                    logger.warning("Map %s kept no picture: out of time", map_id)
                    continue
                try:
                    picture = read(row.picture_url).content
                    self.update_icon(map_id, picture, keep_existing=True)
                except (BadRequestError, ExternalServiceError) as error:
                    logger.warning("Map %s kept no picture: %s", map_id, error)
                continue
            with Session.begin() as session:
                map = session.get(Map, map_id, with_for_update=True)
                if map and not map.image:
                    map.image = row.picture_url

    def sources(self) -> list[MapSourcePublic]:
        """The sites an organizer or an admin can take maps from."""
        return [
            MapSourcePublic(
                key=source.key,
                title=source.title,
                credit_url=source.credit_url,
                license=source.license,
            )
            for source in map_sources.SOURCES.values()
        ]

    def source_rows(self, key: str, q: str = "") -> list[SourceMapRow]:
        """A source's maps matching a search, each with the map of the app it is."""
        rows = map_sources.source_of(key).catalogue(q)
        with Session.begin() as session:
            maps = Map.get_all(session)
            known = _known(maps)
            pictured = {ident(map) for map in maps if map.image}
        return [
            SourceMapRow(
                name=row.name,
                players=row.players,
                modes=row.modes,
                shortname=row.shortname,
                picture_url=row.picture_url,
                map_id=known(row.name),
                pictured=known(row.name) in pictured,
            )
            for row in rows
            # a name the table cannot hold is not offered
            if len(row.name) <= MAP_NAME_LENGTH
        ]

    def import_from_source(self, key: str, picks: list[SourceMapPick]) -> list[int]:
        """The ids of the picked maps, in the order picked. A new map takes the
        source's short name, else its initials. A map the app holds under this name
        or lineage gains the modes and a missing picture, and keeps the rest."""
        source = map_sources.source_of(key)
        chosen = {pick.name: pick.modes for pick in picks}
        found = source.find(list(chosen))
        map_ids = []
        pictures: list[tuple[int, map_sources.Hit]] = []
        with Session.begin() as session:
            maps = Map.get_all(session)
            known = _known(maps)
            modes_of = {ident(map): map.modes for map in maps}
            pictured = {ident(map) for map in maps if map.image}
            taken = {map.shortname.lower() for map in maps if map.shortname}
            for name, modes in chosen.items():
                row = found.get(name)
                map_id = known(name)
                if map_id is None:
                    shortname = ladder_maps.free_shortname(
                        row.shortname if row else None, name, taken
                    )
                    taken.add(shortname.lower())
                    map_id = ident(
                        Map.add(
                            session,
                            {"name": name, "shortname": shortname, "modes": modes},
                        )
                    )
                else:
                    Map.update(
                        session, map_id, modes=_tagged(modes_of.get(map_id), modes)
                    )
                if row and map_id not in pictured:
                    pictures.append((map_id, (source, row)))
                map_ids.append(map_id)
        self._fill_pictures(pictures)
        return map_ids

    def ladder_import_preview(
        self, mode: int = ladder_maps.SOLO_MODE
    ) -> list[LadderMapRow]:
        """Every ladder map of one game mode and whether the app already holds it,
        then every map the app holds off the ladder whose picture a source has. A
        source is read only for a map that is new or has no picture."""
        with Session.begin() as session:
            maps = Map.get_all(session)
            known = _known(maps)
            holds = {ident(map): (map.name, map.shortname, map.image) for map in maps}
            taken = {map.shortname.lower() for map in maps if map.shortname}
            unpictured = {
                ident(map): map.name for map in maps if map.name and not map.image
            }
        ladder = ladder_maps.ladder_names(mode)
        on_ladder = {known(name) for name in ladder}
        off_ladder = {
            map_id: name
            for map_id, name in unpictured.items()
            if map_id not in on_ladder
        }
        found, unreached = map_sources.find_in_order(
            [
                lookup
                for name, lookup in ladder.items()
                if known(name) is None or known(name) in unpictured
            ]
            + list(off_ladder.values())
        )
        rows = []
        for name, lookup in ladder.items():
            row = _ladder_row(name, found.get(lookup), unreached)
            map_id = known(name)
            if map_id is not None:
                # what is shown is what the map will have: a known map keeps its own
                held_name, shortname, image = holds[map_id]
                row.status = "known"
                row.map_id = map_id
                row.matched_name = row.matched_name or held_name
                row.shortname = shortname
                row.image_url = image or row.image_url
            else:
                row.shortname = ladder_maps.free_shortname(row.shortname, name, taken)
                taken.add(row.shortname.lower())
            rows.append(row)
        for map_id, name in off_ladder.items():
            hit = found.get(name)
            if hit and hit[1].picture_url:
                row = _ladder_row(name, hit, unreached)
                row.status = "off_ladder"
                row.shortname = holds[map_id][1]
                rows.append(row)
        return rows

    def import_ladder_maps(
        self,
        names: list[str],
        mode: int = ladder_maps.SOLO_MODE,
        ladder_only: bool = False,
    ) -> list[int]:
        """The ids of these ladder maps, in the order named; the w3champions name is the truth.

        A map the app knows under an older name or spelling of the same lineage
        is renamed to the ladder name and keeps its id, results and short name;
        a missing picture is filled. Only a map with no lineage here is created.
        A name off the ladder is a map the app holds: its picture is filled
        from a source and nothing else changes. No season pool changes.

        `mode` names the ladder the names are read against, 1v1 unless named;
        `ladder_only` leaves every name off that ladder alone, as an organizer's
        import does: it brings a cup the ladder maps and touches no other map.
        """
        ladder = ladder_maps.ladder_names(mode)
        tag = ladder_maps.MODE_NAMES.get(mode)
        with Session.begin() as session:
            maps = Map.get_all(session)
            known = _known(maps)
            modes = {ident(map): map.modes for map in maps}
            # a map that already has a picture, uploaded or published, is left alone
            pictured = {ident(map) for map in maps if map.image}
            taken = {map.shortname.lower() for map in maps if map.shortname}
        wanted = [
            name
            for name in dict.fromkeys(names)
            if name in ladder
            or not (ladder_only or known(name) is None or known(name) in pictured)
        ]
        found, _ = map_sources.find_in_order(
            [ladder.get(name, name) for name in wanted if known(name) not in pictured]
        )

        map_ids = []
        pictures: list[tuple[int, map_sources.Hit]] = []
        with Session.begin() as session:
            for name in wanted:
                hit = found.get(ladder.get(name, name))
                map_id = known(name)
                if name not in ladder:
                    if map_id is not None and hit and hit[1].picture_url:
                        pictures.append((map_id, hit))
                        map_ids.append(map_id)
                    continue
                if map_id is None:
                    shortname = ladder_maps.free_shortname(
                        hit[1].shortname if hit else None, name, taken
                    )
                    taken.add(shortname.lower())
                    map = Map.add(
                        session,
                        {
                            "name": name,
                            "shortname": shortname,
                            "modes": map_modes([tag] if tag else None),
                        },
                    )
                    map_id = ident(map)
                else:
                    Map.update(
                        session,
                        map_id,
                        name=name,
                        modes=_tagged(modes.get(map_id), tag),
                    )
                if hit and map_id not in pictured:
                    pictures.append((map_id, hit))
                map_ids.append(map_id)
        self._fill_pictures(pictures)
        return map_ids


def _tagged(current: str | None, tag: str | None) -> str | None:
    """The modes of a map with the ones it was imported as added."""
    if not tag:
        return current
    return map_modes(f"{current or ''},{tag}")
