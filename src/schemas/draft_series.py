from src.schemas.base import APISchema, IsoDateTime
from src.schemas.match import Match
from src.schemas.user import User

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
    match: Match | None = None
    date_time: IsoDateTime | None = None
    caster: str | None = None
    player1_id: int | None = None
    player1: User | None = None
    player2_id: int | None = None
    player2: User | None = None
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
            match=Match.from_dbmatch(draft_series.match)
            if draft_series.match
            else None,
            date_time=draft_series.date_time,
            caster=draft_series.caster,
            player1_id=draft_series.player1_id,
            player1=User.from_dbuser(draft_series.player1)
            if draft_series.player1
            else None,
            player2_id=draft_series.player2_id,
            player2=User.from_dbuser(draft_series.player2)
            if draft_series.player2
            else None,
            player1_score=draft_series.player1_score,
            player2_score=draft_series.player2_score,
            host_player_id=draft_series.host_player_id,
            is_fantasy_match=draft_series.is_fantasy_match,
            created_at=draft_series.created_at,
        )

    @staticmethod
    def schema():
        return {
            "type": "object",
            "properties": {
                "match_id": {"type": "integer"},
                "date_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": 'ISO 8601 date-time (e.g., "2025-03-08T18:57:00Z")',
                },
                "caster": {"type": "string"},
                "player1_id": {"type": "integer"},
                "player2_id": {"type": "integer"},
                "player1_score": {"type": "integer"},
                "player2_score": {"type": "integer"},
                "host_player_id": {"type": "integer"},
                "is_fantasy_match": {"type": "boolean"},
            },
            "required": ["match_id", "player1_id", "player2_id", "host_player_id"],
        }
