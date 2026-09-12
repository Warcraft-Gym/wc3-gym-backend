"""Checks on the mapping itself, independent of any request.

A relationship that needs foreign_keys names its columns in a string, for
example "[Series.match_id]". SQLAlchemy resolves that string the first
time the class is queried, so a wrong name would otherwise surface as a
failing request rather than as a failing test.
"""

import importlib
import pkgutil

from sqlalchemy.orm import configure_mappers

import app.models

TABLES = {
    "admin_grant",
    "clerk_account",
    "discord_post",
    "discord_role_binding",
    "discord_role_hidden",
    "draft_series",
    "event",
    "event_division",
    "event_entrant",
    "event_round",
    "event_stage",
    "fantasy_bets",
    "fantasy_team_player",
    "fantasy_teams",
    "koth_events",
    "koth_match_participants",
    "koth_matches",
    "koth_signups",
    "ladder_achievements",
    "ladder_sync",
    "league",
    "map_season",
    "maps",
    "matches",
    "player_career_stats",
    "round_availability",
    "series",
    "series_cast",
    "series_replay",
    "series_veto_step",
    "settings",
    "team_season",
    "team_season_captain",
    "teams",
    "user_season_signup",
    "user_team_season",
    "users",
    "w3c_ladder_matches",
    "w3cstats",
}


def import_all_models() -> None:
    for module in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{module.name}")


def test_every_mapping_resolves() -> None:
    import_all_models()
    configure_mappers()
