from app.models.match import MatchPublic
from app.models.user import UserPublic
from app.schemas.base import APISchema, IsoDateTime

DB_FIELDS = {
    "match_id",
    "date_time",
    "caster",
    "player1_id",
    "player2_id",
    "player1_score",
    "player2_score",
    "host_player_id",
    "is_fantasy_match",
}


class DraftSeries(APISchema):
    id: int | None = None
    match_id: int | None = None
    match: MatchPublic | None = None
    date_time: IsoDateTime | None = None
    caster: str | None = None
    player1_id: int | None = None
    player1: UserPublic | None = None
    player2_id: int | None = None
    player2: UserPublic | None = None
    player1_score: int | None = 0
    player2_score: int | None = 0
    host_player_id: int | None = None
    is_fantasy_match: bool | None = False
    created_at: IsoDateTime | None = None

    def to_db_dict(self):
        return self.model_dump(include=DB_FIELDS)

    @classmethod
    def from_db_draft_series(cls, draft_series):
        if not draft_series:
            return None

        return cls(
            id=draft_series.id,
            match_id=draft_series.match_id,
            match=MatchPublic.from_match(draft_series.match)
            if draft_series.match
            else None,
            date_time=draft_series.date_time,
            caster=draft_series.caster,
            player1_id=draft_series.player1_id,
            player1=UserPublic.from_user(draft_series.player1)
            if draft_series.player1
            else None,
            player2_id=draft_series.player2_id,
            player2=UserPublic.from_user(draft_series.player2)
            if draft_series.player2
            else None,
            player1_score=draft_series.player1_score,
            player2_score=draft_series.player2_score,
            host_player_id=draft_series.host_player_id,
            is_fantasy_match=draft_series.is_fantasy_match,
            created_at=draft_series.created_at,
        )
