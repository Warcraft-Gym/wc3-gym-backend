"""Importing any model imports them all.

A relationship names its target class in a string, and SQLAlchemy looks
the name up in the registry when the mappers configure. The class behind
the name registers when its module imports, so this package imports every
model module up front and no import order can leave a name unresolved.
"""

# The import list is the registration itself, so no name in it is read here
# ruff: noqa: F401
from sqlmodel import SQLModel

# The convention applies when a table is built, so it is set before the imports
SQLModel.metadata.naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

from app.models import (
    base,
    discord_role_binding,
    draft_series,
    enums,
    fantasy_bet,
    fantasy_team,
    koth_event,
    koth_match,
    koth_match_participant,
    koth_signup,
    ladder_achievement,
    ladder_sync,
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
    w3c_ladder_match,
    w3c_stats,
)
