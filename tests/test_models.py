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


def test_drafted_players_serialize_as_objects_and_empty_reads_as_null() -> None:
    """The drafted players serializer hands pydantic the players themselves.

    Their JSON must stay what UserPublic writes, and an empty list must
    still read as null, which is the shape the fantasy pages expect.
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
    assert empty.model_dump(mode="json")["drafted_players"] is None
