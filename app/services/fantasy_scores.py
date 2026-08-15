from typing import TYPE_CHECKING, Any

from app.models.enums import Race
from app.models.fantasy_bet import FantasyBetUpdate
from app.models.fantasy_team import FantasyTeamUpdate
from app.services.fantasy_bets import FantasyBetService
from app.services.fantasy_teams import FantasyTeamService
from app.services.series import SeriesService
from app.services.teams import TeamService
from app.utils.query_util import QueryUtil

if TYPE_CHECKING:
    from app.models.fantasy_team import FantasyTeamPublic
    from app.models.season import SeasonPublic
    from app.models.series import SeriesPublic

# The response models render a race as its plain value, so a race read
# off a player or a fantasy team is a string. A race read off an ORM row
# is the member, and a player without one is None, so a key is any of the
# three and race_value writes all three the same way.
type RaceKey = Race | str | None
type RacePoints = dict[RaceKey, int]
type RaceStats = dict[RaceKey, dict[str, Any]]
type RaceWeeklyDetails = dict[RaceKey, list[dict[str, Any]]]


def _race_value(race: RaceKey) -> str | None:
    """The plain value ("HU"), which is also the frontend's icon id.
    str(member) would answer the repr ("Race.HU")."""
    if isinstance(race, Race):
        return race.value
    return race


class FantasyScoreService:
    def __init__(
        self,
        fantasy_team_service: FantasyTeamService,
        fantasy_bet_service: FantasyBetService,
        series_app_service: SeriesService,
        team_app_service: TeamService,
    ) -> None:
        self.fantasy_team_service = fantasy_team_service
        self.fantasy_bet_service = fantasy_bet_service
        self.series_app_service = series_app_service
        self.team_app_service = team_app_service

    def _season_series_by_week(
        self, season: "SeasonPublic"
    ) -> dict[int, list["SeriesPublic"]]:
        """All series of the season, one query per week."""
        return {
            week: self.series_app_service.searchForSeasonAndPlayday(
                season.id, week, None
            )
            or []
            for week in range(1, season.number_weeks + 1)
        }

    # The flag also changes the result: the totals alone, or the totals
    # with the per-week detail beside them.
    def _calculate_race_points(
        self,
        season: "SeasonPublic",
        series_by_week: dict[int, list["SeriesPublic"]],
        include_weekly_details: bool = False,
    ) -> RacePoints | tuple[RacePoints, RaceStats, RaceWeeklyDetails]:
        """
        Calculate race points for all races in a season.

        Args:
            season: The season to calculate points for
            series_by_week: The season's series keyed by week
            include_weekly_details: If True, includes weekly breakdown and overall stats

        Returns:
            tuple: (race_points, race_stats, race_weekly_details) if include_weekly_details=True
                   (race_points,) if include_weekly_details=False
        """
        race_points: RacePoints = {}
        race_stats: RaceStats | None = {} if include_weekly_details else None
        race_weekly_details: RaceWeeklyDetails | None = (
            {} if include_weekly_details else None
        )

        for week in range(1, season.number_weeks + 1):
            season_week_series = series_by_week.get(week, [])
            week_race_wins = {}
            week_race_looses = {}

            for series in season_week_series:
                if series.player1_score == 2:
                    week_race_wins[series.player1.race] = (
                        week_race_wins.get(series.player1.race, 0) + 1
                    )
                    week_race_looses[series.player2.race] = (
                        week_race_looses.get(series.player2.race, 0) + 1
                    )
                elif series.player2_score == 2:
                    week_race_wins[series.player2.race] = (
                        week_race_wins.get(series.player2.race, 0) + 1
                    )
                    week_race_looses[series.player1.race] = (
                        week_race_looses.get(series.player1.race, 0) + 1
                    )

            week_result = {}
            all_races = set(list(week_race_wins.keys()) + list(week_race_looses.keys()))

            for race in all_races:
                wins = week_race_wins.get(race, 0)
                losses = week_race_looses.get(race, 0)

                # Track overall stats if requested
                if include_weekly_details:
                    if race not in race_stats:
                        race_stats[race] = {"wins": 0, "losses": 0}
                    race_stats[race]["wins"] += wins
                    race_stats[race]["losses"] += losses

                if wins == 0:
                    week_percentage = 0
                elif losses == 0:
                    week_percentage = 100
                else:
                    week_percentage = wins / losses
                week_result[race] = week_percentage

                # Store weekly details if requested
                if include_weekly_details:
                    if race not in race_weekly_details:
                        race_weekly_details[race] = []
                    race_weekly_details[race].append(
                        {
                            "week": week,
                            "wins": wins,
                            "losses": losses,
                            "ratio": week_percentage,
                        }
                    )

            # Award points for this week
            has_played_games = any(ratio > 0 for ratio in week_result.values())
            if has_played_games:
                points_map = {1: 18, 2: 12, 3: 6}
                sorted_races = sorted(
                    week_result.items(),
                    key=lambda item: (item[1], str(item[0])),
                    reverse=True,
                )

                current_rank = 1
                prev_ratio = None
                races_at_current_rank = []

                for race, ratio in sorted_races:
                    if ratio == 0:
                        continue

                    if prev_ratio is not None and ratio != prev_ratio:
                        points_to_award = points_map.get(current_rank, 0)
                        for prev_race in races_at_current_rank:
                            race_points[prev_race] = (
                                race_points.get(prev_race, 0) + points_to_award
                            )
                            # Add points to the weekly detail if tracking
                            if include_weekly_details:
                                for weekly_detail in race_weekly_details[prev_race]:
                                    if weekly_detail["week"] == week:
                                        weekly_detail["points_awarded"] = (
                                            points_to_award
                                        )
                                        weekly_detail["rank"] = current_rank
                        current_rank += len(races_at_current_rank)
                        races_at_current_rank = []

                    if current_rank > 3:
                        break

                    races_at_current_rank.append(race)
                    prev_ratio = ratio

                if races_at_current_rank and current_rank <= 3:
                    points_to_award = points_map.get(current_rank, 0)
                    for race in races_at_current_rank:
                        race_points[race] = race_points.get(race, 0) + points_to_award
                        # Add points to the weekly detail if tracking
                        if include_weekly_details:
                            for weekly_detail in race_weekly_details[race]:
                                if weekly_detail["week"] == week:
                                    weekly_detail["points_awarded"] = points_to_award
                                    weekly_detail["rank"] = current_rank

        if include_weekly_details:
            return race_points, race_stats, race_weekly_details
        return race_points

    def _calculate_fantasy_team_scores(
        self,
        fantasy_team: "FantasyTeamPublic",
        season: "SeasonPublic",
        race_points: RacePoints,
        series_by_week: dict[int, list["SeriesPublic"]],
        include_breakdown: bool = False,
    ) -> dict[str, Any]:
        """
        Calculate all score components for a single fantasy team.

        Args:
            fantasy_team: The fantasy team to calculate scores for
            season: The season to calculate scores for
            race_points: Pre-calculated race points dictionary
            series_by_week: The season's series keyed by week
            include_breakdown: If True, returns detailed breakdown; if False, returns just totals

        Returns:
            dict: Score totals and optional breakdown details
        """
        result = {
            "player_points": 0,
            "bench_points": 0,
            "team_points": 0,
            "race_points": 0,
            "bet_points": 0,
            "total_points": 0,
            # (bet id, points won or lost) per decided bet, so the caller
            # can store the results without evaluating the bets again.
            "bet_results": [],
        }

        if include_breakdown:
            result["player_breakdown"] = []
            result["bench_breakdown"] = []

        # Player and bench points
        players = fantasy_team.drafted_players
        if players:
            for player in players:
                player_total = 0
                player_data = None

                if include_breakdown:
                    player_data = {
                        "player_id": player.id,
                        "player_name": player.name,
                        "weeks": [],
                        "total": 0,
                    }

                for week in range(1, season.number_weeks + 1):
                    week_player_series = [
                        series
                        for series in series_by_week.get(week, [])
                        if player.id in (series.player1_id, series.player2_id)
                    ]

                    week_points = 0
                    week_data = None

                    if include_breakdown:
                        week_data = {
                            "week": week,
                            "series": [],
                            "points": 0,
                            "bench_points": 0,
                        }

                    if not week_player_series:
                        result["bench_points"] += 5

                        if include_breakdown:
                            week_data["bench_points"] = 5
                            result["bench_breakdown"].append(
                                {
                                    "player_name": player.name,
                                    "week": week,
                                    "reason": "No games played",
                                    "points": 5,
                                }
                            )
                    else:
                        for series in week_player_series:
                            if (
                                series.player1_score is not None
                                and series.player2_score is not None
                            ):
                                is_player1 = player.id == series.player1_id
                                player_score = (
                                    series.player1_score
                                    if is_player1
                                    else series.player2_score
                                )
                                opponent_score = (
                                    series.player2_score
                                    if is_player1
                                    else series.player1_score
                                )

                                points = self.calculatePoints(
                                    player_score, opponent_score
                                )
                                week_points += points

                                if include_breakdown:
                                    opponent_name = (
                                        series.player2.name
                                        if is_player1
                                        else series.player1.name
                                    )
                                    week_data["series"].append(
                                        {
                                            "opponent": opponent_name,
                                            "score": f"{player_score}-{opponent_score}",
                                            "points": points,
                                        }
                                    )

                    player_total += week_points

                    if include_breakdown:
                        week_data["points"] = week_points
                        player_data["weeks"].append(week_data)

                result["player_points"] += player_total

                if include_breakdown:
                    player_data["total"] = player_total
                    result["player_breakdown"].append(player_data)

        # Team points
        drafted_team = fantasy_team.drafted_team
        if drafted_team and drafted_team.seasons_info:
            for season_info in drafted_team.seasons_info:
                if season_info.season_id == season.id:
                    result["team_points"] = season_info.final_score or 0

                    if include_breakdown:
                        result["team_breakdown"] = {
                            "team_id": drafted_team.id,
                            "team_name": drafted_team.name,
                            "final_score": season_info.final_score or 0,
                            "points_against": season_info.points_against or 0,
                            "points_available": season_info.points_available or 0,
                        }

        # Race points
        result["race_points"] = race_points.get(fantasy_team.drafted_race, 0)

        # Bet points
        series_q_string = (
            f"user_id=={fantasy_team.captain.id} and season_id=={season.id}"
        )
        series_query = QueryUtil.parseQuery(series_q_string)
        player_bets = self.fantasy_bet_service.search_fantasy_bets(series_query)

        if include_breakdown:
            result["bet_breakdown"] = []

        if player_bets:
            for bet in player_bets:
                series_winner = None
                if bet.series.player1_score == 2:
                    series_winner = bet.series.player1
                elif bet.series.player2_score == 2:
                    series_winner = bet.series.player2
                else:
                    continue

                won_bet = bet.winner.id == series_winner.id
                bet_result = bet.bet_points if won_bet else -bet.bet_points
                result["bet_points"] += bet_result
                result["bet_results"].append((bet.id, bet_result))

                if include_breakdown:
                    result["bet_breakdown"].append(
                        {
                            "week": bet.series.match.playday,
                            "series": f"{bet.series.player1.name} vs {bet.series.player2.name}",
                            "bet_on": bet.winner.name,
                            "actual_winner": series_winner.name,
                            "bet_points": bet.bet_points,
                            "result": bet_result,
                            "won": won_bet,
                        }
                    )

        # Calculate total
        result["total_points"] = (
            result["player_points"]
            + result["bench_points"]
            + result["team_points"]
            + result["race_points"]
            + result["bet_points"]
        )

        return result

    def calculateTeamScores(self, season: "SeasonPublic") -> None:
        series_by_week = self._season_series_by_week(season)
        race_points = self._calculate_race_points(
            season, series_by_week, include_weekly_details=False
        )

        fteams = self.fantasy_team_service.getAll_fantasy_teams()
        if fteams:
            for fteam in fteams:
                scores = self._calculate_fantasy_team_scores(
                    fteam, season, race_points, series_by_week, include_breakdown=False
                )

                # Store through the Update models. The bet update skips
                # bet-points validation on purpose: it writes a result,
                # it does not place a bet.
                for bet_id, bet_result in scores["bet_results"]:
                    self.fantasy_bet_service.update(
                        bet_id, FantasyBetUpdate(bet_result=bet_result)
                    )

                self.fantasy_team_service.update(
                    fteam.id,
                    FantasyTeamUpdate(
                        player_points=scores["player_points"],
                        bench_points=scores["bench_points"],
                        team_points=scores["team_points"],
                        race_points=scores["race_points"],
                        bet_points=scores["bet_points"],
                        total_points=scores["total_points"],
                    ),
                )

    def getTeamScoreBreakdown(
        self, fantasy_team_id: int, season: "SeasonPublic"
    ) -> dict[str, Any]:
        """
        Get detailed breakdown of how a fantasy team's score was calculated
        Returns a dictionary with all components and their calculations
        """
        # get_fantasy_team raises NotFoundError for an unknown id.
        fantasy_team = self.fantasy_team_service.get_fantasy_team(fantasy_team_id)

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

        # JSON keys are strings, and the page matches them against the
        # value in race_breakdown.race, so both are written the same way.
        race_points_str = {
            _race_value(race): points for race, points in race_points.items()
        }

        # Get weekly details for the drafted race (with points_awarded defaulting to 0)
        drafted_race_weekly = race_weekly_details.get(drafted_race, [])
        for detail in drafted_race_weekly:
            if "points_awarded" not in detail:
                detail["points_awarded"] = 0
                detail["rank"] = None

        breakdown["race_breakdown"] = {
            "race": _race_value(drafted_race),
            "total_points": race_total_points,
            "season_stats": race_stats.get(drafted_race, {"wins": 0, "losses": 0}),
            "weekly_breakdown": drafted_race_weekly,
            "all_race_points": race_points_str,  # Include all races for context
        }
        breakdown["totals"]["race_points"] = race_total_points

        # Calculate total
        breakdown["totals"]["total_points"] = scores["total_points"]

        return breakdown

    def calculatePoints(self, score1: int, score2: int) -> int:
        if score1 == 2:
            if score2 == 0:
                return 10
            elif score2 == 1:
                return 8
            else:
                raise Exception(f"Invalid result score1: {score1} - score2: {score2}")
        elif score1 == 1:
            if score2 == 2:
                return 4
            else:
                raise Exception(f"Invalid result score1: {score1} - score2: {score2}")
        else:
            return 0
