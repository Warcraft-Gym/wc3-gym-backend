import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.enums import Race
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
from app.services.w3c import W3CService

if TYPE_CHECKING:
    from app.services.settings import SettingsService

logger = logging.getLogger(__name__)


class KothService:
    def __init__(self, settings_app_service: "SettingsService | None" = None) -> None:
        self.settings_app_service = settings_app_service

    # ============ Event Methods ============
    def add_event(self, event: KothEventCreate) -> KothEventPublic:
        with Session.begin() as session:
            db_event = KothEvent.add(session, event.model_dump())
            return KothEventPublic.model_validate(db_event)

    def update_event(self, event_id: int, event: KothEventUpdate) -> KothEventPublic:
        with Session.begin() as session:
            db_event = KothEvent.update(
                session, event_id, **event.model_dump(exclude_unset=True)
            )
            if not db_event:
                raise NotFoundError("KOTH Event not found")
            return KothEventPublic.model_validate(db_event)

    def delete_event(self, event_id: int) -> None:
        with Session.begin() as session:
            KothEvent.delete(session, event_id)

    def get_event(self, event_id: int) -> KothEventPublic:
        with Session.begin() as session:
            event = (
                session.scalars(
                    select(KothEvent)
                    .options(
                        joinedload(KothEvent.signups),
                        joinedload(KothEvent.matches)
                        .joinedload(KothMatch.participants)
                        .joinedload(KothMatchParticipant.signup),
                    )
                    .where(col(KothEvent.id) == event_id)
                )
                .unique()
                .first()
            )
            if not event:
                raise NotFoundError(f"KOTH Event not found by Id: {event_id}")
            return KothEventPublic.model_validate(event)

    def get_all_events(self) -> list[KothEventPublic]:
        with Session.begin() as session:
            events = session.scalars(select(KothEvent)).unique().all()
            return [KothEventPublic.model_validate(e) for e in events]

    def get_active_event(self) -> KothEventPublic:
        with Session.begin() as session:
            # A LIMIT on the outer select would cut the joined rows
            active_event_id = (
                select(col(KothEvent.id))
                .where(col(KothEvent.is_active) == True)
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
                    .where(col(KothEvent.id) == active_event_id)
                )
                .unique()
                .first()
            )
            if not event:
                raise NotFoundError("No active KOTH event found")
            return KothEventPublic.model_validate(event)

    def set_active_event(self, event_id: int) -> KothEventPublic:
        """Set an event as active and deactivate all others"""
        with Session.begin() as session:
            if not session.get(KothEvent, event_id):
                raise NotFoundError(f"KOTH Event not found by Id: {event_id}")
            # One transaction, so no other request reads the table between the two
            session.execute(
                update(KothEvent)
                .where(col(KothEvent.is_active) == True)
                .values(is_active=False),
                execution_options={"synchronize_session": False},
            )
            session.execute(
                update(KothEvent)
                .where(col(KothEvent.id) == event_id)
                .values(is_active=True),
                execution_options={"synchronize_session": False},
            )
        return self.get_event(event_id)

    # ============ Signup Methods ============
    def update_signup(
        self, signup_id: int, signup: KothSignupUpdate
    ) -> KothSignupPublic:
        with Session.begin() as session:
            db_signup = KothSignup.update(
                session, signup_id, **signup.model_dump(exclude_unset=True)
            )
            if not db_signup:
                raise NotFoundError("KOTH Signup not found")
            return KothSignupPublic.model_validate(db_signup)

    def delete_signup(self, signup_id: int) -> None:
        with Session.begin() as session:
            KothSignup.delete(session, signup_id)

    def get_signup(self, signup_id: int) -> KothSignupPublic:
        with Session.begin() as session:
            signup = session.get(KothSignup, signup_id)
            if not signup:
                raise NotFoundError(f"Signup not found by Id: {signup_id}")
            return KothSignupPublic.model_validate(signup)

    def get_signups_by_event(
        self, event_id: int, limit: int | None = None, offset: int = 0
    ) -> list[KothSignupPublic]:
        with Session.begin() as session:
            statement = (
                select(KothSignup)
                .where(col(KothSignup.event_id) == event_id)
                .order_by(col(KothSignup.bracket), col(KothSignup.mmr).desc())
            )
            if limit is not None or offset:
                # The id breaks the ties the bracket and mmr order leaves
                statement = statement.order_by(col(KothSignup.id)).offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            signups = session.scalars(statement).unique().all()
            return [KothSignupPublic.model_validate(s) for s in signups]

    def create_signup_from_twitch(
        self, twitch_username: str, battle_tag: str, preferred_race: str | None = None
    ) -> KothSignupPublic:
        """
        Create a signup from Twitch/Nightbot with automatic W3C validation and bracket assignment.
        Only allows signup if no active signup exists for this twitch username.
        If preferred_race is provided, only considers MMR for that race.
        Returns the created signup or raises an exception.
        """
        signup_race = None
        if preferred_race:
            try:
                signup_race = Race.from_text(preferred_race).value
            except ValueError as error:
                raise BadRequestError(
                    f"Invalid race '{preferred_race}'. Valid options: orc, human, undead, nightelf, random"
                ) from error

        # Get active event
        event = self.get_active_event()

        # The W3C calls below take seconds, so the insert checks this again
        with Session.begin() as session:
            self._check_duplicate_signup(
                session, event.id, twitch_username, signup_race
            )

        # Validate and get W3C stats
        w3c_service = W3CService(settings_app_service=self.settings_app_service)

        # Get stats from the most recent season (within last 3 seasons)
        race_mmr_data = {}  # {race: mmr} for the found season
        w3c_name = battle_tag

        current_season = w3c_service.current_season()
        for season_offset in range(2):
            season = current_season - season_offset
            try:
                stats = w3c_service.get_player_stats(battle_tag, season_override=season)
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

        # Determine final race and MMR
        if signup_race:
            # Race was specified (including RANDOM)
            if signup_race not in race_mmr_data:
                raise BadRequestError(
                    f"No W3Champions statistics found for {battle_tag} with race {signup_race} in the last 3 seasons"
                )
            avg_mmr = race_mmr_data[signup_race]
            final_race = signup_race
        else:
            # No race specified - find race with highest MMR
            if not race_mmr_data:
                raise BadRequestError(
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

        with Session.begin() as session:
            self._check_duplicate_signup(
                session, event.id, twitch_username, signup_race
            )
            try:
                db_signup = KothSignup.add(session, signup.model_dump())
            except IntegrityError as error:
                # The unique index holds where the check cannot: two signups at once
                raise BadRequestError(
                    f"Player {twitch_username} already has an active signup with race {final_race}"
                ) from error
            return KothSignupPublic.model_validate(db_signup)

    def update_signup_bracket(
        self, signup_id: int, new_bracket: int
    ) -> KothSignupPublic:
        """Manually update a player's bracket"""
        if new_bracket not in [1, 2, 3]:
            raise BadRequestError("Bracket must be 1, 2, or 3")

        self.get_signup(signup_id)  # 404 names the id
        return self.update_signup(signup_id, KothSignupUpdate(bracket=new_bracket))

    def set_king(self, signup_id: int) -> KothSignupPublic:
        """Set a player as king of their bracket (clears other kings in bracket)"""
        signup = self.get_signup(signup_id)
        self._clear_bracket_kings(signup.event_id, signup.bracket)
        return self.update_signup(signup_id, KothSignupUpdate(is_king=1))

    def add_king(self, signup_id: int) -> KothSignupPublic:
        """Add a player as king of their bracket (keeps existing kings)"""
        return self._set_king(signup_id, 1)

    def unset_king(self, signup_id: int) -> KothSignupPublic:
        """Remove king status from a player"""
        return self._set_king(signup_id, 0)

    # ============ Match Methods ============
    def add_match(self, match: KothMatchCreate) -> KothMatchPublic:
        with Session.begin() as session:
            db_match = KothMatch.add(session, match.model_dump())
            return KothMatchPublic.model_validate(db_match)

    def update_match(self, match_id: int, match: KothMatchUpdate) -> KothMatchPublic:
        with Session.begin() as session:
            db_match = KothMatch.update(
                session, match_id, **match.model_dump(exclude_unset=True)
            )
            if not db_match:
                raise NotFoundError("KOTH Match not found")
            return KothMatchPublic.model_validate(db_match)

    def delete_match(self, match_id: int) -> None:
        with Session.begin() as session:
            KothMatch.delete(session, match_id)

    def get_match(self, match_id: int) -> KothMatchPublic:
        with Session.begin() as session:
            match = (
                session.scalars(
                    select(KothMatch)
                    .options(
                        joinedload(KothMatch.participants).joinedload(
                            KothMatchParticipant.signup
                        )
                    )
                    .where(col(KothMatch.id) == match_id)
                )
                .unique()
                .first()
            )
            if not match:
                raise NotFoundError(f"Match not found by Id: {match_id}")
            return KothMatchPublic.model_validate(match)

    def get_matches_by_event(
        self, event_id: int, limit: int | None = None, offset: int = 0
    ) -> list[KothMatchPublic]:
        with Session.begin() as session:
            statement = (
                select(KothMatch)
                .options(
                    joinedload(KothMatch.participants).joinedload(
                        KothMatchParticipant.signup
                    )
                )
                .where(col(KothMatch.event_id) == event_id)
                .order_by(col(KothMatch.bracket), col(KothMatch.id))
            )
            if limit is not None or offset:
                statement = statement.offset(offset)
                if limit is not None:
                    statement = statement.limit(limit)
            matches = session.scalars(statement).unique().all()
            return [KothMatchPublic.model_validate(m) for m in matches]

    def create_match(
        self, match: KothMatchCreate, participant_signup_ids: list[dict[str, int]]
    ) -> KothMatchPublic:
        """
        Create a team-based match with participants.
        participant_signup_ids: list of dicts with {'signup_id': int, 'team_number': int}
        """
        # Validate all participants exist and are in the same bracket
        signups = [
            self.get_signup(participant["signup_id"])
            for participant in participant_signup_ids
        ]

        # All must be in same bracket
        if signups:
            first_bracket = signups[0].bracket
            if not all(s.bracket == first_bracket for s in signups):
                raise BadRequestError("All participants must be in the same bracket")
            match.bracket = first_bracket

        # Validate team configuration - each team must have at least 1 player
        team_numbers = [p["team_number"] for p in participant_signup_ids]
        unique_teams = set(team_numbers)

        if len(unique_teams) != match.num_teams:
            raise BadRequestError(
                f"Expected {match.num_teams} teams, but participants are assigned to {len(unique_teams)} teams"
            )

        for team_num in range(1, match.num_teams + 1):
            if team_num not in unique_teams:
                raise BadRequestError(f"Team {team_num} has no participants")

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
        if winner_team_number < 1 or winner_team_number > match.num_teams:
            raise BadRequestError(
                f"Winner team number must be between 1 and {match.num_teams}"
            )

        updated_match = self.update_match(
            match.id, KothMatchUpdate(winner_team_number=winner_team_number)
        )

        # Get participants and set winners as kings
        participants = self.get_participants_by_match(match_id)

        self._clear_bracket_kings(match.event_id, match.bracket)

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
        with Session.begin() as session:
            db_participant = KothMatchParticipant.add(session, participant.model_dump())
            return KothMatchParticipantPublic.model_validate(db_participant)

    def get_participants_by_match(
        self, match_id: int
    ) -> list[KothMatchParticipantPublic]:
        with Session.begin() as session:
            participants = (
                session.scalars(
                    select(KothMatchParticipant)
                    .options(joinedload(KothMatchParticipant.signup))
                    .where(col(KothMatchParticipant.match_id) == match_id)
                    .order_by(col(KothMatchParticipant.team_number))
                )
                .unique()
                .all()
            )
            return [KothMatchParticipantPublic.model_validate(p) for p in participants]

    def get_bracket_kings(self, event_id: int) -> dict[int, list[KothSignupPublic]]:
        """Get all kings for each bracket"""
        kings: defaultdict[int, list[KothSignupPublic]] = defaultdict(list)
        for signup in self.get_signups_by_event(event_id):
            if signup.is_king == 1:
                kings[signup.bracket].append(signup)
        return kings

    # ============ Helper Methods ============
    def _check_duplicate_signup(
        self,
        session: OrmSession,
        event_id: int,
        twitch_username: str,
        race: str | None,
    ) -> None:
        """Raise when the player already has an active signup for this race.

        Without a race the player may hold one active signup only, because
        the race the W3C stats pick would repeat the signup they have.
        """
        active = session.scalars(
            select(KothSignup).where(
                col(KothSignup.event_id) == event_id,
                col(KothSignup.twitch_username) == twitch_username,
                col(KothSignup.is_active) == 1,
            )
        ).all()
        if not active:
            return
        if not race:
            raise BadRequestError(
                f"Player {twitch_username} already has an active signup. Specify a race to signup with a different race."
            )
        if any(signup.race == Race(race) for signup in active):
            raise BadRequestError(
                f"Player {twitch_username} already has an active signup with race {race}"
            )

    def _set_king(self, signup_id: int, value: int) -> KothSignupPublic:
        """Write the king flag of a signup."""
        self.get_signup(signup_id)  # 404 names the id
        return self.update_signup(signup_id, KothSignupUpdate(is_king=value))

    def _clear_bracket_kings(self, event_id: int, bracket: int) -> None:
        """Take the crown from every signup in the bracket."""
        with Session.begin() as session:
            session.execute(
                update(KothSignup)
                .where(
                    col(KothSignup.event_id) == event_id,
                    col(KothSignup.bracket) == bracket,
                )
                .values(is_king=0),
                execution_options={"synchronize_session": False},
            )

    def _determine_bracket(self, mmr: int, event: KothEventPublic) -> int:
        """Determine bracket based on MMR thresholds"""
        if mmr < event.bracket_1_threshold:
            return 1
        elif mmr < event.bracket_2_threshold:
            return 2
        else:
            return 3
