"""An entity inside another object is its summary shape.

The test walks every schema a route answers with, as /openapi.json names it,
and fails where a property embeds a shape of a registered entity other than
its summary, or where a summary holds a list of entities. docs/okf/api/
response-shapes.md states the rule.
"""

from typing import Any

from httpx2 import Client
from pydantic import BaseModel

from app.models.fantasy_bet import FantasyBetPublic
from app.models.fantasy_team import FantasyTeamPublic
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

# Entities with no summary: they answer at the top level only, never embedded
TOP_LEVEL_ONLY = (FantasyTeamPublic, FantasyBetPublic)

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
