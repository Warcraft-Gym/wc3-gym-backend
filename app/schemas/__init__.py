"""The API schemas that have not moved into a model family yet.

Each of these still declares its own fields separately from the table it
is built from. The ones that have moved live next to their table in
app/models.
"""

from app.schemas.base import APISchema
from app.schemas.draft_series import DraftSeries
from app.schemas.fantasy_bet import FantasyBet
from app.schemas.fantasy_team import FantasyTeam
from app.schemas.player_career_stats import PlayerCareerStats

__all__ = [
    "APISchema",
    "DraftSeries",
    "FantasyBet",
    "FantasyTeam",
    "PlayerCareerStats",
]
