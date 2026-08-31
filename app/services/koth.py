import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload
from sqlmodel import col

from app.core.db import Session, rel
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.base import ident
from app.models.enums import Race
from app.models.koth_event import (
    KothEvent,
    KothEventCreate,
    KothEventPublic,
    KothEventSummary,
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
)
from app.models.koth_signup import (
    KothSignup,
    KothSignupCreate,
    KothSignupPublic,
    KothSignupUpdate,
)
from app.models.user import User
from app.services.w3c import W3CService

if TYPE_CHECKING:
    from app.services.settings import SettingsService

logger = logging.getLogger(__name__)

# The full tree KothEventPublic serializes; without it every event lazy-loads
# its signups and matches one query at a time
EVENT_TREE = (
    joinedload(rel(KothEvent.signups)),
    joinedload(rel(KothEvent.matches))
    .joinedload(rel(KothMatch.participants))
    .joinedload(rel(KothMatchParticipant.signup)),
)


class KothService:
    def __init__(self, settings_app_service: "SettingsService") -> None:
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
                    .options(*EVENT_TREE)
                    .where(col(KothEvent.id) == event_id)
                )
                .unique()
                .first()
            )
            if not event:
                raise NotFoundError(f"KOTH Event not found by Id: {event_id}")
            public = KothEventPublic.model_validate(event)
            self._add_countries(session, public.signups)
            return public

    def get_all_events(self) -> list[KothEventSummary]:
        with Session.begin() as session:
            events = session.scalars(select(KothEvent)).all()
            return [KothEventSummary.model_validate(e) for e in events]

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
                    .options(*EVENT_TREE)
                    .where(col(KothEvent.id) == active_event_id)
                )
                .unique()
                .first()
            )
            if not event:
                raise NotFoundError("No active KOTH event found")
            public = KothEventPublic.model_validate(event)
            self._add_countries(session, public.signups)
            return public

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
                # The id breaks the ties the bracket and mmr order leaves
                .order_by(col(KothSignup.id))
                .offset(offset)
                .limit(limit)
            )
            signups = session.scalars(statement).unique().all()
            return self._add_countries(
                session, [KothSignupPublic.model_validate(s) for s in signups]
            )

    def create_signups(
        self,
        twitch_username: str,
        battle_tag: str,
        races: list[str] | None = None,
    ) -> list[KothSignupPublic]:
        """Sign a player up for the active event, one signup per race.

        Each race carries its own W3C MMR and lands in the bracket that MMR
        cuts into, so one player can sit in several brackets. An empty race
        list lets the W3C stats pick the player's highest-MMR race.
        """
        signup_races: list[str] = []
        for race in races or []:
            try:
                value = Race.from_text(race).value
            except ValueError as error:
                raise BadRequestError(
                    f"Invalid race '{race}'. Valid options: orc, human, undead, nightelf, random"
                ) from error
            if value not in signup_races:
                signup_races.append(value)

        event = self.get_active_event()

        # The W3C calls below take seconds, so the insert checks this again
        with Session.begin() as session:
            self._check_duplicate_signup(session, event.id, battle_tag, signup_races)

        race_mmr = self._read_race_mmr(battle_tag, signup_races)

        if signup_races:
            missing = [race for race in signup_races if race not in race_mmr]
            if missing:
                raise BadRequestError(
                    f"No W3Champions statistics found for {battle_tag} with race"
                    f" {', '.join(missing)} in the last 3 seasons"
                )
            chosen = signup_races
        else:
            if not race_mmr:
                raise BadRequestError(
                    f"No valid MMR data found for {battle_tag} in the last 3 seasons"
                )
            chosen = [max(race_mmr, key=lambda race: race_mmr[race])]

        new_signups = [
            KothSignupCreate(
                event_id=event.id,
                twitch_username=twitch_username,
                battle_tag=battle_tag,
                w3c_name=battle_tag,
                race=race,
                mmr=race_mmr[race],
                bracket=self._determine_bracket(race_mmr[race], event),
                is_king=0,
                is_active=1,
            )
            for race in chosen
        ]

        with Session.begin() as session:
            self._check_duplicate_signup(session, event.id, battle_tag, signup_races)
            try:
                rows = [
                    KothSignup.add(session, signup.model_dump())
                    for signup in new_signups
                ]
            except IntegrityError as error:
                # The unique index holds where the check cannot: two signups at once
                raise BadRequestError(
                    f"Player {battle_tag} already has an active signup with race"
                    f" {', '.join(chosen)}"
                ) from error
            return [KothSignupPublic.model_validate(row) for row in rows]

    def _read_race_mmr(self, battle_tag: str, races: list[str]) -> dict[str, int]:
        """The MMR of each race the player has played, taken from the newest of
        the last 3 seasons that names it."""
        w3c_service = W3CService(settings_app_service=self.settings_app_service)
        race_mmr: dict[str, int] = {}
        current_season = w3c_service.current_season()
        for season_offset in range(3):
            season = current_season - season_offset
            try:
                stats = w3c_service.get_player_stats(battle_tag, season_override=season)
            except Exception as error:
                logger.debug(f"No stats for {battle_tag} in season {season}: {error}")
                continue
            for stat in stats or []:
                if stat.race and stat.mmr and stat.mmr > 0:
                    race_mmr.setdefault(stat.race.value, stat.mmr)
            if races:
                if all(race in race_mmr for race in races):
                    break
            elif race_mmr:
                break
        return race_mmr

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
        with Session.begin() as session:
            signup = session.get(KothSignup, signup_id)
            if not signup:
                raise NotFoundError(f"Signup not found by Id: {signup_id}")
            self._clear_bracket_kings(session, signup.event_id, signup.bracket)
            signup.is_king = 1
            session.flush()
            return KothSignupPublic.model_validate(signup)

    def add_king(self, signup_id: int) -> KothSignupPublic:
        """Add a player as king of their bracket (keeps existing kings)"""
        return self._set_king(signup_id, 1)

    def unset_king(self, signup_id: int) -> KothSignupPublic:
        """Remove king status from a player"""
        return self._set_king(signup_id, 0)

    # ============ Match Methods ============
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
                        joinedload(rel(KothMatch.participants)).joinedload(
                            rel(KothMatchParticipant.signup)
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
                    joinedload(rel(KothMatch.participants)).joinedload(
                        rel(KothMatchParticipant.signup)
                    )
                )
                .where(col(KothMatch.event_id) == event_id)
                .order_by(col(KothMatch.bracket), col(KothMatch.id))
                .offset(offset)
                .limit(limit)
            )
            matches = session.scalars(statement).unique().all()
            return [KothMatchPublic.model_validate(m) for m in matches]

    def create_match(
        self, match: KothMatchCreate, participant_signup_ids: list[dict[str, int]]
    ) -> KothMatchPublic:
        """
        Create a team-based match with participants, in one transaction.
        participant_signup_ids: list of dicts with {'signup_id': int, 'team_number': int}
        """
        with Session.begin() as session:
            signups = []
            for participant in participant_signup_ids:
                signup = session.get(KothSignup, participant["signup_id"])
                if not signup:
                    raise NotFoundError(
                        f"Signup not found by Id: {participant['signup_id']}"
                    )
                signups.append(signup)

            # All must be in same bracket
            if signups:
                first_bracket = signups[0].bracket
                if not all(s.bracket == first_bracket for s in signups):
                    raise BadRequestError(
                        "All participants must be in the same bracket"
                    )
                match.bracket = first_bracket

            # Validate team configuration - each team must have at least 1 player
            unique_teams = {p["team_number"] for p in participant_signup_ids}
            if len(unique_teams) != match.num_teams:
                raise BadRequestError(
                    f"Expected {match.num_teams} teams, but participants are assigned to {len(unique_teams)} teams"
                )
            for team_num in range(1, match.num_teams + 1):
                if team_num not in unique_teams:
                    raise BadRequestError(f"Team {team_num} has no participants")

            db_match = KothMatch.add(session, match.model_dump())
            session.flush()
            match_id = ident(db_match)
            for participant in participant_signup_ids:
                KothMatchParticipant.add(
                    session,
                    KothMatchParticipantCreate(
                        match_id=match_id,
                        signup_id=participant["signup_id"],
                        team_number=participant["team_number"],
                    ).model_dump(),
                )

        # Return match with participants loaded
        return self.get_match(match_id)

    def update_match_result(
        self, match_id: int, winner_team_number: int
    ) -> KothMatchPublic:
        """Update match winner, set all winning team members as kings, and delete losing participant signups"""
        with Session.begin() as session:
            match = session.scalars(
                select(KothMatch)
                .options(joinedload(rel(KothMatch.participants)))
                .where(col(KothMatch.id) == match_id)
            ).first()
            if not match:
                raise NotFoundError(f"Match not found by Id: {match_id}")
            if winner_team_number < 1 or winner_team_number > match.num_teams:
                raise BadRequestError(
                    f"Winner team number must be between 1 and {match.num_teams}"
                )

            match.winner_team_number = winner_team_number
            self._clear_bracket_kings(session, match.event_id, match.bracket)

            # Winning team members become kings; losing signups go inactive
            # so those players can sign up again
            winners = [
                p.signup_id
                for p in match.participants
                if p.team_number == winner_team_number
            ]
            losers = [
                p.signup_id
                for p in match.participants
                if p.team_number != winner_team_number
            ]
            if winners:
                session.execute(
                    update(KothSignup)
                    .where(col(KothSignup.id).in_(winners))
                    .values(is_king=1),
                    execution_options={"synchronize_session": False},
                )
            if losers:
                session.execute(
                    update(KothSignup)
                    .where(col(KothSignup.id).in_(losers))
                    .values(is_active=0),
                    execution_options={"synchronize_session": False},
                )

        return self.get_match(match_id)

    def get_bracket_kings(self, event_id: int) -> dict[int, list[KothSignupPublic]]:
        """Get all kings for each bracket"""
        kings: defaultdict[int, list[KothSignupPublic]] = defaultdict(list)
        for signup in self.get_signups_by_event(event_id):
            if signup.is_king == 1:
                kings[signup.bracket].append(signup)
        return kings

    # ============ Helper Methods ============
    @staticmethod
    def _add_countries(
        session: OrmSession, signups: list[KothSignupPublic]
    ) -> list[KothSignupPublic]:
        """Fill each signup's country from the users row with its battle tag."""
        tags = {s.battle_tag.strip().lower() for s in signups if s.battle_tag}
        if not tags:
            return signups
        folded = func.lower(func.trim(col(User.battleTag)))
        rows = session.execute(
            select(folded, col(User.country)).where(folded.in_(tags))
        ).all()
        countries = {tag: country for tag, country in rows}
        for signup in signups:
            if signup.battle_tag:
                signup.country = countries.get(signup.battle_tag.strip().lower())
        return signups

    def _check_duplicate_signup(
        self,
        session: OrmSession,
        event_id: int,
        battle_tag: str,
        races: list[str],
    ) -> None:
        """Raise when the player already has an active signup for one of these races.

        The battle tag is the player, because a Twitch name is blank on an admin
        or profile signup. Without a race the player may hold one active signup
        only, because the race the W3C stats pick would repeat the signup they have.
        """
        active = session.scalars(
            select(KothSignup).where(
                col(KothSignup.event_id) == event_id,
                func.lower(func.trim(col(KothSignup.battle_tag)))
                == battle_tag.strip().lower(),
                col(KothSignup.is_active) == 1,
            )
        ).all()
        if not active:
            return
        if not races:
            raise BadRequestError(
                f"Player {battle_tag} already has an active signup. Specify a race to signup with a different race."
            )
        taken = [
            race
            for race in races
            if any(signup.race == Race(race) for signup in active)
        ]
        if taken:
            raise BadRequestError(
                f"Player {battle_tag} already has an active signup with race {', '.join(taken)}"
            )

    def _set_king(self, signup_id: int, value: int) -> KothSignupPublic:
        """Write the king flag of a signup."""
        self.get_signup(signup_id)  # 404 names the id
        return self.update_signup(signup_id, KothSignupUpdate(is_king=value))

    def _clear_bracket_kings(
        self, session: OrmSession, event_id: int, bracket: int
    ) -> None:
        """Take the crown from every signup in the bracket, in the caller's transaction."""
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
