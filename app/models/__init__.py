"""Importing any model imports them all.

A relationship names its target class in a string, and SQLAlchemy looks
the name up in the registry when the mappers configure. The class behind
the name registers when its module imports, so this package imports every
model module up front and no import order can leave a name unresolved.
"""

from app.models import (
    base,
    draft_series,
    enums,
    fantasy_bet,
    fantasy_team,
    koth_event,
    koth_match,
    koth_match_participant,
    koth_signup,
    map,
    match,
    player_career_stats,
    relationships,
    season,
    season_info,
    series,
    settings,
    team,
    team_reduced,
    team_season,
    types,
    user,
    user_team_season,
    w3c_stats,
)

__all__ = [
    "base",
    "draft_series",
    "enums",
    "fantasy_bet",
    "fantasy_team",
    "koth_event",
    "koth_match",
    "koth_match_participant",
    "koth_signup",
    "map",
    "match",
    "player_career_stats",
    "relationships",
    "season",
    "season_info",
    "series",
    "settings",
    "team",
    "team_reduced",
    "team_season",
    "types",
    "user",
    "user_team_season",
    "w3c_stats",
]
