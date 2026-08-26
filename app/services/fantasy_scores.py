from typing import TYPE_CHECKING, Any

from app.core import fantasy
from app.core.query import QueryUtil
from app.services import derived
from app.services.fantasy_bets import FantasyBetService
from app.services.fantasy_teams import FantasyTeamService
from app.services.series import SeriesService

if TYPE_CHECKING:
    from app.models.fantasy_team import FantasyTeamPublic
    from app.models.season import SeasonPublic


class FantasyScoreService:
    def __init__(
        self,
        fantasy_team_service: FantasyTeamService,
        fantasy_bet_service: FantasyBetService,
        series_app_service: SeriesService,
    ) -> None:
        self.fantasy_team_service = fantasy_team_service
        self.fantasy_bet_service = fantasy_bet_service
        self.series_app_service = series_app_service

    def _season_series_by_week(
        self, season: "SeasonPublic"
    ) -> dict[int | None, list[fantasy.Series]]:
        """All series of the season, keyed by the week their match was played."""
        return self.series_app_service.fantasy_series_by_week(season.id)

    # include_weekly_details also changes the return type
    def _calculate_race_points(
        self,
        season: "SeasonPublic",
        series_by_week: dict[int | None, list[fantasy.Series]],
        include_weekly_details: bool = False,
    ) -> (
        fantasy.RacePoints
        | tuple[fantasy.RacePoints, fantasy.RaceStats, fantasy.RaceWeeklyDetails]
    ):
        """The points every race takes off the weekly race table of the season."""
        return fantasy.race_points(
            season.number_weeks, series_by_week, include_weekly_details
        )

    def _drafted_standing(
        self, fantasy_team: "FantasyTeamPublic", season: "SeasonPublic"
    ) -> fantasy.Standing | None:
        """What the drafted team stands at in the season, off its derived
        seasons_info row."""
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

    def _calculate_fantasy_team_scores(
        self,
        fantasy_team: "FantasyTeamPublic",
        season: "SeasonPublic",
        race_points: fantasy.RacePoints,
        series_by_week: dict[int | None, list[fantasy.Series]],
        include_breakdown: bool = False,
    ) -> dict[str, Any]:
        """The five score parts of one fantasy team, over the bets its captain
        holds in the season."""
        query = QueryUtil.parse_query(
            f"user_id=={fantasy_team.captain.id} and season_id=={season.id}"
        )
        player_bets, _ = self.fantasy_bet_service.search(query)

        return fantasy.team_scores(
            drafted_players=[
                fantasy.Player(player.id, player.name, fantasy.race_value(player.race))
                for player in fantasy_team.drafted_players
            ],
            drafted_race=fantasy.race_value(fantasy_team.drafted_race),
            standing=self._drafted_standing(fantasy_team, season),
            bets=[derived.public_bet(bet) for bet in player_bets or []],
            race_points=race_points,
            series_by_week=series_by_week,
            number_weeks=season.number_weeks,
            include_breakdown=include_breakdown,
        )

    def get_team_score_breakdown(
        self, fantasy_team_id: int, season: "SeasonPublic"
    ) -> dict[str, Any]:
        """
        Get detailed breakdown of how a fantasy team's score was calculated
        Returns a dictionary with all components and their calculations
        """
        # get raises NotFoundError for an unknown id.
        fantasy_team = self.fantasy_team_service.get(fantasy_team_id)

        breakdown = {
            "team_id": fantasy_team_id,
            "team_name": fantasy_team.name,
            "season_id": season.id,
            "season_name": season.name,
            "player_breakdown": [],
            "bench_breakdown": [],
            "team_breakdown": {},
            "race_breakdown": {},
            "bet_breakdown": [],
            "totals": {
                "player_points": 0,
                "bench_points": 0,
                "team_points": 0,
                "race_points": 0,
                "bet_points": 0,
                "total_points": 0,
            },
        }

        # Calculate race points for all races using shared method
        series_by_week = self._season_series_by_week(season)
        race_points, race_stats, race_weekly_details = self._calculate_race_points(
            season, series_by_week, include_weekly_details=True
        )

        # Calculate all score components using shared method
        scores = self._calculate_fantasy_team_scores(
            fantasy_team, season, race_points, series_by_week, include_breakdown=True
        )

        # Merge scores into breakdown structure
        breakdown["player_breakdown"] = scores["player_breakdown"]
        breakdown["bench_breakdown"] = scores["bench_breakdown"]
        breakdown["team_breakdown"] = scores.get("team_breakdown", {})
        breakdown["bet_breakdown"] = scores["bet_breakdown"]
        breakdown["totals"]["player_points"] = scores["player_points"]
        breakdown["totals"]["bench_points"] = scores["bench_points"]
        breakdown["totals"]["team_points"] = scores["team_points"]
        breakdown["totals"]["bet_points"] = scores["bet_points"]

        # Race points breakdown
        drafted_race = fantasy_team.drafted_race
        race_total_points = race_points.get(drafted_race, 0)

        # JSON keys are strings, and the page matches them against race_breakdown.race
        race_points_str = {
            fantasy.race_value(race): points for race, points in race_points.items()
        }

        # Get weekly details for the drafted race (with points_awarded defaulting to 0)
        drafted_race_weekly = race_weekly_details.get(drafted_race, [])
        for detail in drafted_race_weekly:
            if "points_awarded" not in detail:
                detail["points_awarded"] = 0
                detail["rank"] = None

        breakdown["race_breakdown"] = {
            "race": fantasy.race_value(drafted_race),
            "total_points": race_total_points,
            "season_stats": race_stats.get(drafted_race, {"wins": 0, "losses": 0}),
            "weekly_breakdown": drafted_race_weekly,
            "all_race_points": race_points_str,  # Include all races for context
        }
        breakdown["totals"]["race_points"] = race_total_points

        # Calculate total
        breakdown["totals"]["total_points"] = scores["total_points"]

        return breakdown
