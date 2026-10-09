"""Names and fingerprints for preview databases."""

from pathlib import Path
from typing import cast

import psycopg
import pytest

from api import preview_db
from api.preview_db import branch_db_name, copy_template, migrations_fingerprint


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


class _Recorder:
    def __init__(self, fail_on: str = "") -> None:
        self.sql: list[str] = []
        self.fail_on = fail_on

    def execute(self, sql: str, *_: object) -> None:
        self.sql.append(sql.split()[0] + " " + sql.split()[1])
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError(sql)


def test_template_is_locked_for_the_copy_only() -> None:
    conn = _Recorder()
    copy_template(cast(psycopg.Connection, conn), "wc3gym_x")
    assert conn.sql == [
        "ALTER DATABASE",
        "SELECT pg_terminate_backend(pid)",
        "CREATE DATABASE",
        "ALTER DATABASE",
    ]
    failing = _Recorder(fail_on="CREATE DATABASE")
    with pytest.raises(RuntimeError):
        copy_template(cast(psycopg.Connection, failing), "wc3gym_x")
    assert failing.sql[-1] == "ALTER DATABASE"


def test_main_migrates_staging_not_a_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_connection(*_: object, **__: object) -> psycopg.Connection:
        raise LookupError("connected")

    calls: list[str] = []
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("PREVIEW_BRANCH", "main")
    monkeypatch.delenv("VERCEL_GIT_COMMIT_REF", raising=False)
    monkeypatch.setattr(preview_db, "migrate", lambda: calls.append("migrate"))
    monkeypatch.setattr(preview_db, "connect", no_connection)
    preview_db.build()
    assert calls == ["migrate"]
    assert preview_db.runtime_database() == preview_db.SHARED
    # a git build of any other branch still reads the shared revision to choose or copy
    monkeypatch.delenv("PREVIEW_BRANCH")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_REF", "feature/x")
    with pytest.raises(LookupError):
        preview_db.build()
    assert calls == ["migrate"]
