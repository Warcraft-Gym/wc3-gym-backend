import logging
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload

from app.exceptions import NotFoundError
from app.models.koth_event import (
    KothEvent,
    KothEventCreate,
    KothEventPublic,
    KothEventUpdate,
)
from app.models.koth_match import (
    KothMatch,
    KothMatchCreate,
    KothMatchPublic,
    KothMatchUpdate,
)
from app.models.koth_match_participant import (
    KothMatchParticipant,
    KothMatchParticipantCreate,
    KothMatchParticipantPublic,
)
from app.models.koth_signup import (
    KothSignup,
    KothSignupCreate,
    KothSignupPublic,
    KothSignupUpdate,
)
from app.services.base import BaseService
from app.services.w3c import W3CService

if TYPE_CHECKING:
    from app.models.w3c_stats import W3CStatsCreate
    from app.services.settings import SettingsService

logger = logging.getLogger(__name__)


class KothService(BaseService):
    def __init__(self, settings_app_service: "SettingsService | None" = None) -> None:
        self.settings_app_service = settings_app_service

    # ============ Event Methods ============
    def add_event(self, event: KothEventCreate) -> KothEventPublic:
        with self.get_session() as session:
            db_event = KothEvent.add(session, event.model_dump())
            return KothEventPublic.model_validate(db_event)

    def create_event(self, event: KothEventCreate) -> KothEventPublic:
        return self.add_event(event)

    def update_event(self, event_id: int, event: KothEventUpdate) -> KothEventPublic:
        with self.get_session() as session:
            db_event = KothEvent.update(
                session, event_id, **event.model_dump(exclude_unset=True)
            )
            if not db_event:
                raise NotFoundError("KOTH Event not found")
            return KothEventPublic.model_validate(db_event)

    def delete_event(self, event_id: int) -> None:
        with self.get_session() as session:
            KothEvent.delete(session, event_id)

    def get_event(self, event_id: int) -> KothEventPublic:
        with self.get_session() as session:
            event = (
                session.scalars(
                    select(KothEvent)
                    .options(
                        joinedload(KothEvent.signups),
                        joinedload(KothEvent.matches)
                        .joinedload(KothMatch.participants)
                        .joinedload(KothMatchParticipant.signup),
                    )
                    .where(KothEvent.id == event_id)
                )
                .unique()
                .first()
            )
            if not event:
                raise NotFoundError(f"KOTH Event not found by Id: {event_id}")
            return KothEventPublic.model_validate(event)

    def get_all_events(self) -> list[KothEventPublic]:
        with self.get_session() as session:
            events = session.scalars(select(KothEvent)).unique().all()
            return [KothEventPublic.model_validate(e) for e in events]

    def get_active_event(self) -> KothEventPublic:
        with self.get_session() as session:
            # Pick the one event id first. A LIMIT on the outer select would
            # cut the joined signup and match rows, so the limit belongs in a
            # subquery, which is also what the old Query.first() built.
            active_event_id = (
                select(KothEvent.id)
                .where(KothEvent.is_active == True)
                .limit(1)
                .scalar_subquery()
            )
            event = (
                session.scalars(
                    select(KothEvent)
                    .options(
                        joinedload(KothEvent.signups),
                        joinedload(KothEvent.matches)
                        .joinedload(KothMatch.participants)
                        .joinedload(KothMatchParticipant.signup),
                    )
                    .where(KothEvent.id == active_event_id)
                )
                .unique()
                .first()
            )
            if not event:
                raise NotFoundError("No active KOTH event found")
            return KothEventPublic.model_validate(event)

    def set_active_event(self, event_id: int) -> KothEventPublic:
        """Set an event as active and deactivate all others"""
        all_events = self.get_all_events()
        for e in all_events:
            self.update_event(e.id, KothEventUpdate(is_active=e.id == event_id))
        return self.get_event(event_id)

    # ============ Signup Methods ============
    def add_signup(self, signup: KothSignupCreate) -> KothSignupPublic:
        with self.get_session() as session:
            db_signup = KothSignup.add(session, signup.model_dump())
            return KothSignupPublic.model_validate(db_signup)

    def update_signup(
        self, signup_id: int, signup: KothSignupUpdate
    ) -> KothSignupPublic:
        with self.get_session() as session:
            db_signup = KothSignup.update(
                session, signup_id, **signup.model_dump(exclude_unset=True)
            )
            if not db_signup:
                raise NotFoundError("KOTH Signup not found")
            return KothSignupPublic.model_validate(db_signup)

    def delete_signup(self, signup_id: int) -> None:
        with self.get_session() as session:
            KothSignup.delete(session, signup_id)

    def get_signup(self, signup_id: int) -> KothSignupPublic | None:
        with self.get_session() as session:
            signup = session.get(KothSignup, signup_id)
            if not signup:
                return None
            return KothSignupPublic.model_validate(signup)

    def get_signups_by_event(self, event_id: int) -> list[KothSignupPublic]:
        with self.get_session() as session:
            signups = (
                session.scalars(
                    select(KothSignup)
                    .where(KothSignup.event_id == event_id)
                    .order_by(KothSignup.bracket, KothSignup.mmr.desc())
                )
                .unique()
                .all()
            )
            return [KothSignupPublic.model_validate(s) for s in signups]

    def create_signup_from_twitch(
        self, twitch_username: str, battle_tag: str, preferred_race: str | None = None
    ) -> KothSignupPublic:
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
        existing_signups = self.get_signups_by_event(event.id)
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
        signup = KothSignupCreate(
            event_id=event.id,
            twitch_username=twitch_username,
            battle_tag=battle_tag,
            w3c_name=w3c_name,
            race=final_race,
            mmr=avg_mmr,
            bracket=bracket,
            is_king=0,
            is_active=1,
        )

        return self.add_signup(signup)

    def update_signup_bracket(
        self, signup_id: int, new_bracket: int
    ) -> KothSignupPublic:
        """Manually update a player's bracket"""
        if new_bracket not in [1, 2, 3]:
            raise ValueError("Bracket must be 1, 2, or 3")

        signup = self.get_signup(signup_id)
        if not signup:
            raise NotFoundError(f"Signup not found by Id: {signup_id}")

        return self.update_signup(signup_id, KothSignupUpdate(bracket=new_bracket))

    def set_king(self, signup_id: int) -> KothSignupPublic:
        """Set a player as king of their bracket (clears other kings in bracket)"""
        signup = self.get_signup(signup_id)
        if not signup:
            raise NotFoundError(f"Signup not found by Id: {signup_id}")

        # Unset any other kings in the same bracket
        event_signups = self.get_signups_by_event(signup.event_id)
        for s in event_signups:
            if s.bracket == signup.bracket and s.is_king == 1 and s.id != signup_id:
                self.update_signup(s.id, KothSignupUpdate(is_king=0))

        return self.update_signup(signup_id, KothSignupUpdate(is_king=1))

    def add_king(self, signup_id: int) -> KothSignupPublic:
        """Add a player as king of their bracket (keeps existing kings)"""
        signup = self.get_signup(signup_id)
        if not signup:
            raise NotFoundError(f"Signup not found by Id: {signup_id}")

        return self.update_signup(signup_id, KothSignupUpdate(is_king=1))

    def unset_king(self, signup_id: int) -> KothSignupPublic:
        """Remove king status from a player"""
        signup = self.get_signup(signup_id)
        if not signup:
            raise NotFoundError(f"Signup not found by Id: {signup_id}")

        return self.update_signup(signup_id, KothSignupUpdate(is_king=0))

    # ============ Match Methods ============
    def add_match(self, match: KothMatchCreate) -> KothMatchPublic:
        with self.get_session() as session:
            db_match = KothMatch.add(session, match.model_dump())
            return KothMatchPublic.model_validate(db_match)

    def update_match(self, match_id: int, match: KothMatchUpdate) -> KothMatchPublic:
        with self.get_session() as session:
            db_match = KothMatch.update(
                session, match_id, **match.model_dump(exclude_unset=True)
            )
            if not db_match:
                raise NotFoundError("KOTH Match not found")
            return KothMatchPublic.model_validate(db_match)

    def delete_match(self, match_id: int) -> None:
        with self.get_session() as session:
            KothMatch.delete(session, match_id)

    def get_match(self, match_id: int) -> KothMatchPublic | None:
        with self.get_session() as session:
            match = (
                session.scalars(
                    select(KothMatch)
                    .options(
                        joinedload(KothMatch.participants).joinedload(
                            KothMatchParticipant.signup
                        )
                    )
                    .where(KothMatch.id == match_id)
                )
                .unique()
                .first()
            )
            if not match:
                return None
            return KothMatchPublic.model_validate(match)

    def get_matches_by_event(self, event_id: int) -> list[KothMatchPublic]:
        with self.get_session() as session:
            matches = (
                session.scalars(
                    select(KothMatch)
                    .options(
                        joinedload(KothMatch.participants).joinedload(
                            KothMatchParticipant.signup
                        )
                    )
                    .where(KothMatch.event_id == event_id)
                    .order_by(KothMatch.bracket, KothMatch.id)
                )
                .unique()
                .all()
            )
            return [KothMatchPublic.model_validate(m) for m in matches]

    def create_match(
        self, match: KothMatchCreate, participant_signup_ids: list[dict[str, int]]
    ) -> KothMatchPublic | None:
        """
        Create a team-based match with participants.
        participant_signup_ids: list of dicts with {'signup_id': int, 'team_number': int}
        """
        # Validate all participants exist and are in the same bracket
        signups = []
        for participant in participant_signup_ids:
            signup = self.get_signup(participant["signup_id"])
            if not signup:
                raise NotFoundError(
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
        created_match = self.add_match(match)

        # Add participants
        for participant in participant_signup_ids:
            self.add_participant(
                KothMatchParticipantCreate(
                    match_id=created_match.id,
                    signup_id=participant["signup_id"],
                    team_number=participant["team_number"],
                )
            )

        # Return match with participants loaded
        return self.get_match(created_match.id)

    def update_match_result(
        self, match_id: int, winner_team_number: int
    ) -> KothMatchPublic:
        """Update match winner, set all winning team members as kings, and delete losing participant signups"""
        match = self.get_match(match_id)
        if not match:
            raise NotFoundError(f"Match not found by Id: {match_id}")

        if winner_team_number < 1 or winner_team_number > match.num_teams:
            raise ValueError(
                f"Winner team number must be between 1 and {match.num_teams}"
            )

        updated_match = self.update_match(
            match.id, KothMatchUpdate(winner_team_number=winner_team_number)
        )

        # Get participants and set winners as kings
        participants = self.get_participants_by_match(match_id)

        # Unset all kings in this bracket first
        all_signups = self.get_signups_by_event(match.event_id)
        for signup in all_signups:
            if signup.bracket == match.bracket and signup.is_king == 1:
                self.update_signup(signup.id, KothSignupUpdate(is_king=0))

        # Set winning team members as kings and mark losing team signups as inactive
        for participant in participants:
            if participant.team_number == winner_team_number:
                self.update_signup(participant.signup_id, KothSignupUpdate(is_king=1))
            else:
                # Mark signups of losing teams as inactive so they can sign up again
                self.update_signup(participant.signup_id, KothSignupUpdate(is_active=0))

        return updated_match

    # ============ Match Participant Methods ============
    def add_participant(
        self, participant: KothMatchParticipantCreate
    ) -> KothMatchParticipantPublic:
        with self.get_session() as session:
            db_participant = KothMatchParticipant.add(session, participant.model_dump())
            return KothMatchParticipantPublic.model_validate(db_participant)

    def delete_participants_by_match(self, match_id: int) -> None:
        """Delete all participants for a given match"""
        with self.get_session() as session:
            session.execute(
                delete(KothMatchParticipant).where(
                    KothMatchParticipant.match_id == match_id
                ),
                execution_options={"synchronize_session": False},
            )

    def get_participants_by_match(
        self, match_id: int
    ) -> list[KothMatchParticipantPublic]:
        with self.get_session() as session:
            participants = (
                session.scalars(
                    select(KothMatchParticipant)
                    .options(joinedload(KothMatchParticipant.signup))
                    .where(KothMatchParticipant.match_id == match_id)
                    .order_by(KothMatchParticipant.team_number)
                )
                .unique()
                .all()
            )
            return [KothMatchParticipantPublic.model_validate(p) for p in participants]

    def get_bracket_kings(self, event_id: int) -> dict[int, list[KothSignupPublic]]:
        """Get all kings for each bracket"""
        signups = self.get_signups_by_event(event_id)
        kings: dict[int, list[KothSignupPublic]] = {}
        for signup in signups:
            if signup.is_king == 1:
                if signup.bracket not in kings:
                    kings[signup.bracket] = []
                kings[signup.bracket].append(signup)
        return kings

    # ============ Helper Methods ============
    def _determine_bracket(self, mmr: int, event: KothEventPublic) -> int:
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
    ) -> list["W3CStatsCreate"]:
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
        from app.models.w3c_stats import W3CStatsCreate

        for gmode_stats in result:
            if gmode_stats.get("gameMode") and gmode_stats.get("gameMode") == 1:
                stats.append(
                    W3CStatsCreate(
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

    # Required abstract methods
    # BaseService asks for these four. This service works through the
    # add_event/add_signup/add_match methods above, so they stay empty.
    def get(self, obj_id: object) -> None:
        pass

    def add(self, **kwargs: object) -> None:
        pass

    def update(self, obj_id: object, **kwargs: object) -> None:
        pass

    def delete(self, obj_id: object) -> None:
        pass
