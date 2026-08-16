"""The response schema of the fantasy score breakdown.

The score service builds the breakdown as a dict; this schema documents
it and serializes the response. The field order matches the order the
service writes the keys, so the JSON stays as it was.
"""

from typing import Any

from sqlmodel import SQLModel


class FantasyScoreSeries(SQLModel):
    opponent: str | None
    score: str
    points: int


class FantasyScoreWeek(SQLModel):
    week: int
    series: list[FantasyScoreSeries]
    points: int
    bench_points: int


class FantasyPlayerBreakdown(SQLModel):
    player_id: int | None
    player_name: str | None
    weeks: list[FantasyScoreWeek]
    total: int


class FantasyBenchAward(SQLModel):
    player_name: str | None
    week: int
    reason: str
    points: int


class FantasyRaceWeek(SQLModel):
    week: int
    wins: int
    losses: int
    # A played week answers wins/losses as a float; 0 and 100 stay int.
    ratio: int | float
    points_awarded: int
    rank: int | None


class FantasyRaceBreakdown(SQLModel):
    race: str
    total_points: int
    season_stats: dict[str, int]
    weekly_breakdown: list[FantasyRaceWeek]
    all_race_points: dict[str, int]


class FantasyBetOutcome(SQLModel):
    week: int | None
    series: str
    bet_on: str | None
    actual_winner: str | None
    bet_points: int
    result: int
    won: bool


class FantasyScoreTotals(SQLModel):
    player_points: int
    bench_points: int
    team_points: int
    race_points: int
    bet_points: int
    total_points: int


class FantasyTeamScoreBreakdown(SQLModel):
    team_id: int
    team_name: str | None
    season_id: int | None
    season_name: str | None
    player_breakdown: list[FantasyPlayerBreakdown]
    bench_breakdown: list[FantasyBenchAward]
    # An empty dict when the team drafted no GNL team
    team_breakdown: dict[str, Any]
    race_breakdown: FantasyRaceBreakdown
    bet_breakdown: list[FantasyBetOutcome]
    totals: FantasyScoreTotals
