import os

from app.models.match import MatchPublic, MatchUpdate
from app.models.season_info import SeasonInfoUpdate
from app.models.series import SeriesPublic, SeriesUpdate
from app.models.team import TeamPublic
from app.models.team_reduced import TeamReduced
from app.services.matches import MatchService
from app.services.seasons import SeasonService
from app.services.series import SeriesService
from app.services.settings import SettingsService
from app.services.team_seasons import TeamSeasonService
from app.services.teams import TeamService
from app.utils.query_util import QueryUtil


class ScoreService:
    STANDARD_MAX_SCORE = 3
    HELPSTONE_MAX_SCORE = 4

    def __init__(
        self,
        match_service: MatchService,
        serires_service: SeriesService,
        team_service: TeamService,
        team_season_service: TeamSeasonService,
        season_service: SeasonService,
        settings_service: SettingsService,
    ) -> None:
        self.match_service = match_service
        self.serires_service = serires_service
        self.team_service = team_service
        self.team_season_service = team_season_service
        self.season_service = season_service
        self.settings_service = settings_service

    def calculateSeriesScore(self, series: SeriesPublic) -> SeriesPublic:
        series.player1_points = self.getScoreByMapScore(
            series.player1_score, series.player2_score
        )
        series.player2_points = self.getScoreByMapScore(
            series.player2_score, series.player1_score
        )
        return series

    def updateMatchScore(self, matchId: int) -> MatchPublic:
        match = self.match_service.get(matchId)

        query = QueryUtil.parseQuery("match_id == " + str(matchId))

        series_list = self.serires_service.search(query)

        team1_score = 0
        team2_score = 0

        for single_series in series_list:
            if (
                single_series.player1_score is not None
                and single_series.player2_score is not None
            ) and (
                single_series.player1_points is None
                or single_series.player2_points is None
            ):
                single_series = self.calculateSeriesScore(single_series)
                self.serires_service.update(
                    single_series.id,
                    SeriesUpdate(
                        player1_points=single_series.player1_points,
                        player2_points=single_series.player2_points,
                    ),
                )

            if single_series.player1_points is not None:
                team1_score += single_series.player1_points
            if single_series.player2_points is not None:
                team2_score += single_series.player2_points

        match_data = self.match_service.update(
            matchId,
            MatchUpdate(team1_score=team1_score, team2_score=team2_score),
        )

        match_data.team1 = self.updateTeamScore(match.team1, match.season_id)
        match_data.team2 = self.updateTeamScore(match.team2, match.season_id)

        return match_data

    def updateTeamScore(
        self, team: TeamPublic | TeamReduced, seasonId: int
    ) -> TeamPublic | TeamReduced:
        # A match carries reduced team objects without seasons_info;
        # fetch the full team data in that case
        if not getattr(team, "seasons_info", None):
            team = self.team_service.get(team.id)

        # If still no seasons_info, we can't update the team score
        if team.seasons_info is None or len(team.seasons_info) == 0:
            return team

        team_points = 0
        team_against = 0

        query = QueryUtil.parseQuery(
            f"season_id == {seasonId} and team1_id == {team.id} or season_id == {seasonId} and team2_id == {team.id}"
        )
        matches = self.match_service.search(query)

        for match in matches:
            if match.team1_id == team.id:
                if match.team1_score is not None:
                    team_points += match.team1_score
                if match.team2_score is not None:
                    team_against += match.team2_score
            elif match.team2_id == team.id:
                if match.team2_score is not None:
                    team_points += match.team2_score
                if match.team1_score is not None:
                    team_against += match.team1_score
            else:
                raise Exception("Cannot calculate Teamscore invalid match!")

        season_key = None

        for i in range(len(team.seasons_info)):
            if team.seasons_info[i].season_id == seasonId:
                season_key = i

        if season_key is None:
            return team

        team.seasons_info[season_key].final_score = team_points
        team.seasons_info[season_key].points_against = team_against

        # Fetch season directly to get series_per_week and number_weeks
        season = self.season_service.get(seasonId)
        if (
            season is not None
            and season.series_per_week is not None
            and season.number_weeks is not None
        ):
            max_available = (
                season.series_per_week
                * season.number_weeks
                * self.getMaxPointsPerSeries()
            )
            team.seasons_info[season_key].points_available = (
                max_available - team_points - team_against
            )

        info = team.seasons_info[season_key]
        updated_season_info = self.team_season_service.update(
            team.id,
            SeasonInfoUpdate(
                season_id=info.season_id,
                final_score=info.final_score,
                points_available=info.points_available,
                points_against=info.points_against,
            ),
        )

        team.seasons_info[season_key] = updated_season_info
        return team

    def _get_score_system(self) -> str:
        """Get the score system from settings, fallback to environment variable, default to 'standard'"""
        try:
            score_system_setting = self.settings_service.get_by_key("score_system")
            if score_system_setting and score_system_setting.value:
                return score_system_setting.value
        except Exception:
            pass

        # Fallback to environment variable for backward compatibility
        return os.getenv("SCORE_SYSTEM", "standard")

    # The body accepts no score at all, so both arguments are optional.
    def getScoreByMapScore(
        self, playerScore: int | None, opponentScore: int | None
    ) -> int | None:
        if playerScore == None and opponentScore == None:
            return None
        if playerScore == None or playerScore < 0 or playerScore > 2:
            raise Exception("Score is not valid please check it.")
        if opponentScore == None or opponentScore < 0 or opponentScore > 2:
            raise Exception("Score is not valid please check it.")

        if playerScore == 0 or playerScore == 1:
            return playerScore

        if self._get_score_system() == "helpstone":
            return self.getHelpstoneScoreByMapScore(opponentScore)

        return self.getStandardScoreByMapScore(opponentScore)

    def getHelpstoneScoreByMapScore(self, opponentScore: int) -> int | None:
        if opponentScore == 0:
            return self.HELPSTONE_MAX_SCORE
        elif opponentScore == 1:
            return self.HELPSTONE_MAX_SCORE - 1

    def getStandardScoreByMapScore(self, opponentScore: int) -> int | None:
        if opponentScore == 0:
            return self.STANDARD_MAX_SCORE
        elif opponentScore == 1:
            return self.STANDARD_MAX_SCORE - 1

    def getMaxPointsPerSeries(self) -> int:
        if self._get_score_system() == "helpstone":
            return self.HELPSTONE_MAX_SCORE
        return self.STANDARD_MAX_SCORE
