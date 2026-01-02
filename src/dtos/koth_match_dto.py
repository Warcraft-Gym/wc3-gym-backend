from src.database.model.DBKothMatch import DBKothMatch

class KothMatchDTO:
    def __init__(self, data: dict):
        self.id = data.get('id')
        self.event_id = data.get('event_id')
        self.bracket = data.get('bracket')
        self.game_mode = data.get('game_mode')
        self.num_teams = data.get('num_teams')
        self.winner_team_number = data.get('winner_team_number')
        self.participants = data.get('participants', [])

    def to_dict(self):
        return {
            'id': self.id,
            'event_id': self.event_id,
            'bracket': self.bracket,
            'game_mode': self.game_mode,
            'num_teams': self.num_teams,
            'winner_team_number': self.winner_team_number,
            'participants': [p.to_dict() for p in self.participants if p] if self.participants else []
        }

    def to_db_dict(self):
        return {
            'id': self.id,
            'event_id': self.event_id,
            'bracket': self.bracket,
            'game_mode': self.game_mode,
            'num_teams': self.num_teams,
            'winner_team_number': self.winner_team_number
        }

    @classmethod
    def from_db_match(cls, match: DBKothMatch):
        if not match:
            return None
        
        from src.dtos.koth_match_participant_dto import KothMatchParticipantDTO
        
        return cls({
            'id': match.id,
            'event_id': match.event_id,
            'bracket': match.bracket,
            'game_mode': match.game_mode,
            'num_teams': match.num_teams,
            'winner_team_number': match.winner_team_number,
            'participants': [KothMatchParticipantDTO.from_db_participant(p) for p in match.participants] if hasattr(match, 'participants') else []
        })
