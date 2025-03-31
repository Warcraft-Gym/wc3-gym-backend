from src.database.model.DBW3CStats import DBW3CStats

class W3CStatsDTO:
    def __init__(self, data : dict):
        self.id = data.get('id')
        self.wc3_season = data.get('wc3_season')
        self.wins = data.get('wins')
        self.losses = data.get('losses')
        self.games = data.get('games')
        self.mmr = data.get('mmr')
        self.winrate = data.get('winrate')
        self.race = data.get('race')
        self.league = data.get('league')
        self.user_id = data.get('user_id')

    def to_dict(self):
        return {
            'id': self.id,
            'wc3_season': self.wc3_season,
            'wins': self.wins,
            'losses': self.losses,
            'games': self.games,
            'mmr': self.mmr,
            'winrate': self.winrate,
            'race': self.race,
            'league': self.league,
            'user_id': self.user_id
        }
    
    def to_db_dict(self):
        return {
            'wc3_season': self.wc3_season,
            'wins': self.wins,
            'losses': self.losses,
            'games': self.games,
            'mmr': self.mmr,
            'winrate': self.winrate,
            'race': self.race,
            'league': self.league,
            'user_id': self.user_id
        }

    @classmethod
    def from_dbw3cstats(cls, stats: DBW3CStats):
        return cls(
                {
                'id': stats.id,
                'wc3_season': stats.wc3_season,
                'wins': stats.wins,
                'losses': stats.losses,
                'games': stats.games,
                'mmr': stats.mmr,
                'winrate': stats.winrate,
                'race': stats.race,
                'league': stats.league,
                'user_id': stats.user_id
            }
        )

    @staticmethod
    def schema():
        return {
            "type": "object",
            "properties": {
                "wc3_season": {
                    "type": "integer",
                    "description": "Season Number"
                },
                "wins": {
                    "type": "integer",
                    "description": "Number of wins"
                },
                "losses": {
                    "type": "integer",
                    "description": "Number of losses"
                },
                "games": {
                    "type": "intger",
                    "description": "Number of games"
                },
                "mmr": {
                    "type": "integer",
                    "description": "User's MMR"
                },
                "winrate": {
                    "type": "float",
                    "description": "Percentage of won games"
                },
                "race": {
                    "type": "string",
                    "description": "Race of the stats"
                },
                 "league": {
                    "type": "integer",
                    "description": "Number of the league"
                },
                "user_id": {
                    "type": "string",
                    "description": "User's Id"
                }
            }
        }