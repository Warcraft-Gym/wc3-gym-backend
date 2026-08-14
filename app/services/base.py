"""Base class for the services that read and write the database."""

import logging
from abc import ABC, abstractmethod
from contextlib import contextmanager

from sqlalchemy.exc import SQLAlchemyError

from app.core.db import Session
from app.exceptions import DBException

logger = logging.getLogger(__name__)


class BaseService(ABC):
    """All services share the engine and session factory of the process,
    in app/core/db.py."""

    @contextmanager
    def get_session(self):
        """One transaction per call: commit on success, roll back on error,
        always close. Callers must not commit; to share a transaction, pass
        the session instead of opening a new one. Database errors become
        DBException here and nowhere else.

        The message is fixed because the API sends it to the client. What
        the database said, including the statement, goes to the log."""
        try:
            with Session.begin() as session:
                yield session
        except SQLAlchemyError as e:
            logger.exception("Database error")
            raise DBException("Database error") from e

    @abstractmethod
    def add(self, **kwargs):
        pass

    @abstractmethod
    def update(self, obj_id, **kwargs):
        pass

    @abstractmethod
    def delete(self, obj_id):
        pass

    @abstractmethod
    def get(self, obj_id):
        pass
