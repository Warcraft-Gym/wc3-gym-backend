"""A cup that repeats on a rule, and the cups made from it.

A runner sets a rule up from a cup, which becomes its first occurrence. The
rule names its days, every week or the nth weekday of the month, and a runner
of the latest cup makes the next one on a day the rule names: a copy with its
own name, its own start, its stages, its rounds moved by the same days and
its organizers. Stopping the rule keeps every cup it made.
"""

from datetime import date
from typing import Any

from httpx2 import Client

from app.models.cup_recurrence import CupRecurrence
from app.services.cup_recurrence import days_of, names_day
from tests.test_cup_divisions import make_cup
from tests.test_event_organizers import Headers, grant

# a Friday, years ahead, so no day of the rule has passed
FRIDAY = "2030-01-04T19:00:00Z"
WEEKLY = {"name": "Friday Cup", "weekday": 4, "start_time": "19:00", "zone": "UTC"}


def rule(**fields: Any) -> CupRecurrence:  # noqa: ANN401
    return CupRecurrence(
        name="R",
        weekday=4,
        start_time="19:00",
        zone="UTC",
        starts_on=date(2030, 1, 4),
        created_by="1",
        **fields,
    )


def repeat(client: Client, headers: Headers, **fields: Any) -> tuple[dict, dict]:  # noqa: ANN401
    cup = make_cup(
        client,
        headers,
        name=f"Cup {fields.pop('tag', 'A')}",
        starts_at=FRIDAY,
        **fields,
    )
    response = client.post(
        f"/events/{cup['id']}/recurrence", json=WEEKLY, headers=headers
    )
    assert response.status_code == 201, response.text
    return cup, response.json()


def occur(client: Client, headers: Headers, recurrence: int, day: str) -> Any:  # noqa: ANN401
    return client.post(
        f"/cup-recurrences/{recurrence}/occurrences", json={"on": day}, headers=headers
    )


def test_a_rule_names_every_week_or_the_nth_weekday_of_the_month() -> None:
    weekly = rule()
    assert list(next_days(weekly, date(2030, 1, 1), 3)) == [
        date(2030, 1, 4),
        date(2030, 1, 11),
        date(2030, 1, 18),
    ]
    first = rule(nth=1)
    assert list(next_days(first, date(2030, 1, 5), 2)) == [
        date(2030, 2, 1),
        date(2030, 3, 1),
    ]
    last = rule(nth=-1, ends_on=date(2030, 3, 1))
    assert list(next_days(last, date(2030, 1, 1), 5)) == [
        date(2030, 1, 25),
        date(2030, 2, 22),
    ]
    assert names_day(first, date(2030, 2, 1))
    assert not names_day(first, date(2030, 2, 8))
    assert not names_day(weekly, date(2030, 1, 5))


def next_days(row: CupRecurrence, start: date, count: int) -> list[date]:
    days = []
    for day in days_of(row, start):
        days.append(day)
        if len(days) == count:
            break
    return days


def test_a_cup_becomes_the_first_occurrence_of_its_rule(
    client: Client, auth_headers: Headers
) -> None:
    cup, made = repeat(client, auth_headers)

    assert (made["starts_on"], made["latest_event_id"]) == ("2030-01-04", cup["id"])
    assert [row["event_id"] for row in made["occurrences"]] == [cup["id"]]
    assert [row["on"] for row in made["upcoming"]][:3] == [
        "2030-01-04",
        "2030-01-11",
        "2030-01-18",
    ]
    assert len(made["upcoming"]) == 8
    assert made["upcoming"][0]["event_id"] == cup["id"]
    read = client.get(f"/events/{cup['id']}").json()
    assert read["cup_recurrence"] == {"id": made["id"], "name": "Friday Cup"}
    again = client.post(
        f"/events/{cup['id']}/recurrence", json=WEEKLY, headers=auth_headers
    )
    assert again.status_code == 409, again.text
    listed = client.get("/cup-recurrences").json()
    assert listed[0]["id"] == made["id"]
    assert (listed[0]["next_on"], listed[0]["occurrence_count"]) == ("2030-01-04", 1)


def test_create_copies_the_latest_cup_onto_a_day_of_the_rule(
    client: Client, auth_headers: Headers
) -> None:
    cup, made = repeat(
        client, auth_headers, uses_divisions=True, entrant_cap=16, hide_seeds=True
    )

    response = occur(client, auth_headers, made["id"], "2030-01-11")

    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["name"] == "Friday Cup 11 Jan 2030"
    assert copy["starts_at"].startswith("2030-01-11T19:00")
    assert (copy["entrant_cap"], copy["hide_seeds"], copy["uses_divisions"]) == (
        16,
        True,
        True,
    )
    assert [(stage["format"], stage["best_of"]) for stage in copy["stages"]] == [
        (stage["format"], stage["best_of"]) for stage in cup["stages"]
    ]
    assert copy["cup_recurrence"]["id"] == made["id"]
    page = client.get(f"/cup-recurrences/{made['id']}").json()
    assert page["latest_event_id"] == copy["id"]
    assert page["upcoming"][1] == {"on": "2030-01-11", "event_id": copy["id"]}

    taken = occur(client, auth_headers, made["id"], "2030-01-11")
    assert taken.status_code == 409, taken.text
    saturday = occur(client, auth_headers, made["id"], "2030-01-12")
    assert saturday.status_code == 400, saturday.text


def test_a_cup_over_rounds_moves_its_rounds_with_it(
    client: Client, auth_headers: Headers
) -> None:
    legs = [
        {"starts_at": FRIDAY},
        {"starts_at": "2030-01-11T19:00:00Z", "name": "Finale"},
    ]
    _, made = repeat(client, auth_headers, legs=legs, points_by_place=[5, 3, 1])

    copy = occur(client, auth_headers, made["id"], "2030-02-01").json()

    assert [(leg["name"], leg["starts_at"][:16]) for leg in copy["cup_legs"]] == [
        ("Round 1", "2030-02-01T19:00"),
        ("Finale", "2030-02-08T19:00"),
    ]
    assert len(copy["stages"]) == 2
    overall = client.get(f"/events/{copy['id']}/overall").json()
    assert overall["points_by_place"] == [5, 3, 1]


def test_only_a_runner_of_the_latest_cup_makes_the_next(
    client: Client,
    auth_headers: Headers,
    member: Any,  # noqa: ANN401
) -> None:
    grant(client, auth_headers, "60")
    organizer = member("60")
    _, made = repeat(client, organizer, tag="Org")

    outsider = occur(client, member("61"), made["id"], "2030-01-11")
    assert outsider.status_code == 403, outsider.text

    copy = occur(client, organizer, made["id"], "2030-01-11")
    assert copy.status_code == 201, copy.text
    runners = client.get(f"/events/{copy.json()['id']}/organizers").json()
    assert [row["discord_id"] for row in runners] == ["60"]


def test_stopping_the_rule_keeps_its_cups(
    client: Client, auth_headers: Headers
) -> None:
    cup, made = repeat(client, auth_headers)
    copy = occur(client, auth_headers, made["id"], "2030-01-11").json()

    stopped = client.delete(f"/cup-recurrences/{made['id']}", headers=auth_headers)

    assert stopped.status_code == 204, stopped.text
    assert client.get(f"/cup-recurrences/{made['id']}").status_code == 404
    for event in (cup["id"], copy["id"]):
        read = client.get(f"/events/{event}")
        assert read.status_code == 200
        assert read.json()["cup_recurrence"] is None


def test_a_rule_changes_its_name_and_last_day(
    client: Client, auth_headers: Headers
) -> None:
    _, made = repeat(client, auth_headers)

    changed = client.put(
        f"/cup-recurrences/{made['id']}",
        json={"name": "Friday Fights", "ends_on": "2030-01-18"},
        headers=auth_headers,
    )

    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "Friday Fights"
    assert [row["on"] for row in changed.json()["upcoming"]] == [
        "2030-01-04",
        "2030-01-11",
        "2030-01-18",
    ]
    late = occur(client, auth_headers, made["id"], "2030-01-25")
    assert late.status_code == 400, late.text
