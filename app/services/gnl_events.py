"""Creation rules for the GNL kind of event.

The shared event service creates generic runs. A run of the GNL league also
needs its drafted-team shape, one GNL stage, weekly rounds, a map pool and the
achievement catalogue. They are written in one transaction here.
"""

from sqlalchemy.orm import Session as OrmSession

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.base import ident
from app.models.enums import EventKind, LeagueKind, StageFormat
from app.models.event_stage import EventStage, EventStageWrite
from app.models.ladder_achievement import default_rows
from app.models.league import League
from app.models.map import Map
from app.models.relationships import DBMapSeason
from app.models.season import EventCreate, Season
from app.services.seasons import fill_rounds
from app.services.series_veto import check_order


class GnlEventService:
    """Recognise the GNL league and create one complete run of it."""

    def owns(self, league_id: int | None) -> bool:
        """Whether this league uses the GNL creation rules."""
        if league_id is None:
            return False
        with Session.begin() as session:
            league = session.get(League, league_id)
            return league is not None and league.kind is LeagueKind.gnl

    def add(self, data: EventCreate) -> int:
        """Create a GNL event, its stage, rounds, maps and achievement rules."""
        with Session.begin() as session:
            league = session.get(League, data.league_id)
            if league is None:
                raise NotFoundError(f"League not found by id: {data.league_id}")
            if league.kind is not LeagueKind.gnl:
                raise BadRequestError("The league does not use the GNL event rules")
            if data.kind is not EventKind.gnl:
                raise BadRequestError("An event of the GNL league must have kind gnl")

            fields = data.model_dump(
                exclude={"stages", "round_count", "map_ids", "entrant_kind"}
            )
            event = Season(**fields, entrant_kind=league.entrant_kind)
            session.add(event)
            session.flush()
            check_order(event)

            stages = self._stages(data)
            session.add_all(
                EventStage(
                    event_id=ident(event), position=position, **stage.model_dump()
                )
                for position, stage in enumerate(stages, start=1)
            )
            session.flush()
            fill_rounds(session, event, data.round_count or 0)
            self._add_maps(session, event, data.map_ids)
            session.add_all(default_rows(ident(event)))
            session.flush()
            return ident(event)

    @staticmethod
    def _stages(data: EventCreate) -> list[EventStageWrite]:
        """The one GNL stage, supplied in full or derived from the event rules."""
        if "stages" not in data.model_fields_set:
            rules = data.map_rules.split(",") if data.map_rules else []
            return [
                EventStageWrite(
                    format=StageFormat.gnl,
                    best_of=len(rules) or 3,
                    map_rules=data.map_rules,
                )
            ]
        if len(data.stages) != 1 or data.stages[0].format is not StageFormat.gnl:
            raise BadRequestError("A GNL event has exactly one stage of format gnl")
        return data.stages

    @staticmethod
    def _add_maps(session: OrmSession, event: Season, map_ids: list[int]) -> None:
        """Attach the initial map pool in the order of the request."""
        if len(map_ids) != len(set(map_ids)):
            raise BadRequestError("The initial map pool names each map once")
        for position, map_id in enumerate(map_ids):
            game_map = session.get(Map, map_id)
            if game_map is None:
                raise NotFoundError(f"Map not found by id: {map_id}")
            session.add(
                DBMapSeason(season_id=ident(event), map_id=map_id, position=position)
            )
