import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBKothEvent import DBKothEvent
from src.database.model.DBKothSignup import DBKothSignup
from src.database.model.DBKothMatch import DBKothMatch
from src.database.model.DBKothMatchParticipant import DBKothMatchParticipant
from src.dtos.koth_event_dto import KothEventDTO
from src.dtos.koth_signup_dto import KothSignupDTO
from src.dtos.koth_match_dto import KothMatchDTO
from src.dtos.koth_match_participant_dto import KothMatchParticipantDTO
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from custom_exceptions import DBException

logger = logging.getLogger(__name__)

class KothDBService(AbstractDatabaseService):
    # ============ Event Methods ============
    def add_event(self, event: KothEventDTO):
        with self.get_session() as session:
            try:
                db_event = DBKothEvent.add(session, event.to_db_dict())
                if not db_event:
                    raise DBException("KOTH Event could not be created!")
                return KothEventDTO.from_db_event(db_event)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def update_event(self, event: KothEventDTO):
        with self.get_session() as session:
            try:
                db_event = DBKothEvent.update(session, event.id, **event.to_db_dict())
                if not db_event:
                    raise DBException("KOTH Event could not be updated")
                return KothEventDTO.from_db_event(db_event)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def delete_event(self, event_id):
        with self.get_session() as session:
            try:
                DBKothEvent.delete(session, event_id)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get_event(self, event_id):
        with self.get_session() as session:
            try:
                event = session.query(DBKothEvent)\
                    .options(
                        joinedload(DBKothEvent.signups),
                        joinedload(DBKothEvent.matches).joinedload(DBKothMatch.participants).joinedload(DBKothMatchParticipant.signup)
                    )\
                    .filter_by(id=event_id).first()
                if not event:
                    return None
                return KothEventDTO.from_db_event(event)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get_all_events(self):
        with self.get_session() as session:
            try:
                events = session.query(DBKothEvent).all()
                return [KothEventDTO.from_db_event(e) for e in events]
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get_active_event(self):
        with self.get_session() as session:
            try:
                event = session.query(DBKothEvent)\
                    .options(
                        joinedload(DBKothEvent.signups),
                        joinedload(DBKothEvent.matches).joinedload(DBKothMatch.participants).joinedload(DBKothMatchParticipant.signup)
                    )\
                    .filter_by(is_active=True)\
                    .first()
                if not event:
                    return None
                return KothEventDTO.from_db_event(event)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    # ============ Signup Methods ============
    def add_signup(self, signup: KothSignupDTO):
        with self.get_session() as session:
            try:
                db_signup = DBKothSignup.add(session, signup.to_db_dict())
                if not db_signup:
                    raise DBException("KOTH Signup could not be created!")
                return KothSignupDTO.from_db_signup(db_signup)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def update_signup(self, signup: KothSignupDTO):
        with self.get_session() as session:
            try:
                db_signup = DBKothSignup.update(session, signup.id, **signup.to_db_dict())
                if not db_signup:
                    raise DBException("KOTH Signup could not be updated")
                return KothSignupDTO.from_db_signup(db_signup)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def delete_signup(self, signup_id):
        with self.get_session() as session:
            try:
                DBKothSignup.delete(session, signup_id)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get_signup(self, signup_id):
        with self.get_session() as session:
            try:
                signup = session.query(DBKothSignup).filter_by(id=signup_id).first()
                if not signup:
                    return None
                return KothSignupDTO.from_db_signup(signup)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get_signups_by_event(self, event_id):
        with self.get_session() as session:
            try:
                signups = session.query(DBKothSignup)\
                    .filter_by(event_id=event_id)\
                    .order_by(DBKothSignup.bracket, DBKothSignup.mmr.desc())\
                    .all()
                return [KothSignupDTO.from_db_signup(s) for s in signups]
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    # ============ Match Methods ============
    def add_match(self, match: KothMatchDTO):
        with self.get_session() as session:
            try:
                db_match = DBKothMatch.add(session, match.to_db_dict())
                if not db_match:
                    raise DBException("KOTH Match could not be created!")
                return KothMatchDTO.from_db_match(db_match)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def update_match(self, match: KothMatchDTO):
        with self.get_session() as session:
            try:
                db_match = DBKothMatch.update(session, match.id, **match.to_db_dict())
                if not db_match:
                    raise DBException("KOTH Match could not be updated")
                return KothMatchDTO.from_db_match(db_match)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def delete_match(self, match_id):
        with self.get_session() as session:
            try:
                DBKothMatch.delete(session, match_id)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get_match(self, match_id):
        with self.get_session() as session:
            try:
                match = session.query(DBKothMatch)\
                    .options(
                        joinedload(DBKothMatch.participants).joinedload(DBKothMatchParticipant.signup)
                    )\
                    .filter_by(id=match_id).first()
                if not match:
                    return None
                return KothMatchDTO.from_db_match(match)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get_matches_by_event(self, event_id):
        with self.get_session() as session:
            try:
                matches = session.query(DBKothMatch)\
                    .options(
                        joinedload(DBKothMatch.participants).joinedload(DBKothMatchParticipant.signup)
                    )\
                    .filter_by(event_id=event_id)\
                    .order_by(DBKothMatch.bracket, DBKothMatch.id)\
                    .all()
                return [KothMatchDTO.from_db_match(m) for m in matches]
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    # ============ Match Participant Methods ============
    def add_participant(self, participant: KothMatchParticipantDTO):
        with self.get_session() as session:
            try:
                db_participant = DBKothMatchParticipant.add(session, participant.to_db_dict())
                if not db_participant:
                    raise DBException("KOTH Match Participant could not be created!")
                return KothMatchParticipantDTO.from_db_participant(db_participant)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def delete_participants_by_match(self, match_id):
        """Delete all participants for a given match"""
        with self.get_session() as session:
            try:
                session.query(DBKothMatchParticipant)\
                    .filter_by(match_id=match_id)\
                    .delete(synchronize_session=False)
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    def get_participants_by_match(self, match_id):
        with self.get_session() as session:
            try:
                participants = session.query(DBKothMatchParticipant)\
                    .options(joinedload(DBKothMatchParticipant.signup))\
                    .filter_by(match_id=match_id)\
                    .order_by(DBKothMatchParticipant.team_number)\
                    .all()
                return [KothMatchParticipantDTO.from_db_participant(p) for p in participants]
            except SQLAlchemyError as e:
                logger.error(f"Database error: {e}")
                raise DBException(f"Database error: {e}")

    # Required abstract methods
    def get(self, obj_id):
        pass

    def add(self, **kwargs):
        pass

    def update(self, obj_id, **kwargs):
        pass

    def delete(self, obj_id):
        pass
