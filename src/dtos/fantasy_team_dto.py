from src.database.model.DBFantasyTeam import DBFantasyTeam
from src.dtos.season_dto import SeasonDTO
from src.dtos.user_dto import UserDTO
from src.dtos.team_dto import TeamDTO

class FantasyTeamDTO:
    def __init__(self, data: dict):
        self.id = data.get('id')
        self.name = data.get('name')
        self.season_id = data.get('season_id')
        self.season = data.get('season')
        self.captain_id = data.get('captain_id')
        self.captain = data.get('captain')
        self.drafted_team_id = data.get('drafted_team_id')
        self.drafted_team = data.get('drafted_team')
        self.drafted_race = data.get('drafted_race')
        self.drafted_players = data.get('drafted_players')
        self.player_points = data.get('player_points')
        self.bench_points = data.get('bench_points')
        self.team_points = data.get('team_points')
        self.race_points = data.get('race_points')
        self.bet_points = data.get('bet_points')
        self.total_points = data.get('total_points')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'season_id': self.season_id,
            'season': None if not self.season else self.season.to_dict(),
            'captain_id': self.captain_id,
            'captain': None if not self.captain else self.captain.to_dict(),
            'drafted_team_id': self.drafted_team_id,
            'drafted_team': None if not self.drafted_team else self.drafted_team.to_dict(),
            'drafted_race': self.drafted_race,
            'drafted_players': [dp.to_dict() for dp in self.drafted_players if dp] if self.drafted_players else None,
            'player_points': self.player_points,
            'bench_points': self.bench_points,
            'team_points': self.team_points,
            'race_points': self.race_points,
            'bet_points': self.bet_points,
            'total_points': self.total_points
        }
    
    def to_db_dict(self):
        return {
            'name': self.name,
            'season_id': self.season_id,
            'captain_id': self.captain_id,
            'drafted_team_id': self.drafted_team_id,
            'drafted_race': self.drafted_race,
            'player_points': self.player_points,
            'bench_points': self.bench_points,
            'team_points': self.team_points,
            'race_points': self.race_points,
            'bet_points': self.bet_points,
            'total_points': self.total_points
        }
    
    @classmethod
    def from_dbfantasyteam(cls, fteam: DBFantasyTeam):
        if not fteam:
            return None

        drafted_players = []
        if fteam.drafted_players:
            for dp in fteam.drafted_players:
                user = UserDTO.from_dbuser(dp.users)
                if user:
                    drafted_players.append(user)
                
        return cls(
            {
            'id': fteam.id,
            'name': fteam.name,
            'season_id': fteam.season_id,
            'season': SeasonDTO.from_dbseason(fteam.season) if fteam.season else None,
            'captain_id': fteam.captain_id,
            'captain': UserDTO.from_dbuser(fteam.captain) if fteam.captain else None,
            'drafted_team_id': fteam.drafted_team_id,
            'drafted_team': TeamDTO.from_dbteam(fteam.drafted_team) if fteam.drafted_team else None,
            'drafted_race': fteam.drafted_race,
            'drafted_players': drafted_players,
            'player_points': fteam.player_points,
            'bench_points': fteam.bench_points,
            'team_points': fteam.team_points,
            'race_points': fteam.race_points,
            'bet_points': fteam.bet_points,
            'total_points': fteam.total_points
            }
        )
    
    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'season_id': {'type': 'integer'},
                'captain_id': {'type': 'integer'},
                'drafted_team_id': {'type': 'integer'},
                'drafted_race': {'type': 'integer'},
                'player_points': {'type': 'integer'},
                'bench_points': {'type': 'integer'},
                'team_points': {'type': 'integer'},
                'race_points': {'type': 'integer'},
                'bet_points': {'type': 'integer'},
                'total_points': {'type': 'integer'}
            },
            'required': ['season_id', 'captain_id', 'drafted_team_id', 'drafted_race']
        }