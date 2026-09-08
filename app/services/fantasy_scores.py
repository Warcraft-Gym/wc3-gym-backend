"""The detailed score breakdown of one fantasy team.

The list answer builds its scores in app.services.derived; this builds the
same scores for one team, with the per-part breakdown the page reads.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session as OrmSession

from app.core import fantasy
from app.core.db import Session
from app.core.query import QueryUtil
from app.models.team import Team
from app.services import derived
from app.services.fantasy_bets import FantasyBetService
from app.services.fantasy_teams import FantasyTeamService
from app.services.ladder import team_achievement_points

if TYPE_CHECKING:
    from app.models.fantasy_team import FantasyTeamPublic
    from app.models.season import SeasonPublic


def _drafted_standing(
    fantasy_team: "FantasyTeamPublic", season: "SeasonPublic"
) -> fantasy.Standing | None:
    """What the drafted team stands at in the season, off its derived
    seasons_info row. The list answer carries no team name; this one does."""
    drafted_team = fantasy_team.drafted_team
    if not drafted_team or not drafted_team.seasons_info:
        return None
    for season_info in drafted_team.seasons_info:
        if season_info.season_id == season.id:
            return fantasy.Standing(
                team_id=drafted_team.id,
                team_name=drafted_team.name,
                final_score=season_info.final_score or 0,
                points_against=season_info.points_against or 0,
                points_available=season_info.points_available or 0,
            )
    return None


def _grind(
    session: OrmSession, fantasy_team: "FantasyTeamPublic", season: "SeasonPublic"
) -> fantasy.Grind | None:
    """The grind pick of the fantasy team, with the name of the team it picked.

    A season that offers no pick, or a team without one, grinds nothing.
    """
    team_id = fantasy_team.grind_team_id
    if team_id is None or not season.fantasy_grind:
        return None
    by_team = team_achievement_points(session, season.id)
    rank, points = fantasy.grind_points(by_team, team_id)
    name = session.get(Team, team_id)
    return fantasy.Grind(
        team_id,
        name.name if name else None,
        by_team.get(team_id, 0),
        rank,
        len(by_team),
        points,
    )


def team_score_breakdown(
    fantasy_team_service: FantasyTeamService,
    fantasy_bet_service: FantasyBetService,
    fantasy_team_id: int,
    season: "SeasonPublic",
) -> dict[str, Any]:
    """How a fantasy team's score was calculated, component by component."""
    # get raises NotFoundError for an unknown id.
    fantasy_team = fantasy_team_service.get(fantasy_team_id)

    with Session.begin() as session:
        series_by_week = derived.fantasy_series(session, {season.id}).get(season.id, {})
        grind = _grind(session, fantasy_team, season)
    race_points, race_stats, race_weekly_details = fantasy.race_points(
        season.number_rounds, series_by_week, True
    )

    query = QueryUtil.parse_query(
        f"user_id=={fantasy_team.captain_id} and season_id=={season.id}"
    )
    player_bets, _ = fantasy_bet_service.search(query)
    scores = fantasy.team_scores(
        drafted_players=[
            fantasy.Player(player.id, player.name, fantasy.race_value(player.race))
            for player in fantasy_team.drafted_players
        ],
        drafted_race=fantasy.race_value(fantasy_team.drafted_race),
        standing=_drafted_standing(fantasy_team, season),
        bets=[
            scored
            for bet in player_bets or []
            if (scored := derived.public_bet(bet)) is not None
        ],
        race_points=race_points,
        series_by_week=series_by_week,
        number_rounds=season.number_rounds,
        grind=grind,
        include_breakdown=True,
    )

    drafted_race = fantasy_team.drafted_race
    race_total_points = race_points.get(drafted_race, 0)
    drafted_race_weekly = race_weekly_details.get(drafted_race, [])
    for detail in drafted_race_weekly:
        if "points_awarded" not in detail:
            detail["points_awarded"] = 0
            detail["rank"] = None

    return {
        "team_id": fantasy_team_id,
        "team_name": fantasy_team.name,
        "season_id": season.id,
        "season_name": season.name,
        "player_breakdown": scores["player_breakdown"],
        "bench_breakdown": scores["bench_breakdown"],
        "team_breakdown": scores.get("team_breakdown", {}),
        "race_breakdown": {
            "race": fantasy.race_value(drafted_race),
            "total_points": race_total_points,
            "season_stats": race_stats.get(drafted_race, {"wins": 0, "losses": 0}),
            "weekly_breakdown": drafted_race_weekly,
            # JSON keys are strings, and the page matches them against race_breakdown.race
            "all_race_points": {
                fantasy.race_value(race): points for race, points in race_points.items()
            },
        },
        "bet_breakdown": scores["bet_breakdown"],
        "grind_breakdown": scores["grind_breakdown"],
        "totals": {
            "player_points": scores["player_points"],
            "bench_points": scores["bench_points"],
            "team_points": scores["team_points"],
            "race_points": race_total_points,
            "bet_points": scores["bet_points"],
            "grind_points": scores["grind_points"],
            "total_points": scores["total_points"],
        },
    }
