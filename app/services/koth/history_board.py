"""The bounded archive board, with no live queue or current ladder lookups."""

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlmodel import col

from app.models.base import ident
from app.models.event_entrant import EventEntrant
from app.models.event_history import (
    EventVideo,
    EventVideoPublic,
    HistoricalParticipant,
    KothHistorySeries,
)
from app.models.koth_night import (
    KothBoard,
    KothBracket,
    KothHistoricalSeries,
    KothPlayer,
)
from app.models.season import Season
from app.services.koth.history_import import bounds
from app.services.koth.night import divisions_of, series_of


def read_archive(session: Session, night: Season, date_label: str) -> KothBoard:
    """Six narrow batch reads after the event and archive lookup; raw evidence stays private."""
    event_id = ident(night)
    people = {
        entrant_id: KothPlayer(entrant_id=entrant_id, name=name)
        for entrant_id, name in session.execute(
            select(col(EventEntrant.id), col(HistoricalParticipant.source_name))
            .join(
                HistoricalParticipant,
                col(HistoricalParticipant.id) == EventEntrant.historical_participant_id,
            )
            .where(col(EventEntrant.event_id) == event_id)
        )
    }
    series = series_of(session, event_id)
    inferred = {
        series_id: (winner, note)
        for series_id, winner, note in session.execute(
            select(
                col(KothHistorySeries.series_id),
                col(KothHistorySeries.inferred_winner),
                col(KothHistorySeries.review_note),
            ).where(col(KothHistorySeries.event_id) == event_id)
        )
    }
    brackets = []
    for division in divisions_of(session, event_id):
        brackets.append(
            KothBracket(
                division_id=ident(division),
                name=division.name,
                lower_bound=division.lower_bound,
                upper_bound=bounds(division.name or "")[1],
                historical=True,
                historical_king=people.get(division.king_entrant_id or 0),
                history=[
                    KothHistoricalSeries(
                        series_id=ident(row),
                        sequence=row.sequence or 0,
                        side1=people[row.entrant1_id],
                        side2=people[row.entrant2_id],
                        result_unavailable=row.result_unavailable,
                        winner_side=None
                        if row.result_unavailable
                        else 1
                        if (row.player1_score or 0) > (row.player2_score or 0)
                        else 2,
                        inferred_winner_side=inferred.get(ident(row), (None, None))[0],
                        review_note=inferred.get(ident(row), (None, None))[1],
                    )
                    for row in series
                    if row.division_id == ident(division)
                ],
            )
        )
    videos = [
        EventVideoPublic(id=id_, url=url, title=title, kind=kind)
        for id_, url, title, kind in session.execute(
            select(
                col(EventVideo.id),
                col(EventVideo.url),
                col(EventVideo.title),
                col(EventVideo.kind),
            )
            .where(col(EventVideo.event_id) == event_id)
            .order_by(col(EventVideo.position))
        )
    ]
    return KothBoard(
        night_id=event_id,
        name=night.name,
        closed=True,
        historical=True,
        date_label=date_label,
        entrant_count=len(people),
        series_count=len(series),
        brackets=brackets,
        videos=videos,
    )
