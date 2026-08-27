"""Names and fingerprints for preview databases."""

from pathlib import Path

from api.preview_db import branch_db_name, migrations_fingerprint


def test_branch_db_name_is_short_and_unique() -> None:
    name = branch_db_name("feature/a-very-long-branch-name-here")
    assert name.startswith("wc3gym_")
    assert len(name) <= 32
    # colliding slugs, different hashes
    assert branch_db_name("feature/foo-bar") != branch_db_name("feature/foo_bar")


def test_fingerprint_follows_the_migration_files(tmp_path: Path) -> None:
    empty = migrations_fingerprint(tmp_path)
    (tmp_path / "a1b2_add_a_table.py").write_text("revision = 'a1b2'")
    added = migrations_fingerprint(tmp_path)
    (tmp_path / "a1b2_add_a_table.py").write_text("revision = 'a1b2'  # edited")
    edited = migrations_fingerprint(tmp_path)
    assert len({empty, added, edited}) == 3
