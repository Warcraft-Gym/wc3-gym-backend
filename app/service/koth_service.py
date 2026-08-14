import logging

from app.database.koth_db_service import KothDBService
from app.exceptions import NotFoundException
from app.schemas.koth_event import KothEvent
from app.schemas.koth_match import KothMatch
from app.schemas.koth_match_participant import KothMatchParticipant
from app.schemas.koth_signup import KothSignup
from app.service.w3champions.w3c_service import W3CService

logger = logging.getLogger(__name__)


class KothAppService:
    def __init__(self, koth_service: KothDBService, settings_app_service=None):
        self.koth_service = koth_service
        self.settings_app_service = settings_app_service

    # ============ Event Methods ============
    def create_event(self, event: KothEvent):
        event.id = None
        return self.koth_service.add_event(event)

    def update_event(self, event_id, event: KothEvent):
        event.id = event_id
        return self.koth_service.update_event(event)

    def delete_event(self, event_id: int):
        self.koth_service.delete_event(event_id)

    def get_event(self, event_id: int):
        event = self.koth_service.get_event(event_id)
        if not event:
            raise NotFoundException(f"KOTH Event not found by Id: {event_id}")
        return event

    def get_all_events(self):
        return self.koth_service.get_all_events()

    def get_active_event(self):
        event = self.koth_service.get_active_event()
        if not event:
            raise NotFoundException("No active KOTH event found")
        return event

    def set_active_event(self, event_id: int):
        """Set an event as active and deactivate all others"""
        all_events = self.koth_service.get_all_events()
        for e in all_events:
            e.is_active = e.id == event_id
            self.koth_service.update_event(e)
        return self.get_event(event_id)

    # ============ Signup Methods ============
    def create_signup_from_twitch(
        self, twitch_username: str, battle_tag: str, preferred_race: str | None = None
    ):
        """
        Create a signup from Twitch/Nightbot with automatic W3C validation and bracket assignment.
        Only allows signup if no active signup exists for this twitch username.
        If preferred_race is provided, only considers MMR for that race.
        Returns the created signup DTO or raises an exception.
        """
        # Normalize race input
        race_map = {
            "orc": "OC",
            "oc": "OC",
            "human": "HU",
            "hu": "HU",
            "undead": "UD",
            "ud": "UD",
            "nightelf": "NE",
            "ne": "NE",
            "random": "RANDOM",
            "rd": "RANDOM",
        }

        signup_race = None
        if preferred_race:
            preferred_race_lower = preferred_race.lower()
            signup_race = race_map.get(preferred_race_lower)
            if not signup_race:
                raise ValueError(
                    f"Invalid race '{preferred_race}'. Valid options: orc, human, undead, nightelf, random"
                )

        # Get active event
        event = self.get_active_event()

        # Check if player already has an active signup with the same race
        existing_signups = self.koth_service.get_signups_by_event(event.id)
        for signup in existing_signups:
            if signup.is_active == 1 and signup.twitch_username == twitch_username:
                # If a race is specified, only prevent duplicate if it's the same race
                if signup_race and signup.race == signup_race:
                    raise Exception(
                        f"Player {twitch_username} already has an active signup with race {signup_race}"
                    )
                # If no race specified, check if they have any active signup (to prevent auto-picking duplicate)
                elif not signup_race:
                    raise Exception(
                        f"Player {twitch_username} already has an active signup. Specify a race to signup with a different race."
                    )

        # Validate and get W3C stats
        w3c_service = W3CService(settings_app_service=self.settings_app_service)

        # Get stats from the most recent season (within last 3 seasons)
        race_mmr_data = {}  # {race: mmr} for the found season
        w3c_name = battle_tag

        try:
            current_season = self._get_current_w3c_season()
            for season_offset in range(2):
                season = current_season - season_offset
                try:
                    stats = self._get_w3c_stats_for_season(
                        w3c_service, battle_tag, season
                    )
                    if stats:
                        for stat in stats:
                            if stat.mmr and stat.mmr > 0:
                                # Race is an object, get the value string
                                race_mmr_data[stat.race.value] = stat.mmr

                        # Stop checking older seasons if we found the required stats
                        if signup_race:
                            # If a specific race was requested, only stop if we found that race
                            if signup_race in race_mmr_data:
                                logger.debug(
                                    f"Found W3C stats for {battle_tag} with race {signup_race} in season {season}"
                                )
                                break
                        else:
                            # If no race specified, stop as soon as we find any stats
                            if race_mmr_data:
                                logger.debug(
                                    f"Found W3C stats for {battle_tag} in season {season}"
                                )
                                break
                except Exception as e:
                    logger.debug(f"No stats for {battle_tag} in season {season}: {e}")
                    continue
        except Exception as e:
            raise Exception(f"Failed to validate W3C stats for {battle_tag}: {e!s}")

        # Determine final race and MMR
        if signup_race:
            # Race was specified (including RANDOM)
            if signup_race not in race_mmr_data:
                raise Exception(
                    f"No W3Champions statistics found for {battle_tag} with race {signup_race} in the last 3 seasons"
                )
            avg_mmr = race_mmr_data[signup_race]
            final_race = signup_race
        else:
            # No race specified - find race with highest MMR
            if not race_mmr_data:
                raise Exception(
                    f"No valid MMR data found for {battle_tag} in the last 3 seasons"
                )

            highest_race = max(race_mmr_data, key=race_mmr_data.get)
            avg_mmr = race_mmr_data[highest_race]
            final_race = highest_race

        # Determine bracket
        bracket = self._determine_bracket(avg_mmr, event)

        # Create signup
        signup = KothSignup(
            {
                "event_id": event.id,
                "twitch_username": twitch_username,
                "battle_tag": battle_tag,
                "w3c_name": w3c_name,
                "race": final_race,
                "mmr": avg_mmr,
                "bracket": bracket,
                "is_king": 0,
                "is_active": 1,
            }
        )

        return self.koth_service.add_signup(signup)

    def update_signup_bracket(self, signup_id: int, new_bracket: int):
        """Manually update a player's bracket"""
        if new_bracket not in [1, 2, 3]:
            raise ValueError("Bracket must be 1, 2, or 3")

        signup = self.koth_service.get_signup(signup_id)
        if not signup:
            raise NotFoundException(f"Signup not found by Id: {signup_id}")

        signup.bracket = new_bracket
        return self.koth_service.update_signup(signup)

    def set_king(self, signup_id: int):
        """Set a player as king of their bracket (clears other kings in bracket)"""
        signup = self.koth_service.get_signup(signup_id)
        if not signup:
            raise NotFoundException(f"Signup not found by Id: {signup_id}")

        # Unset any other kings in the same bracket
        event_signups = self.koth_service.get_signups_by_event(signup.event_id)
        for s in event_signups:
            if s.bracket == signup.bracket and s.is_king == 1 and s.id != signup_id:
                s.is_king = 0
                self.koth_service.update_signup(s)

        signup.is_king = 1
        return self.koth_service.update_signup(signup)

    def add_king(self, signup_id: int):
        """Add a player as king of their bracket (keeps existing kings)"""
        signup = self.koth_service.get_signup(signup_id)
        if not signup:
            raise NotFoundException(f"Signup not found by Id: {signup_id}")

        signup.is_king = 1
        return self.koth_service.update_signup(signup)

    def unset_king(self, signup_id: int):
        """Remove king status from a player"""
        signup = self.koth_service.get_signup(signup_id)
        if not signup:
            raise NotFoundException(f"Signup not found by Id: {signup_id}")

        signup.is_king = 0
        return self.koth_service.update_signup(signup)

    def delete_signup(self, signup_id: int):
        self.koth_service.delete_signup(signup_id)

    def get_signups_by_event(self, event_id: int):
        return self.koth_service.get_signups_by_event(event_id)

    # ============ Match Methods ============
    def create_match(self, match: KothMatch, participant_signup_ids: list):
        """
        Create a team-based match with participants.
        participant_signup_ids: list of dicts with {'signup_id': int, 'team_number': int}
        """
        match.id = None

        # Validate all participants exist and are in the same bracket
        signups = []
        for participant in participant_signup_ids:
            signup = self.koth_service.get_signup(participant["signup_id"])
            if not signup:
                raise NotFoundException(
                    f"Signup not found by Id: {participant['signup_id']}"
                )
            signups.append(signup)

        # All must be in same bracket
        if signups:
            first_bracket = signups[0].bracket
            if not all(s.bracket == first_bracket for s in signups):
                raise ValueError("All participants must be in the same bracket")
            match.bracket = first_bracket

        # Validate team configuration - each team must have at least 1 player
        team_numbers = [p["team_number"] for p in participant_signup_ids]
        unique_teams = set(team_numbers)

        if len(unique_teams) != match.num_teams:
            raise ValueError(
                f"Expected {match.num_teams} teams, but participants are assigned to {len(unique_teams)} teams"
            )

        for team_num in range(1, match.num_teams + 1):
            if team_num not in unique_teams:
                raise ValueError(f"Team {team_num} has no participants")

        # Create match
        created_match = self.koth_service.add_match(match)

        # Add participants
        for participant in participant_signup_ids:
            participant_dto = KothMatchParticipant(
                {
                    "match_id": created_match.id,
                    "signup_id": participant["signup_id"],
                    "team_number": participant["team_number"],
                }
            )
            self.koth_service.add_participant(participant_dto)

        # Return match with participants loaded
        return self.koth_service.get_match(created_match.id)

    def update_match(self, match_id: int, match: KothMatch):
        match.id = match_id
        return self.koth_service.update_match(match)

    def update_match_result(self, match_id: int, winner_team_number: int):
        """Update match winner, set all winning team members as kings, and delete losing participant signups"""
        match = self.koth_service.get_match(match_id)
        if not match:
            raise NotFoundException(f"Match not found by Id: {match_id}")

        if winner_team_number < 1 or winner_team_number > match.num_teams:
            raise ValueError(
                f"Winner team number must be between 1 and {match.num_teams}"
            )

        match.winner_team_number = winner_team_number
        updated_match = self.koth_service.update_match(match)

        # Get participants and set winners as kings
        participants = self.koth_service.get_participants_by_match(match_id)

        # Unset all kings in this bracket first
        all_signups = self.koth_service.get_signups_by_event(match.event_id)
        for signup in all_signups:
            if signup.bracket == match.bracket and signup.is_king == 1:
                signup.is_king = 0
                self.koth_service.update_signup(signup)

        # Set winning team members as kings and mark losing team signups as inactive
        for participant in participants:
            if participant.team_number == winner_team_number:
                signup = self.koth_service.get_signup(participant.signup_id)
                signup.is_king = 1
                self.koth_service.update_signup(signup)
            else:
                # Mark signups of losing teams as inactive so they can sign up again
                signup = self.koth_service.get_signup(participant.signup_id)
                signup.is_active = 0
                self.koth_service.update_signup(signup)

        return updated_match

    def delete_match(self, match_id: int):
        self.koth_service.delete_match(match_id)

    def get_matches_by_event(self, event_id: int):
        return self.koth_service.get_matches_by_event(event_id)

    def get_bracket_kings(self, event_id: int):
        """Get all kings for each bracket"""
        signups = self.koth_service.get_signups_by_event(event_id)
        kings = {}
        for signup in signups:
            if signup.is_king == 1:
                if signup.bracket not in kings:
                    kings[signup.bracket] = []
                kings[signup.bracket].append(signup)
        return kings

    # ============ Helper Methods ============
    def _determine_bracket(self, mmr: int, event: KothEvent) -> int:
        """Determine bracket based on MMR thresholds"""
        if mmr < event.bracket_1_threshold:
            return 1
        elif mmr < event.bracket_2_threshold:
            return 2
        else:
            return 3

    def _get_current_w3c_season(self) -> int:
        """Get current W3C season from settings or environment"""
        if self.settings_app_service:
            season_setting = self.settings_app_service.get_setting("current_wc3_season")
            if season_setting:
                return int(season_setting.get("value"))

        import os

        season = os.getenv("CURRENT_WC3_SEASON")
        if season:
            return int(season)

        raise ValueError("Current W3C season not configured")

    def _get_w3c_stats_for_season(
        self, w3c_service: W3CService, battle_tag: str, season: int
    ):
        """Get W3C stats for a specific season"""
        import os
        import urllib.parse

        w3c_url = None
        if self.settings_app_service:
            w3c_url_setting = self.settings_app_service.get_setting("w3c_url")
            w3c_url = w3c_url_setting.get("value") if w3c_url_setting else None

        if not w3c_url:
            w3c_url = os.getenv("W3C_URL")

        if not w3c_url:
            raise ValueError("W3C URL not configured")

        param = {"gateWay": 20, "season": season}

        result = w3c_service.send_request(
            method=w3c_service.GET,
            url=f"{w3c_url}/{urllib.parse.quote(battle_tag)}/game-mode-stats",
            params=param,
        )

        if not result:
            return []

        stats = []
        from app.schemas.w3c_stats import W3CStats

        for gmode_stats in result:
            if gmode_stats.get("gameMode") and gmode_stats.get("gameMode") == 1:
                stats.append(
                    W3CStats(
                        wc3_season=gmode_stats.get("season"),
                        wins=gmode_stats.get("wins"),
                        losses=gmode_stats.get("losses"),
                        games=gmode_stats.get("games"),
                        mmr=gmode_stats.get("mmr"),
                        winrate=gmode_stats.get("winrate"),
                        race=w3c_service.getRaceEnum(gmode_stats.get("race")),
                        league=gmode_stats.get("leagueOrder"),
                    )
                )

        return stats
