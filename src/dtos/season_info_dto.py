from src.database.model.DBRelationships import DBTeamSeason
from src.database.model.DBSeason import DBSeason
from src.dtos.season_dto import SeasonDTO

class SeasonInfoDTO:
    def __init__(self, data : dict):
        self.season_id = data.get('season_id')
        self.final_score = data.get('final_score')
        self.points_available = data.get('points_available')
        self.points_against = data.get('points_against')
        self.season = data.get('season')

    def to_dict(self):
        return {
            'season_id' : self.season_id,
            'final_score': self.final_score,
            'points_available': self.points_available,
            'points_against' : self.points_against,
            'season' : self.season.to_dict() if self.season else None
        }
    
    def to_db_dict(self):
        return {
            'season_id' : self.season_id,
            'final_score': self.final_score,
            'points_available': self.points_available,
            'points_against' : self.points_against,
        }

    @classmethod
    def from_dbseasoninfo(cls, season_info: DBTeamSeason):
        if not season_info:
            return None

        return cls(
            {
            'season_id' : season_info.season_id,
            'final_score': season_info.final_score,
            'points_available': season_info.points_available,
            'points_against' : season_info.points_against,
            'season' : SeasonDTO.from_dbseason(season_info.season) if season_info.season else None
        }
        )
    
    @staticmethod
    def schema():
        return {
            'type': 'object',
            'properties': {
                'season_id': {'type': 'integer'},
                'final_score': {'type': 'integer'},
                'points_available': {'type': 'integer'},
                'points_against': {'type': 'integer'},
                'season': {'type': DBSeason},
            }
        }