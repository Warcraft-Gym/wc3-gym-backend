import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload

from app.database.abstract_database_service import AbstractDatabaseService
from app.exceptions import DBException
from app.models.koth_event import DBKothEvent
from app.models.koth_match import DBKothMatch
from app.models.koth_match_participant import DBKothMatchParticipant
from app.models.koth_signup import DBKothSignup
from app.schemas.koth_event import KothEvent
from app.schemas.koth_match import KothMatch
from app.schemas.koth_match_participant import KothMatchParticipant
from app.schemas.koth_signup import KothSignup

logger = logging.getLogger(__name__)


class KothDBService(AbstractDatabaseService):
    # ============ Event Methods ============
    def add_event(self, event: KothEvent):
        with self.get_session() as session:
            db_event = DBKothEvent.add(session, event.to_db_dict())
            if not db_event:
                raise DBException("KOTH Event could not be created!")
            return KothEvent.from_db_event(db_event)

    def update_event(self, event: KothEvent):
        with self.get_session() as session:
            db_event = DBKothEvent.update(session, event.id, **event.to_db_dict())
            if not db_event:
                raise DBException("KOTH Event could not be updated")
            return KothEvent.from_db_event(db_event)

    def delete_event(self, event_id):
        with self.get_session() as session:
            DBKothEvent.delete(session, event_id)

    def get_event(self, event_id):
        with self.get_session() as session:
            event = (
                session.scalars(
                    select(DBKothEvent)
                    .options(
                        joinedload(DBKothEvent.signups),
                        joinedload(DBKothEvent.matches)
                        .joinedload(DBKothMatch.participants)
                        .joinedload(DBKothMatchParticipant.signup),
                    )
                    .where(DBKothEvent.id == event_id)
                )
                .unique()
                .first()
            )
            if not event:
                return None
            return KothEvent.from_db_event(event)

    def get_all_events(self):
        with self.get_session() as session:
            events = session.scalars(select(DBKothEvent)).unique().all()
            return [KothEvent.from_db_event(e) for e in events]

    def get_active_event(self):
        with self.get_session() as session:
            # Pick the one event id first. A LIMIT on the outer select would
            # cut the joined signup and match rows, so the limit belongs in a
            # subquery, which is also what the old Query.first() built.
            active_event_id = (
                select(DBKothEvent.id)
                .where(DBKothEvent.is_active == True)
                .limit(1)
                .scalar_subquery()
            )
            event = (
                session.scalars(
                    select(DBKothEvent)
                    .options(
                        joinedload(DBKothEvent.signups),
                        joinedload(DBKothEvent.matches)
                        .joinedload(DBKothMatch.participants)
                        .joinedload(DBKothMatchParticipant.signup),
                    )
                    .where(DBKothEvent.id == active_event_id)
                )
                .unique()
                .first()
            )
            if not event:
                return None
            return KothEvent.from_db_event(event)

    # ============ Signup Methods ============
    def add_signup(self, signup: KothSignup):
        with self.get_session() as session:
            db_signup = DBKothSignup.add(session, signup.to_db_dict())
            if not db_signup:
                raise DBException("KOTH Signup could not be created!")
            return KothSignup.from_db_signup(db_signup)

    def update_signup(self, signup: KothSignup):
        with self.get_session() as session:
            db_signup = DBKothSignup.update(session, signup.id, **signup.to_db_dict())
            if not db_signup:
                raise DBException("KOTH Signup could not be updated")
            return KothSignup.from_db_signup(db_signup)

    def delete_signup(self, signup_id):
        with self.get_session() as session:
            DBKothSignup.delete(session, signup_id)

    def get_signup(self, signup_id):
        with self.get_session() as session:
            signup = session.get(DBKothSignup, signup_id)
            if not signup:
                return None
            return KothSignup.from_db_signup(signup)

    def get_signups_by_event(self, event_id):
        with self.get_session() as session:
            signups = (
                session.scalars(
                    select(DBKothSignup)
                    .where(DBKothSignup.event_id == event_id)
                    .order_by(DBKothSignup.bracket, DBKothSignup.mmr.desc())
                )
                .unique()
                .all()
            )
            return [KothSignup.from_db_signup(s) for s in signups]

    # ============ Match Methods ============
    def add_match(self, match: KothMatch):
        with self.get_session() as session:
            db_match = DBKothMatch.add(session, match.to_db_dict())
            if not db_match:
                raise DBException("KOTH Match could not be created!")
            return KothMatch.from_db_match(db_match)

    def update_match(self, match: KothMatch):
        with self.get_session() as session:
            db_match = DBKothMatch.update(session, match.id, **match.to_db_dict())
            if not db_match:
                raise DBException("KOTH Match could not be updated")
            return KothMatch.from_db_match(db_match)

    def delete_match(self, match_id):
        with self.get_session() as session:
            DBKothMatch.delete(session, match_id)

    def get_match(self, match_id):
        with self.get_session() as session:
            match = (
                session.scalars(
                    select(DBKothMatch)
                    .options(
                        joinedload(DBKothMatch.participants).joinedload(
                            DBKothMatchParticipant.signup
                        )
                    )
                    .where(DBKothMatch.id == match_id)
                )
                .unique()
                .first()
            )
            if not match:
                return None
            return KothMatch.from_db_match(match)

    def get_matches_by_event(self, event_id):
        with self.get_session() as session:
            matches = (
                session.scalars(
                    select(DBKothMatch)
                    .options(
                        joinedload(DBKothMatch.participants).joinedload(
                            DBKothMatchParticipant.signup
                        )
                    )
                    .where(DBKothMatch.event_id == event_id)
                    .order_by(DBKothMatch.bracket, DBKothMatch.id)
                )
                .unique()
                .all()
            )
            return [KothMatch.from_db_match(m) for m in matches]

    # ============ Match Participant Methods ============
    def add_participant(self, participant: KothMatchParticipant):
        with self.get_session() as session:
            db_participant = DBKothMatchParticipant.add(
                session, participant.to_db_dict()
            )
            if not db_participant:
                raise DBException("KOTH Match Participant could not be created!")
            return KothMatchParticipant.from_db_participant(db_participant)

    def delete_participants_by_match(self, match_id):
        """Delete all participants for a given match"""
        with self.get_session() as session:
            session.execute(
                delete(DBKothMatchParticipant).where(
                    DBKothMatchParticipant.match_id == match_id
                ),
                execution_options={"synchronize_session": False},
            )

    def get_participants_by_match(self, match_id):
        with self.get_session() as session:
            participants = (
                session.scalars(
                    select(DBKothMatchParticipant)
                    .options(joinedload(DBKothMatchParticipant.signup))
                    .where(DBKothMatchParticipant.match_id == match_id)
                    .order_by(DBKothMatchParticipant.team_number)
                )
                .unique()
                .all()
            )
            return [KothMatchParticipant.from_db_participant(p) for p in participants]

    # Required abstract methods
    def get(self, obj_id):
        pass

    def add(self, **kwargs):
        pass

    def update(self, obj_id, **kwargs):
        pass

    def delete(self, obj_id):
        pass
