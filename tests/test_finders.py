"""The finders read a column. The query language reads a string.

A value is free text: a player may be called "Fire or Ice", and a Discord
id arrives in the body of a public request. Put such a value into a query
string and the parser reads it as part of the query, not as the value.
These tests pin the difference.
"""

import pytest
from fastapi import FastAPI

from app.core.query import QueryUtil
from app.models.enums import Race
from app.models.user import UserCreate
from app.services.users import UserService


@pytest.fixture
def users(app: FastAPI) -> UserService:
    service = UserService()
    for name, race in [("Fire or Ice", Race.RANDOM), ("Grubby", Race.UD)]:
        service.add(
            UserCreate(
                name=name,
                battleTag=f"{name}#1234",
                discordTag=name,
                discordId=f"id-{name}",
                race=race,
            )
        )
    return service


def test_the_query_language_cannot_carry_that_name(users: UserService) -> None:
    """The parser splits the value at " or "."""
    with pytest.raises(Exception, match="could not be parsed"):
        QueryUtil.parse_query("name == Fire or Ice")


def test_find_by_discord_id_treats_the_value_as_a_value(users: UserService) -> None:
    """A crafted id matches nothing. Through the query language the same
    text used to widen the search to every row."""
    crafted = "id-Grubby or id >= 1"

    assert users.find_by_discord_id(crafted) == []

    widened = QueryUtil.parse_query(f"discordId == {crafted}")
    assert len(users.search(widened)) == 2


def test_a_name_matches_in_any_case(users: UserService) -> None:
    """Postgres compares text case-sensitively, so the search folds both sides."""
    found = users.search(QueryUtil.parse_query("name == grubby"))

    assert [user.name for user in found] == ["Grubby"]


def test_not_equals_drops_a_name_in_another_case(users: UserService) -> None:
    found = users.search(QueryUtil.parse_query("name != grubby"))

    assert [user.name for user in found] == ["Fire or Ice"]


def test_ilike_still_matches_part_of_a_name(users: UserService) -> None:
    found = users.search(QueryUtil.parse_query("name ilike RUBB"))

    assert [user.name for user in found] == ["Grubby"]


def test_a_number_still_compares_as_a_number(users: UserService) -> None:
    grubby = users.find_by_discord_id("id-Grubby")[0]

    found = users.search(QueryUtil.parse_query(f"id == {grubby.id}"))

    assert [user.name for user in found] == ["Grubby"]


def test_a_race_matches_in_any_case(users: UserService) -> None:
    """Postgres rejects an enum literal in the wrong case outright."""
    found = users.search(QueryUtil.parse_query("race == ud"))

    assert [user.name for user in found] == ["Grubby"]
    assert found == users.search(QueryUtil.parse_query("race == UD"))


def test_a_race_the_enum_does_not_hold_is_rejected(users: UserService) -> None:
    with pytest.raises(Exception, match="does not take"):
        users.search(QueryUtil.parse_query("race == NOTARACE"))


def test_ilike_matches_part_of_a_race(users: UserService) -> None:
    found = users.search(QueryUtil.parse_query("race ilike u"))

    assert [user.name for user in found] == ["Grubby"]
