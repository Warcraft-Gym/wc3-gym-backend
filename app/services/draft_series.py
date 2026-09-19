import logging
from collections.abc import Iterable

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.base import ident
from app.models.draft_series import (
    DraftSeries,
    DraftSeriesCreate,
    DraftSeriesPublic,
    DraftSeriesUpdate,
)
from app.models.enums import StageFormat
from app.models.event_stage import MAX_MMR_DIFFERENCE, EventStage
from app.models.match import Match
from app.models.match_draft import (
    DBMatchDraftMark,
    DBMatchDraftState,
    MatchDraftStatePublic,
    MatchDraftTeamMark,
    ReplacePreviewPublic,
)
from app.models.season import Season
from app.models.series import Series, SeriesCreate, SeriesPublic
from app.models.series_replay import DBSeriesReplay
from app.models.series_side import SeriesSide
from app.models.series_veto_step import DBSeriesVetoStep
from app.models.types import utcnow
from app.models.user import User
from app.services import derived
from app.services import series as series_writer

logger = logging.getLogger(__name__)


def drafted_players(
    session: OrmSession,
    match_id: int,
    skip_series_id: int | None = None,
    skip_draft_id: int | None = None,
) -> set[int]:
    """Every player the drafted series of one fixture already name.

    A drafted 1v1 is played through the draft tool, so its players sit in
    `draft_series`; a drafted 2v2 names its side in `series_side`; the series
    columns hold a player a promoted draft wrote. A fixture whose template
    holds no drafted series names nobody, so a GNL match reads as it did.
    """
    rows = [
        row
        for row in session.scalars(
            select(Series).where(
                col(Series.match_id) == match_id,
                col(Series.pick_rule) == "drafted",
            )
        )
        if ident(row) != skip_series_id
    ]
    if not rows:
        return set()
    named = {
        player
        for row in rows
        for player in (row.player1_id, row.player2_id)
        if player is not None
    }
    named |= {
        side.user_id
        for side in session.scalars(
            select(SeriesSide).where(
                col(SeriesSide.series_id).in_([ident(row) for row in rows])
            )
        )
        if side.user_id
    }
    named |= {
        player
        for draft in session.scalars(
            select(DraftSeries).where(col(DraftSeries.match_id) == match_id)
        )
        if ident(draft) != skip_draft_id
        for player in (draft.player1_id, draft.player2_id)
    }
    return named


def refuse_repeat(
    session: OrmSession,
    match_id: int | None,
    players: Iterable[int | None],
    skip_series_id: int | None = None,
    skip_draft_id: int | None = None,
) -> None:
    """Refuse a drafted pick naming a player a sibling drafted series holds."""
    if match_id is None:
        return
    picked = {player for player in players if player is not None}
    if picked & drafted_players(session, match_id, skip_series_id, skip_draft_id):
        raise BadRequestError(
            "That player already plays a drafted series of this fixture"
        )


def refuse_full(
    session: OrmSession, match_id: int | None, replaces_series_id: int | None = None
) -> None:
    """A fixture drafts up to the event's series_per_round pairings.

    Published series plus open drafts count. A draft that replaces a published
    series takes its place, so it is free. A templated series carries a
    sequence and is counted by its template, not by the round setting.
    """
    if match_id is None or replaces_series_id is not None:
        return
    per_round = session.scalar(
        select(col(Season.series_per_round))
        .join(Match, col(Match.season_id) == col(Season.id))
        .where(col(Match.id) == match_id)
    )
    if not per_round:
        return
    published = session.scalar(
        select(func.count())
        .select_from(Series)
        .where(col(Series.match_id) == match_id, col(Series.sequence).is_(None))
    )
    drafted = session.scalar(
        select(func.count())
        .select_from(DraftSeries)
        .where(
            col(DraftSeries.match_id) == match_id,
            col(DraftSeries.replaces_series_id).is_(None),
        )
    )
    if (published or 0) + (drafted or 0) >= per_round:
        raise ApiError(
            409,
            {"error": f"This fixture already holds {per_round} series of the round"},
        )


def refuse_bad_replacement(
    session: OrmSession,
    match_id: int | None,
    replaces_series_id: int | None,
    players: Iterable[int | None],
    skip_draft_id: int | None = None,
) -> None:
    """A replacing draft names an open series of its own fixture and keeps a player."""
    if replaces_series_id is None:
        return
    row = session.get(Series, replaces_series_id)
    if row is None or row.match_id != match_id:
        raise BadRequestError("A replacement names a series of the same fixture")
    if row.player1_score is not None or row.player2_score is not None:
        raise BadRequestError("A series that holds a result is not replaced")
    if not {row.player1_id, row.player2_id} & {
        player for player in players if player is not None
    }:
        raise BadRequestError("A replacement keeps one of the two players")
    open_drafts = (
        select(func.count())
        .select_from(DraftSeries)
        .where(col(DraftSeries.replaces_series_id) == replaces_series_id)
    )
    if skip_draft_id is not None:
        open_drafts = open_drafts.where(col(DraftSeries.id) != skip_draft_id)
    if session.scalar(open_drafts):
        raise ApiError(409, {"error": "A draft already replaces this series"})


def clear_ready(session: OrmSession, match_id: int | None) -> None:
    """A changed pairing drops both teams' Ready marks. The mark blocks nothing."""
    if match_id is None:
        return
    session.execute(
        update(DBMatchDraftMark)
        .where(col(DBMatchDraftMark.match_id) == match_id)
        .values(ready_by_user_id=None, ready_at=None)
    )


def _mark(session: OrmSession, match_id: int, team_id: int) -> DBMatchDraftMark:
    """The mark row of one team of one fixture, written on its first use."""
    row = session.get(DBMatchDraftMark, (match_id, team_id))
    if row is None:
        row = DBMatchDraftMark(match_id=match_id, team_id=team_id)
        session.add(row)
        session.flush()
    return row


def _exists(
    session: OrmSession,
    model: type[DBSeriesVetoStep] | type[DBSeriesReplay],
    series_id: int,
) -> bool:
    """Whether the series holds a row of that table, counted, never read."""
    return bool(
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(col(model.series_id) == series_id)
        )
    )


def _refuse_replace(session: OrmSession, series_id: int) -> None:
    """The delete path takes the booked time, the veto and the fantasy rows with
    the series; a result or a replay is never thrown away."""
    row = session.get(Series, series_id)
    if row is None:
        raise NotFoundError("Series not found")
    if row.player1_score is not None or row.player2_score is not None:
        raise ApiError(409, {"error": "That series holds a result"})
    if _exists(session, DBSeriesReplay, series_id):
        raise ApiError(409, {"error": "That series holds a replay"})


def _stage_max_mmr_difference(session: OrmSession, event_id: int) -> int | None:
    """What the captain-draft stage of the event names; null when it has none."""
    stage = session.scalars(
        select(EventStage)
        .where(
            col(EventStage.event_id) == event_id,
            col(EventStage.format) == StageFormat.gnl,
        )
        .order_by(col(EventStage.position))
    ).first()
    if stage is None:
        return None
    return stage.max_mmr_difference or MAX_MMR_DIFFERENCE


class DraftSeriesService:
    def add(
        self, draft_series: DraftSeriesCreate, user_id: int | None = None
    ) -> DraftSeriesPublic:
        with Session.begin() as session:
            now = utcnow()
            row = DraftSeries.add(
                session,
                draft_series.model_dump()
                | {
                    "created_at": now,
                    "updated_at": now,
                    "created_by_user_id": user_id,
                    "updated_by_user_id": user_id,
                },
            )
            clear_ready(session, row.match_id)
            public = DraftSeriesPublic.from_draft_series(row)
            derived.fill_signup_races(session, [public])
            return public

    def update(
        self,
        draft_series_id: int,
        draft_series: DraftSeriesUpdate,
        user_id: int | None = None,
    ) -> DraftSeriesPublic:
        with Session.begin() as session:
            row = DraftSeries.update(
                session,
                draft_series_id,
                **draft_series.model_dump(exclude_unset=True),
                updated_at=utcnow(),
                updated_by_user_id=user_id,
            )
            if not row:
                raise NotFoundError("Draft series not found")
            clear_ready(session, row.match_id)
            public = DraftSeriesPublic.from_draft_series(row)
            derived.fill_signup_races(session, [public])
            return public

    def delete(self, draft_series_id: int) -> None:
        with Session.begin() as session:
            row = DraftSeries.delete(session, draft_series_id)
            if row:
                clear_ready(session, row.match_id)

    def get(self, draft_series_id: int) -> DraftSeriesPublic:
        with Session.begin() as session:
            draft_series = session.scalars(
                select(DraftSeries)
                .options(*DraftSeries._eager_options())
                .where(col(DraftSeries.id) == draft_series_id)
            ).first()
            if not draft_series:
                raise NotFoundError("Draft series not found")
            public = DraftSeriesPublic.from_draft_series(draft_series)
            derived.fill_signup_races(session, [public])
            return public

    def get_by_match_id(
        self, match_id: int, limit: int | None = None, offset: int = 0
    ) -> list[DraftSeriesPublic]:
        with Session.begin() as session:
            # Offset paging is deterministic only with a fixed order
            statement = (
                select(DraftSeries)
                .options(*DraftSeries._eager_options())
                .where(col(DraftSeries.match_id) == match_id)
                .order_by(col(DraftSeries.id))
                .offset(offset)
                .limit(limit)
            )
            result = [
                DraftSeriesPublic.from_draft_series(row)
                for row in session.scalars(statement).all()
            ]
            derived.fill_signup_races(session, result)
            return result

    def delete_by_match_id(self, match_id: int) -> None:
        """Delete all draft series for a given match"""
        with Session.begin() as session:
            session.execute(
                delete(DraftSeries).where(col(DraftSeries.match_id) == match_id)
            )
            clear_ready(session, match_id)

    def promote(self, draft_series_id: int) -> SeriesPublic:
        """Publish a draft: write the series and drop the draft, in one transaction.

        A draft that names a series it replaces removes that series in the same
        transaction, so the admin swaps the pairing in one action.
        """
        with Session.begin() as session:
            draft = session.get(DraftSeries, draft_series_id)
            if not draft:
                raise NotFoundError("Draft series not found")
            if draft.replaces_series_id is not None:
                _refuse_replace(session, draft.replaces_series_id)
                Series.delete(session, draft.replaces_series_id)
            create = SeriesCreate(
                match_id=draft.match_id,
                date_time=draft.date_time,
                player1_id=draft.player1_id,
                player2_id=draft.player2_id,
                player1_score=draft.player1_score,
                player2_score=draft.player2_score,
                host_player_id=draft.host_player_id,
                is_fantasy_match=draft.is_fantasy_match,
            )
            match_id = draft.match_id
            session.delete(draft)
            session.flush()
            public = series_writer.add_in(session, create)
            clear_ready(session, match_id)
            return public

    def replace_preview(self, draft_series_id: int) -> ReplacePreviewPublic:
        """What promoting this draft takes away: the booked time and the veto."""
        with Session.begin() as session:
            draft = session.get(DraftSeries, draft_series_id)
            if not draft or draft.replaces_series_id is None:
                raise NotFoundError("This draft replaces no series")
            row = session.get(Series, draft.replaces_series_id)
            if not row:
                raise NotFoundError("Series not found")
            return ReplacePreviewPublic(
                series_id=ident(row),
                date_time=row.date_time,
                has_veto=_exists(session, DBSeriesVetoStep, ident(row)),
                has_replay=_exists(session, DBSeriesReplay, ident(row)),
                has_result=row.player1_score is not None
                or row.player2_score is not None,
            )

    def state(self, match_id: int, team_id: int | None = None) -> MatchDraftStatePublic:
        """The Ready marks, the caller's seen stamp and the working MMR values."""
        with Session.begin() as session:
            match = session.get(Match, match_id)
            if not match:
                raise NotFoundError("Match not found")
            stage_value = _stage_max_mmr_difference(session, match.season_id)
            state = session.get(DBMatchDraftState, match_id)
            working = state.max_mmr_difference if state else None
            marks = {
                row.team_id: (row, name)
                for row, name in session.execute(
                    select(DBMatchDraftMark, col(User.name))
                    .outerjoin(
                        User, col(User.id) == col(DBMatchDraftMark.ready_by_user_id)
                    )
                    .where(col(DBMatchDraftMark.match_id) == match_id)
                ).all()
            }
            return MatchDraftStatePublic(
                match_id=match_id,
                max_mmr_difference=working if working is not None else stage_value,
                stage_max_mmr_difference=stage_value,
                teams=[
                    MatchDraftTeamMark(
                        team_id=team,
                        ready_by_user_id=marks[team][0].ready_by_user_id
                        if team in marks
                        else None,
                        ready_by_name=marks[team][1] if team in marks else None,
                        ready_at=marks[team][0].ready_at if team in marks else None,
                    )
                    for team in (match.team1_id, match.team2_id)
                ],
                seen_at=marks[team_id][0].seen_at
                if team_id is not None and team_id in marks
                else None,
            )

    def set_ready(
        self, match_id: int, team_id: int, ready: bool, user_id: int | None
    ) -> MatchDraftStatePublic:
        """Mark one team ready or take the mark back. It blocks no promote."""
        with Session.begin() as session:
            row = _mark(session, match_id, team_id)
            row.ready_by_user_id = user_id if ready else None
            row.ready_at = utcnow() if ready else None
            session.flush()
        return self.state(match_id, team_id)

    def set_seen(self, match_id: int, team_id: int) -> None:
        """Record that the team read the pairings, so later edits read as new."""
        with Session.begin() as session:
            _mark(session, match_id, team_id).seen_at = utcnow()

    def set_max_mmr_difference(
        self, match_id: int, value: int | None, team_id: int | None = None
    ) -> MatchDraftStatePublic:
        """The working largest MMR difference of the fixture; null clears it."""
        with Session.begin() as session:
            row = session.get(DBMatchDraftState, match_id)
            if row is None:
                row = DBMatchDraftState(match_id=match_id)
                session.add(row)
            row.max_mmr_difference = value
            session.flush()
        return self.state(match_id, team_id)
