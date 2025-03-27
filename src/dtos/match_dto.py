from src.database.model.DBMatch import DBMatch
from src.dtos.season_dto import SeasonDTO
from src.dtos.team_dto import TeamDTO
from src.dtos.map_dto import MapDTO

class MatchDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.team1_id = data.get('team1_id')
        self.team1 = data.get('team1')
        self.team2_id = data.get('team2_id')
        self.team2 = data.get('team2')
        self.season_id = data.get('season_id')
        self.season = data.get('season')
        self.playday = data.get('playday')
        self.date_frame = data.get('date_frame')
        self.fixed_map_id = data.get('fixed_map_id')
        self.fixed_map = data.get('fixed_map')
        self.team1_score = data.get('team1_score')
        self.team2_score = data.get('team2_score')

    def to_dict(self):
        return {
            'id': self.id,
            'team1_id': self.team1_id,
            'team1': None if not self.team1 else self.team1.to_dict_reduced(),
            'team2_id': self.team2_id,
            'team2': None if not self.team2 else self.team2.to_dict_reduced(),
            'season_id': self.season_id,
            'season':  None if not self.season else self.season.to_dict(),
            'playday': self.playday,
            'date_frame': self.date_frame,
            'fixed_map_id': self.fixed_map_id,
            'fixed_map': None if not self.fixed_map else self.fixed_map.to_dict(),
            'team1_score': self.team1_score,
            'team2_score': self.team2_score
        }
    
    def to_db_dict(self):
        return {
            'team1_id': self.team1_id,
            'team2_id': self.team2_id,
            'season_id': self.season_id,
            'playday': self.playday,
            'date_frame': self.date_frame,
            'fixed_map_id': self.fixed_map_id,
            'team1_score': self.team1_score,
            'team2_score': self.team2_score
        }

    @classmethod
    def from_dbmatch(cls, match: DBMatch):
        return cls(
            {
                'id': match.id,
                'team1_id': match.team1_id,
                'team1': TeamDTO.from_dbteam(match.team1) if match.team1 else None,
                'team2_id': match.team2_id,
                'team2': TeamDTO.from_dbteam(match.team2) if match.team2 else None,
                'season_id': match.season_id,
                'season': SeasonDTO.from_dbseason(match.season) if match.season else None,
                'playday': match.playday,
                'date_frame': match.date_frame,
                'fixed_map_id': match.fixed_map_id,
                'fixed_map': MapDTO.from_dbmap(match.fixed_map) if match.fixed_map else None,
                'team1_score': match.team1_score,
                'team2_score': match.team2_score
            }
        )
    
    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'team1_id': {'type': 'integer'},
                'team2_id': {'type': 'integer'},
                'season_id': {'type': 'integer'},
                'playday': {'type': 'integer'},
                'date_frame': {'type': 'string'},
                'fixed_map_id': {'type': 'integer'},
                'team1_score' : {'type': 'integer'},
                'team2_score' : {'type': 'integer'}
            },
            'required': ['team1_id','team2_id']
        }
