from app.service.fantasy_bet_service import FantasyBetAppService
from app.service.fantasy_team_service import FantasyTeamAppService
from app.service.series_service import SeriesAppService
from app.service.team_service import TeamAppService
from app.util.query_util import QueryUtil


class FantasyScoreAppService:
    def __init__(
        self,
        fantasy_team_service: FantasyTeamAppService,
        fantasy_bet_service: FantasyBetAppService,
        series_app_service: SeriesAppService,
        team_app_service: TeamAppService,
    ):
        self.fantasy_team_service = fantasy_team_service
        self.fantasy_bet_service = fantasy_bet_service
        self.series_app_service = series_app_service
        self.team_app_service = team_app_service

    def _calculate_race_points(self, season, include_weekly_details=False):
        """
        Calculate race points for all races in a season.

        Args:
            season: The season to calculate points for
            include_weekly_details: If True, includes weekly breakdown and overall stats

        Returns:
            tuple: (race_points, race_stats, race_weekly_details) if include_weekly_details=True
                   (race_points,) if include_weekly_details=False
        """
        race_points = {}
        race_stats = {} if include_weekly_details else None
        race_weekly_details = {} if include_weekly_details else None

        for week in range(1, season.number_weeks + 1):
            season_week_series = self.series_app_service.searchForSeasonAndPlayday(
                season.id, week, None
            )
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
        self, fantasy_team, season, race_points, include_breakdown=False
    ):
        """
        Calculate all score components for a single fantasy team.

        Args:
            fantasy_team: The fantasy team to calculate scores for
            season: The season to calculate scores for
            race_points: Pre-calculated race points dictionary
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
                    series_q_string = (
                        f"player1_id=={player.id} or player2_id=={player.id}"
                    )
                    series_query = QueryUtil.parseQuery(series_q_string)
                    week_player_series = (
                        self.series_app_service.searchForSeasonAndPlayday(
                            season.id, week, series_query
                        )
                    )

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

    def calculateTeamScores(self, season):
        # Calculate race points using shared method
        race_points = self._calculate_race_points(season, include_weekly_details=False)

        fteams = self.fantasy_team_service.getAll_fantasy_teams()
        if fteams:
            for fteam in fteams:
                # Use shared calculation method
                scores = self._calculate_fantasy_team_scores(
                    fteam, season, race_points, include_breakdown=False
                )

                # Update bet results in database
                series_q_string = (
                    f"user_id=={fteam.captain.id} and season_id=={season.id}"
                )
                series_query = QueryUtil.parseQuery(series_q_string)
                player_bets = self.fantasy_bet_service.search_fantasy_bets(series_query)
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
                        bet.bet_result = bet_result
                        self.fantasy_bet_service.update_fantasy_bet(bet.id, bet)

                # Update team with calculated scores
                fteam.player_points = scores["player_points"]
                fteam.bench_points = scores["bench_points"]
                fteam.team_points = scores["team_points"]
                fteam.race_points = scores["race_points"]
                fteam.bet_points = scores["bet_points"]
                fteam.total_points = scores["total_points"]
                fteam = self.fantasy_team_service.update_fantasy_team(fteam.id, fteam)

    def getTeamScoreBreakdown(self, fantasy_team_id, season):
        """
        Get detailed breakdown of how a fantasy team's score was calculated
        Returns a dictionary with all components and their calculations
        """
        fantasy_team = self.fantasy_team_service.get_fantasy_team(fantasy_team_id)
        if not fantasy_team:
            raise Exception(f"Fantasy team with id {fantasy_team_id} not found")

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
        race_points, race_stats, race_weekly_details = self._calculate_race_points(
            season, include_weekly_details=True
        )

        # Calculate all score components using shared method
        scores = self._calculate_fantasy_team_scores(
            fantasy_team, season, race_points, include_breakdown=True
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

        # Convert Race enum keys to strings for JSON serialization
        race_points_str = {str(race): points for race, points in race_points.items()}

        # Get weekly details for the drafted race (with points_awarded defaulting to 0)
        drafted_race_weekly = race_weekly_details.get(drafted_race, [])
        for detail in drafted_race_weekly:
            if "points_awarded" not in detail:
                detail["points_awarded"] = 0
                detail["rank"] = None

        breakdown["race_breakdown"] = {
            "race": str(drafted_race),
            "total_points": race_total_points,
            "season_stats": race_stats.get(drafted_race, {"wins": 0, "losses": 0}),
            "weekly_breakdown": drafted_race_weekly,
            "all_race_points": race_points_str,  # Include all races for context
        }
        breakdown["totals"]["race_points"] = race_total_points

        # Calculate total
        breakdown["totals"]["total_points"] = scores["total_points"]

        return breakdown

    def calculatePoints(self, score1, score2):
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
