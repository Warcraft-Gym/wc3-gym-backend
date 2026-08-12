import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBKothEvent import DBKothEvent
from src.database.model.DBKothSignup import DBKothSignup
from src.database.model.DBKothMatch import DBKothMatch
from src.database.model.DBKothMatchParticipant import DBKothMatchParticipant
from src.schemas.koth_event import KothEvent
from src.schemas.koth_signup import KothSignup
from src.schemas.koth_match import KothMatch
from src.schemas.koth_match_participant import KothMatchParticipant
from sqlalchemy.orm import joinedload
from custom_exceptions import DBException

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
            event = session.query(DBKothEvent)\
                .options(
                    joinedload(DBKothEvent.signups),
                    joinedload(DBKothEvent.matches).joinedload(DBKothMatch.participants).joinedload(DBKothMatchParticipant.signup)
                )\
                .filter_by(id=event_id).first()
            if not event:
                return None
            return KothEvent.from_db_event(event)

    def get_all_events(self):
        with self.get_session() as session:
            events = session.query(DBKothEvent).all()
            return [KothEvent.from_db_event(e) for e in events]

    def get_active_event(self):
        with self.get_session() as session:
            event = session.query(DBKothEvent)\
                .options(
                    joinedload(DBKothEvent.signups),
                    joinedload(DBKothEvent.matches).joinedload(DBKothMatch.participants).joinedload(DBKothMatchParticipant.signup)
                )\
                .filter_by(is_active=True)\
                .first()
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
            signup = session.query(DBKothSignup).filter_by(id=signup_id).first()
            if not signup:
                return None
            return KothSignup.from_db_signup(signup)

    def get_signups_by_event(self, event_id):
        with self.get_session() as session:
            signups = session.query(DBKothSignup)\
                .filter_by(event_id=event_id)\
                .order_by(DBKothSignup.bracket, DBKothSignup.mmr.desc())\
                .all()
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
            match = session.query(DBKothMatch)\
                .options(
                    joinedload(DBKothMatch.participants).joinedload(DBKothMatchParticipant.signup)
                )\
                .filter_by(id=match_id).first()
            if not match:
                return None
            return KothMatch.from_db_match(match)

    def get_matches_by_event(self, event_id):
        with self.get_session() as session:
            matches = session.query(DBKothMatch)\
                .options(
                    joinedload(DBKothMatch.participants).joinedload(DBKothMatchParticipant.signup)
                )\
                .filter_by(event_id=event_id)\
                .order_by(DBKothMatch.bracket, DBKothMatch.id)\
                .all()
            return [KothMatch.from_db_match(m) for m in matches]

    # ============ Match Participant Methods ============
    def add_participant(self, participant: KothMatchParticipant):
        with self.get_session() as session:
            db_participant = DBKothMatchParticipant.add(session, participant.to_db_dict())
            if not db_participant:
                raise DBException("KOTH Match Participant could not be created!")
            return KothMatchParticipant.from_db_participant(db_participant)

    def delete_participants_by_match(self, match_id):
        """Delete all participants for a given match"""
        with self.get_session() as session:
            session.query(DBKothMatchParticipant)\
                .filter_by(match_id=match_id)\
                .delete(synchronize_session=False)

    def get_participants_by_match(self, match_id):
        with self.get_session() as session:
            participants = session.query(DBKothMatchParticipant)\
                .options(joinedload(DBKothMatchParticipant.signup))\
                .filter_by(match_id=match_id)\
                .order_by(DBKothMatchParticipant.team_number)\
                .all()
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
