"""The fantasy scoring rules, as Python.

A fantasy team takes five parts, all of them from the season it names.

Its drafted players pay the points of every series they played that season, and
5 bench points for every week they stood in no series at all. Its drafted team
pays the standing it holds in that season. Its drafted race pays the weekly race
table: a race scores wins over losses, the three best ratios of the week take
18, 12 and 6, races that share a ratio share a rank, and the next rank advances
by the size of the group that tied. Its captain's bets pay their stake, plus
when the series went the way he called it and minus when it did not. The total
is the sum of the five.

Nothing here reads the database, so the read path and the score recalculation
answer the same numbers from the same rule.
"""

from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple

# Points the first three ranks of a week pay to a race
RACE_RANK_POINTS = {1: 18, 2: 12, 3: 6}
# Points a week without a series pays a drafted player
BENCH_POINTS = 5

# A race is an enum member on an ORM row, a string in a response model, None if unset
type RaceKey = str | None
type RacePoints = dict[RaceKey, int]
type RaceStats = dict[RaceKey, dict[str, Any]]
type RaceWeeklyDetails = dict[RaceKey, list[dict[str, Any]]]


def race_value(race: object) -> str | None:
    """The plain value ("HU"), which is also the frontend's icon id.
    str(member) would answer the repr ("Race.HU")."""
    value = getattr(race, "value", race)
    return value if value is None or isinstance(value, str) else str(value)


class Player(NamedTuple):
    """One side of a series, as the fantasy rules read him."""

    id: int | None
    name: str | None
    race: RaceKey


class Series(NamedTuple):
    """One series of a season, on the week its match was played."""

    week: int | None
    player1: Player
    player2: Player
    player1_score: int | None
    player2_score: int | None

    def winner(self) -> Player | None:
        """The side that took two maps, if the series is decided."""
        if self.player1_score == 2:
            return self.player1
        if self.player2_score == 2:
            return self.player2
        return None


class Bet(NamedTuple):
    """One bet a captain holds on a series. A bet reads no race."""

    id: int | None
    points: int | None
    winner_id: int | None
    winner_name: str | None
    series: Series


class Standing(NamedTuple):
    """What the drafted team stands at in the season of the fantasy team."""

    team_id: int | None
    team_name: str | None
    final_score: int
    points_against: int
    points_available: int


type SeriesByWeek = Mapping[int | None, Sequence[Series]]


def series_points(own: int, opp: int) -> int:
    """The points one played series pays the player who holds the own score."""
    if own == 2:
        if opp == 0:
            return 10
        elif opp == 1:
            return 8
        else:
            raise Exception(f"Invalid result score1: {own} - score2: {opp}")
    elif own == 1:
        if opp == 2:
            return 4
        else:
            raise Exception(f"Invalid result score1: {own} - score2: {opp}")
    else:
        return 0


# include_weekly_details also changes the return type
def race_points(
    number_weeks: int | None,
    series_by_week: SeriesByWeek,
    include_weekly_details: bool = False,
) -> RacePoints | tuple[RacePoints, RaceStats, RaceWeeklyDetails]:
    """
    Calculate race points for all races in a season.

    Args:
        number_weeks: The number of weeks the season is played over
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

    for week in range(1, (number_weeks or 0) + 1):
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
                    points_to_award = RACE_RANK_POINTS.get(current_rank, 0)
                    for prev_race in races_at_current_rank:
                        race_points[prev_race] = (
                            race_points.get(prev_race, 0) + points_to_award
                        )
                        # Add points to the weekly detail if tracking
                        if include_weekly_details:
                            for weekly_detail in race_weekly_details[prev_race]:
                                if weekly_detail["week"] == week:
                                    weekly_detail["points_awarded"] = points_to_award
                                    weekly_detail["rank"] = current_rank
                    current_rank += len(races_at_current_rank)
                    races_at_current_rank = []

                if current_rank > 3:
                    break

                races_at_current_rank.append(race)
                prev_ratio = ratio

            if races_at_current_rank and current_rank <= 3:
                points_to_award = RACE_RANK_POINTS.get(current_rank, 0)
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


def bet_result(
    bet_points: int | None, winner_id: int | None, series: Series
) -> int | None:
    """What a bet pays: its stake, plus when the caller named the winner of the
    series and minus when he did not. An undecided series pays nothing."""
    winner = series.winner()
    if winner is None or bet_points is None:
        return None
    return bet_points if winner_id == winner.id else -bet_points


def team_scores(
    drafted_players: Sequence[Player],
    drafted_race: RaceKey,
    standing: Standing | None,
    bets: Sequence[Bet],
    race_points: RacePoints,
    series_by_week: SeriesByWeek,
    number_weeks: int | None,
    include_breakdown: bool = False,
) -> dict[str, Any]:
    """
    Calculate all score components for a single fantasy team.

    Args:
        drafted_players: The players the team drafted
        drafted_race: The race the team drafted
        standing: What the drafted team stands at in the season, if it stands at all
        bets: The bets the captain holds in the season
        race_points: Pre-calculated race points dictionary
        series_by_week: The season's series keyed by week
        number_weeks: The number of weeks the season is played over
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
        # (bet id, points) per decided bet, so the caller does not evaluate again
        "bet_results": [],
    }

    if include_breakdown:
        result["player_breakdown"] = []
        result["bench_breakdown"] = []

    # Player and bench points
    for player in drafted_players:
        player_total = 0
        player_data = None

        if include_breakdown:
            player_data = {
                "player_id": player.id,
                "player_name": player.name,
                "weeks": [],
                "total": 0,
            }

        for week in range(1, (number_weeks or 0) + 1):
            week_player_series = [
                series
                for series in series_by_week.get(week, [])
                if player.id in (series.player1.id, series.player2.id)
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
                result["bench_points"] += BENCH_POINTS

                if include_breakdown:
                    week_data["bench_points"] = BENCH_POINTS
                    result["bench_breakdown"].append(
                        {
                            "player_name": player.name,
                            "week": week,
                            "reason": "No games played",
                            "points": BENCH_POINTS,
                        }
                    )
            else:
                for series in week_player_series:
                    if (
                        series.player1_score is not None
                        and series.player2_score is not None
                    ):
                        is_player1 = player.id == series.player1.id
                        player_score = (
                            series.player1_score if is_player1 else series.player2_score
                        )
                        opponent_score = (
                            series.player2_score if is_player1 else series.player1_score
                        )

                        points = series_points(player_score, opponent_score)
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

    # Team points. The standing is a sum of the series the drafted team played
    if standing is not None:
        result["team_points"] = standing.final_score

        if include_breakdown:
            result["team_breakdown"] = {
                "team_id": standing.team_id,
                "team_name": standing.team_name,
                "final_score": standing.final_score,
                "points_against": standing.points_against,
                "points_available": standing.points_available,
            }

    # Race points
    result["race_points"] = race_points.get(drafted_race, 0)

    # Bet points
    if include_breakdown:
        result["bet_breakdown"] = []

    for bet in bets:
        points = bet_result(bet.points, bet.winner_id, bet.series)
        if points is None:
            continue

        series_winner = bet.series.winner()
        won_bet = bet.winner_id == series_winner.id
        result["bet_points"] += points
        result["bet_results"].append((bet.id, points))

        if include_breakdown:
            result["bet_breakdown"].append(
                {
                    "week": bet.series.week,
                    "series": f"{bet.series.player1.name} vs {bet.series.player2.name}",
                    "bet_on": bet.winner_name,
                    "actual_winner": series_winner.name,
                    "bet_points": bet.points,
                    "result": points,
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
