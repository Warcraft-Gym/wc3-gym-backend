"""Base class for the services that read and write the database."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session as OrmSession

from app.core.db import Session


class BaseService(ABC):
    """All services share the engine and session factory of the process,
    in app/core/db.py."""

    @contextmanager
    def get_session(self) -> Iterator[OrmSession]:
        """One transaction per call: commit on success, roll back on error,
        always close. Callers must not commit; to share a transaction, pass
        the session instead of opening a new one. A database error
        propagates as the SQLAlchemyError it is; the handler in app.main
        answers with a fixed message and logs what the database said."""
        with Session.begin() as session:
            yield session

    # Each service types these four for its own entity
    @abstractmethod
    def add(self, **kwargs: object) -> object:
        pass

    @abstractmethod
    def update(self, obj_id: object, **kwargs: object) -> object:
        pass

    @abstractmethod
    def delete(self, obj_id: object) -> object:
        pass

    @abstractmethod
    def get(self, obj_id: object) -> object:
        pass
