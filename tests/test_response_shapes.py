"""An entity inside another object is its summary shape.

The test walks every schema a route answers with, as /openapi.json names it,
and fails where a property embeds a shape of a registered entity other than
its summary, where a summary holds a list of entities, or where a list route
answers a detail as its row. docs/okf/api/response-shapes.md states the rules.
"""

from typing import Any

from httpx2 import Client
from pydantic import BaseModel

from app.models.fantasy_bet import FantasyBetPublic
from app.models.fantasy_team import FantasyTeamPublic
from app.models.player_reads import UserProfileSummaryPublic
from app.models.season import Season, SeasonBase, SeasonSummaryPublic
from app.models.team import Team
from app.models.team_summary import TeamSummaryPublic
from app.models.user import User, UserReduced, UserSummaryPublic

# Each entity: the root every one of its response shapes extends, and its
# summary. The other shapes, TeamPublic and TeamRosterPublic among them, answer
# only at the top level.
EMBEDS: dict[type, tuple[type[BaseModel], type[BaseModel]]] = {
    User: (UserReduced, UserSummaryPublic),
    Team: (TeamSummaryPublic, TeamSummaryPublic),
    Season: (SeasonBase, SeasonSummaryPublic),
}

# Sites that still embed a detail shape, each with its reason
ALLOWED: dict[tuple[str, str], str] = {}

# Entities with no summary, and a player's own summary read: they answer at
# the top level only, never embedded
TOP_LEVEL_ONLY = (FantasyTeamPublic, FantasyBetPublic, UserProfileSummaryPublic)

# Schema names of entities, which a summary may not hold a list of
ENTITY_PREFIXES = (
    "User",
    "Team",
    "Season",
    "Event",
    "Series",
    "Match",
    "FantasyTeam",
    "FantasyBet",
    "DraftSeries",
    "League",
)
# Rows of values, not entities, though their names start like one
VALUE_ROWS = {"UserTeamSeasonStatsPublic", "UserBattleTagPublic"}


def _refs(node: Any, found: set[str]) -> set[str]:  # noqa: ANN401
    """Every schema name a piece of a schema points at."""
    if isinstance(node, dict):
        if "$ref" in node:
            found.add(node["$ref"].rsplit("/", 1)[-1])
        for value in node.values():
            _refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _refs(value, found)
    return found


def _listed(node: Any) -> set[str]:  # noqa: ANN401
    """Every schema name a piece of a schema holds a list of."""
    if isinstance(node, list):
        return set().union(*(_listed(value) for value in node))
    if not isinstance(node, dict):
        return set()
    found = _refs(node["items"], set()) if "items" in node else set()
    for key, value in node.items():
        if key != "items":
            found |= _listed(value)
    return found


def _family(root: type[BaseModel]) -> set[str]:
    """The names of the root and every class that extends it."""
    names = {root.__name__}
    for sub in root.__subclasses__():
        names |= _family(sub)
    return names


def _answered(spec: dict[str, Any]) -> set[str]:
    """Every schema a route answers with, and every schema those reach."""
    schemas = spec["components"]["schemas"]
    todo = {
        name
        for methods in spec["paths"].values()
        for operation in methods.values()
        for name in _refs(operation.get("responses", {}), set())
    }
    seen: set[str] = set()
    while todo:
        name = todo.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        todo |= _refs(schemas[name], set()) - seen
    return seen


def test_an_embedded_entity_is_its_summary(client: Client) -> None:
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    wrong = []
    for root, summary in EMBEDS.values():
        detail = _family(root) - {summary.__name__}
        for name in sorted(_answered(spec)):
            for prop, sub in (schemas[name].get("properties") or {}).items():
                embedded = _refs(sub, set()) & detail
                if embedded and (name, prop) not in ALLOWED:
                    wrong.append(f"{name}.{prop} embeds {sorted(embedded)}")
    assert wrong == []


def test_a_top_level_entity_is_never_embedded(client: Client) -> None:
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    names = {model.__name__ for model in TOP_LEVEL_ONLY}
    wrong = [
        f"{name}.{prop} embeds {sorted(embedded)}"
        for name in sorted(_answered(spec))
        for prop, sub in (schemas[name].get("properties") or {}).items()
        if (embedded := _refs(sub, set()) & names)
    ]
    assert wrong == []


def test_the_allowed_sites_exist(client: Client) -> None:
    """A renamed or removed site leaves the list, so it only ever shrinks."""
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    missing = [
        f"{name}.{prop}"
        for name, prop in ALLOWED
        if prop not in (schemas.get(name, {}).get("properties") or {})
    ]
    assert missing == []


def test_a_summary_holds_no_entity_list(client: Client) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    wrong = []
    for _, summary in EMBEDS.values():
        properties = schemas[summary.__name__]["properties"]
        for prop, sub in properties.items():
            listed = {
                name
                for name in _listed(sub)
                if name.startswith(ENTITY_PREFIXES) and name not in VALUE_ROWS
            }
            if listed:
                wrong.append(f"{summary.__name__}.{prop} lists {sorted(listed)}")
    assert wrong == []


# The detail shape of each entity, which a list route may not answer as its row
DETAILS = {
    "UserPublic",
    "UserMemberPublic",
    "TeamPublic",
    "TeamRosterPublic",
    "EventPublic",
    "SeriesPublic",
    "MatchPublic",
    "FantasyTeamPublic",
    "FantasyBetPublic",
}

# List routes that still answer a detail as their row, each with its reason
LIST_ROWS_ALLOWED: dict[str, str] = {
    "GET /events": "the list row is SeasonPublic in the table; the route answers the detail",
    "GET /events/{event_id}/fantasy/teams": "a fantasy team has one class for row and detail",
    "GET /fantasy/teams": "a fantasy team has one class for row and detail",
    "GET /fantasy/bets": "a fantasy bet has one class for row and detail",
    "GET /events/{event_id}/matches": "a match has no summary or list row yet",
    "GET /events/{event_id}/series": "the app reads the detail; the site moves to a list row",
    "GET /events/{event_id}/teams": "the app reads the detail; the site moves to a list row",
    "GET /events/{event_id}/teams/basic": "a team has one class for row and detail",
    "GET /leagues/{league_id}/teams": "a team has one class for row and detail",
    "GET /leagues/{league_id}/teams/basic": "a team has one class for row and detail",
}


def _list_rows(spec: dict[str, Any]) -> dict[str, str]:
    """The item schema of every GET route that answers a list, by route."""
    rows = {}
    for path, methods in spec["paths"].items():
        get = methods.get("get")
        if get is None:
            continue
        schema = (
            get.get("responses", {})
            .get("200", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema", {})
        )
        if schema.get("type") == "array" and "$ref" in schema.get("items", {}):
            rows[f"GET {path}"] = schema["items"]["$ref"].rsplit("/", 1)[-1]
    return rows


def test_a_list_route_answers_a_list_row(client: Client) -> None:
    """A list answers each entity's summary or a named list row, never its detail."""
    spec = client.get("/openapi.json").json()
    assert DETAILS <= set(spec["components"]["schemas"])
    wrong = [
        f"{route} answers {row}"
        for route, row in sorted(_list_rows(spec).items())
        if row in DETAILS and route not in LIST_ROWS_ALLOWED
    ]
    assert wrong == []


def test_the_allowed_list_rows_exist(client: Client) -> None:
    """An allowed route that moved to a list row leaves the list, so it only shrinks."""
    rows = _list_rows(client.get("/openapi.json").json())
    stale = [route for route in LIST_ROWS_ALLOWED if rows.get(route) not in DETAILS]
    assert stale == []
