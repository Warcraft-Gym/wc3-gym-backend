"""Checks on the mapping itself, independent of any request.

A relationship that needs foreign_keys names its columns in a string, for
example "[DBSeries.match_id]". SQLAlchemy resolves that string the first
time the class is queried, so a wrong name would otherwise surface as a
failing request rather than as a failing test.
"""

import importlib
import pkgutil

from sqlalchemy.orm import configure_mappers
from sqlmodel import SQLModel

import app.models

TABLES = {
    "draft_series",
    "fantasy_bets",
    "fantasy_team_player",
    "fantasy_teams",
    "koth_events",
    "koth_match_participants",
    "koth_matches",
    "koth_signups",
    "map_season",
    "maps",
    "matches",
    "player_career_stats",
    "seasons",
    "series",
    "settings",
    "team_season",
    "teams",
    "user_season_signup",
    "user_team_season",
    "users",
    "w3cstats",
}


def import_all_models():
    for module in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{module.name}")


def test_every_mapping_resolves():
    import_all_models()
    configure_mappers()


def test_the_metadata_holds_every_table():
    """A table missing here is a table create_all does not make."""
    import_all_models()
    assert set(SQLModel.metadata.tables) == TABLES
