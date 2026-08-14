"""Checks on the mapping itself, independent of any request.

A relationship that needs foreign_keys names its columns in a string, for
example "[Series.match_id]". SQLAlchemy resolves that string the first
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


def import_all_models() -> None:
    for module in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{module.name}")


def test_every_mapping_resolves() -> None:
    import_all_models()
    configure_mappers()


def test_the_metadata_holds_every_table() -> None:
    """A table missing here is a table create_all does not make."""
    import_all_models()
    assert set(SQLModel.metadata.tables) == TABLES


def test_every_list_field_reads_as_a_list() -> None:
    """A list field answers with a list, empty or not, and never with null.

    The API used to answer null for an empty list on three fields and a
    list on the other seven; these assertions pin the one rule.
    """
    from app.models.enums import Race
    from app.models.fantasy_team import FantasyTeamPublic
    from app.models.user import UserPublic

    players = [
        UserPublic(id=1, name="PlayerA", battleTag="PlayerA#1234", race=Race.HU),
        UserPublic(id=2, name="PlayerB", battleTag="PlayerB#5678", race=Race.OC),
    ]
    team = FantasyTeamPublic(id=7, name="Populated", drafted_players=players)

    assert team.model_dump(mode="json")["drafted_players"] == [
        player.to_dict() for player in players
    ]

    empty = FantasyTeamPublic(id=8, name="Empty", drafted_players=[])
    assert empty.model_dump(mode="json")["drafted_players"] == []

    unset = FantasyTeamPublic(id=9, name="Unset")
    assert unset.model_dump(mode="json")["drafted_players"] == []

    from app.models.season import SeasonPublic

    season = SeasonPublic(id=1, name="Season 1")
    dumped = SeasonPublic.model_dump(season, mode="json")
    assert dumped["maps"] == []
    assert dumped["user_signup"] == []
