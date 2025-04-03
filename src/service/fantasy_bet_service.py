from src.database.fantasy_bet_db_service import FantasyBetDBService
from src.dtos.fantasy_team_dto import FantasyTeamDTO
from src.dtos.fantasy_bet_dto import FantasyBetDTO
from custom_exceptions import NotFoundException

class FantasyBetAppService:
    def __init__(self, fantasy_bet_service: FantasyBetDBService):
        self.fantasy_bet_service = fantasy_bet_service

    def create_fantasy_bet(self, bet: FantasyBetDTO):
        bet.id = None
        bet_data = self.fantasy_bet_service.add(bet)
        return bet_data

    def update_fantasy_bet(self, bet_id: int, bet: FantasyBetDTO):
        bet.id = bet_id
        bet_data = self.fantasy_bet_service.update(bet)
        return bet_data

    def delete_fantasy_bet(self, bet_id: int):
        self.fantasy_bet_service.delete(bet_id)

    def get_fantasy_bet(self, bet_id: int):
        bet_data = self.fantasy_bet_service.get(bet_id)
        if not bet_data:
            raise NotFoundException(f"Fantasy Bet not found by Id: {bet_id}")
        return bet_data
    
    def getAll_fantasy_bets(self):
        bet_data = self.fantasy_bet_service.getAll()
        return bet_data

    def search_fantasy_bets(self, query):
        bet_data = self.fantasy_bet_service.search(query)
        return bet_data