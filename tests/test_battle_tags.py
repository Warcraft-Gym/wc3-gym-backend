"""The real-tag rule of app.core.battle_tags agrees with the migration's copy."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.core import battle_tags

MIGRATION = (
    Path(__file__).parents[1]
    / "migrations/versions/e07324d2b4f9_add_the_user_battle_tag_table.py"
)
TAGS = [
    "Main#11855",
    " Second#1230 ",
    "Name#GNL07",
    "Fantasy_User#bob",
    "fantasy_user#123",
    "Review#4321",
    "review#1",
    "NoHash",
    "Two Words#1234",
    "",
    None,
]
IDS = ["123456789", " 42 ", "gnl-s12-17", "", "  ", None]


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tag_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("tag", TAGS)
def test_the_app_and_the_migration_agree_on_a_real_tag(tag: str | None) -> None:
    assert battle_tags.is_real_tag(tag) == _migration().is_real_tag(tag)


@pytest.mark.parametrize("discord_id", IDS)
def test_the_app_and_the_migration_agree_on_a_login(discord_id: str | None) -> None:
    assert battle_tags.has_login(discord_id) == _migration().has_login(discord_id)


def test_the_stand_ins_are_not_real() -> None:
    assert [battle_tags.is_real_tag(tag) for tag in TAGS[:8]] == [
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
