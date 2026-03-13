from src.database.model.DBRelationships import DBUserTeamSeason

class UserTeamSeasonStatsDTO:
    def __init__(self, data : dict):
        self.user_id = data.get('user_id')
        self.team_id = data.get('team_id')
        self.team = data.get('team')
        self.games = data.get('games')
        self.wins = data.get('wins')
        self.losses = data.get('losses')
        self.season_id = data.get('season_id')
        self.season = data.get('season')
        self.matchup_history = data.get('matchup_history', [])

    def to_dict(self):
        return {
            'user_id' : self.user_id,
            'team_id' : self.team_id,
            'games' : self.games,
            'team' : self.team.to_dict_reduced() if self.team else None,
            'wins' : self.wins,
            'losses' : self.losses,
            'season_id' : self.season_id,
            'season' : self.season.to_dict() if self.season else None,
            'matchup_history' : self.matchup_history if self.matchup_history else []
        }
    
    @classmethod
    def from_db_user_team_season(cls, uts: DBUserTeamSeason):
        if not uts:
            return None

        from src.dtos.season_dto import SeasonDTO
        from src.dtos.team_dto import TeamDTO

        return cls({
            'user_id' : uts.user_id,
            'team_id' : uts.team_id,
            'games' : uts.games,
            'team' : TeamDTO.from_dbteam_reduced(uts.team) if uts.team else None,
            'wins' : uts.wins,
            'losses' : uts.losses,
            'season_id' : uts.season_id,
            'season' : SeasonDTO.from_dbseason_reduced(uts.season) if uts.season else None,
            'matchup_history' : uts.matchup_history if uts.matchup_history else []
        })
    
    @staticmethod
    def schema():
        from src.dtos.season_dto import SeasonDTO
        from src.dtos.team_dto import TeamDTO
        return {
            'type': 'object',
            'properties': {
                'user_id': {'type': 'integer'},
                'team_id': {'type': 'integer'},
                'team': {'type': TeamDTO},
                'games': {'type': 'integer'},
                'wins': {'type': 'integer'},
                'losses': {'type': 'integer'},
                'season_id': {'type': 'integer'},
                'season': {'type': SeasonDTO},
            }
        }