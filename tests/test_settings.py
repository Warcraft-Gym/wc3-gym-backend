"""DELETE /config/settings/{key} answers by whether the key exists.

The admin frontend reads the status code to decide a delete worked, so both answers
are pinned here.
"""

from typing import Any

from httpx2 import Client


def test_delete_setting_answers_200_and_removes_the_row(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    resp = client.delete("/config/settings/score_system", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "Setting 'score_system' deleted successfully"

    resp = client.get("/config/settings/score_system")
    assert resp.status_code == 404


def test_delete_missing_setting_answers_404(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    resp = client.delete("/config/settings/no_such_key", headers=auth_headers)
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.json()["error"].lower()


def test_secret_settings_never_leave_through_the_open_reads(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    resp = client.post("/config/koth/nightbot-token", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]

    keys = {s["key"] for s in client.get("/config/settings").json()["settings"]}
    assert "KOTH_NIGHTBOT_TOKEN" not in keys

    resp = client.get("/config/settings/KOTH_NIGHTBOT_TOKEN")
    assert resp.status_code == 404, resp.text

    resp = client.get("/config/koth/nightbot-token", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["token"] == token
