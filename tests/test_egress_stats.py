"""`report` diffs the last two snapshot lines into rows returned and a billed-MB estimate."""

import json
from pathlib import Path

import pytest

from app.core.egress_stats import BYTES_PER_ROW, report


def test_report_totals_rows_between_two_snapshots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = {
        "at": "2026-09-22T00:00:00+00:00",
        "pooler_sent": 1_000_000.0,
        "sessions": 10,
        "by_database": {"postgres": {"calls": 5, "rows": 1_000}},
        "statements": {
            "1": {"db": "postgres", "calls": 5, "rows": 1_000, "q": "select a"}
        },
    }
    second = {
        "at": "2026-09-23T00:00:00+00:00",
        "pooler_sent": 3_000_000.0,
        "sessions": 12,
        "by_database": {"postgres": {"calls": 25, "rows": 3_501_000}},
        "statements": {
            "1": {"db": "postgres", "calls": 15, "rows": 1_501_000, "q": "select a"},
            "2": {"db": "postgres", "calls": 10, "rows": 2_000_000, "q": "select b"},
        },
    }
    (tmp_path / "prod.jsonl").write_text(
        json.dumps(first) + "\n" + json.dumps(second) + "\n"
    )

    rate = report("prod", out=tmp_path)

    printed = capsys.readouterr().out
    assert "rows returned 3,500,000" in printed
    assert "~350 MB billed" in printed
    assert "pooler counter 2.0 MB" in printed
    assert rate == pytest.approx(3_500_000 * BYTES_PER_ROW / 1e6)
