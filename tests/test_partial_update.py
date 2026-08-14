"""A PUT that carries some fields leaves the others alone.

One schema used to serve create, update and response, so an update wrote
every column of the row and filled the ones the request left out with
null. A request naming one field answered 500 when a NOT NULL column was
among them, and erased the value when the column was nullable.
"""


def test_a_user_update_keeps_the_fields_it_was_not_given(client, auth_headers, seeded):
    user_id = seeded["player_ids"][0]
    before = client.get(f"/users/{user_id}").json()

    resp = client.put(f"/users/{user_id}", headers=auth_headers, json={"mmr": 2500})
    assert resp.status_code == 200, resp.text
    after = resp.json()

    assert after["mmr"] == 2500
    for field in ("name", "battleTag", "discordTag", "discordId", "race", "country"):
        assert after[field] == before[field], field


def test_a_season_update_keeps_the_fields_it_was_not_given(
    client, auth_headers, seeded
):
    season_id = seeded["season_id"]
    before = client.get(f"/seasons/{season_id}").json()

    resp = client.put(
        f"/seasons/{season_id}", headers=auth_headers, json={"pick_ban": "yes"}
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()

    assert after["pick_ban"] == "yes"
    for field in ("name", "number_weeks", "series_per_week", "start_date", "end_date"):
        assert after[field] == before[field], field


def test_a_team_update_keeps_the_fields_it_was_not_given(client, auth_headers, seeded):
    team_id = seeded["team_a_id"]
    before = client.get(f"/teams/{team_id}").json()

    resp = client.put(
        f"/teams/{team_id}", headers=auth_headers, json={"discord_role": "captains"}
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()

    assert after["discord_role"] == "captains"
    assert after["name"] == before["name"]
    assert after["long_name"] == before["long_name"]


def test_a_create_that_leaves_out_a_required_column_answers_422(client, auth_headers):
    resp = client.post("/users", headers=auth_headers, json={"name": "Nameless"})
    assert resp.status_code == 422, resp.text
    # The error field is what the frontend reads to see a request failed.
    assert "battleTag" in resp.json()["error"]
