from src.service.fantasy_team_service import FantasyTeamAppService
from src.service.fantasy_bet_service import FantasyBetAppService
from src.service.series_service import SeriesAppService
from src.service.team_service import TeamAppService
from src.dtos.fantasy_team_dto import FantasyTeamDTO
from src.dtos.fantasy_bet_dto import FantasyBetDTO
from src.util.query_util import QueryUtil

class FantasyScoreAppService:
    def __init__(self,
                fantasy_team_service: FantasyTeamAppService,
                fantasy_bet_service: FantasyBetAppService,
                series_app_service: SeriesAppService,
                team_app_service: TeamAppService):
        self.fantasy_team_service = fantasy_team_service
        self.fantasy_bet_service = fantasy_bet_service
        self.series_app_service = series_app_service
        self.team_app_service = team_app_service

    def calculateTeamScores(self, season):
        
        race_points = {}
        for week in range(1,season.number_weeks+1):
            season_week_series = self.series_app_service.searchForSeasonAndPlayday(season.id, week, None)
            week_race_wins = {}
            week_race_looses = {}
            for series in season_week_series:
                if series.player1_score == 2:
                    wins = week_race_wins.get(series.player1.race)
                    if not wins:
                        week_race_wins[series.player1.race] = 0
                    week_race_wins[series.player1.race]+=1
                    looses = week_race_looses.get(series.player2.race)
                    if not looses:
                        week_race_looses[series.player2.race] = 0
                    week_race_looses[series.player2.race]+=1  
                else:
                    wins = week_race_wins.get(series.player2.race)
                    if not wins:
                        week_race_wins[series.player2.race] = 0
                    week_race_wins[series.player2.race]+=1
                    looses = week_race_looses.get(series.player1.race)
                    if not looses:
                        week_race_looses[series.player1.race] = 0
                    week_race_looses[series.player1.race]+=1 
                
            week_result = {}
            for race, wins in week_race_wins.items():
                    losses = week_race_looses.get(race)
                    week_percentage = wins/losses
                    week_result[race] = week_percentage

            # Define points for first, second, and third place
            points = [18, 12, 6]
            # Sort the races based on win/loss ratio in descending order
            sorted_races = sorted(week_result.items(), key=lambda item: item[1], reverse=True)

            for index, (race, ratio) in enumerate(sorted_races):
                if not race_points.get(race):
                    race_points[race] = 0
                if index < 3:  # Only assign points to the top 3
                    race_points[race] += points[index]

        
        fteams = self.fantasy_team_service.getAll_fantasy_teams()
        if fteams:
            for fteam in fteams:
                players = fteam.drafted_players
                team_player_points = 0
                team_bench_points = 0
                team_team_points = 0
                team_race_points = 0
                team_bet_points = 0
                if players:
                    for player in players:
                        for week in range(1,season.number_weeks+1):
                            series_q_string = f"player1_id=={player.id} or player2_id=={player.id}"
                            series_query = QueryUtil.parseQuery(series_q_string)
                            if not series_query or not series_query.elementA:
                                raise Exception(f"No valid query found: {series_q_string}")
                            week_player_series = self.series_app_service.searchForSeasonAndPlayday(season.id, week, series_query)
                            week_player_points = 0
                            week_player_bench_points = 0
                            if not week_player_series:
                                week_player_bench_points=5
                            for series in week_player_series:
                                if series.player1_score is not None and series.player2_score is not None:
                                    if player.id == series.player1_id:
                                        week_player_points+=self.calculatePoints(series.player1_score, series.player2_score)
                                    else: 
                                        week_player_points+=self.calculatePoints(series.player2_score, series.player1_score)
                            team_player_points+=week_player_points
                            team_bench_points+=week_player_bench_points
                
                drafted_team = fteam.drafted_team
                for season_info in drafted_team.seasons_info:
                    if season_info.season_id == season.id:
                        if season_info.final_score:
                            team_team_points = season_info.final_score
                
                team_race_points = race_points.get(fteam.drafted_race)

                series_q_string = f"user_id=={fteam.captain.id} and season_id=={season.id}"
                series_query = QueryUtil.parseQuery(series_q_string)
                if not series_query or not series_query.elementA:
                    raise Exception(f"No valid query found: {series_q_string}")
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
                        bet_result = 0
                        if bet.winner.ie == series_winner.id:
                            bet_result = bet.bet_points
                            team_bet_points += bet.bet_points
                        else:
                            bet_result = bet.bet_points * -1
                            team_bet_points -= bet.bet_points
                        bet.bet_result = bet_result

                        self.fantasy_bet_service.update_fantasy_bets(bet.id, bet)

                total_points = team_player_points + team_bench_points + team_team_points + team_race_points + team_bet_points

                fteam.player_points = team_player_points
                fteam.bench_points = team_bench_points
                fteam.team_points = team_team_points
                fteam.race_points = team_race_points
                fteam.bet_points = team_bet_points
                fteam.total_points = total_points
                fteam = self.fantasy_team_service.update_fantasy_team(fteam.id, fteam)                 

        return
    
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