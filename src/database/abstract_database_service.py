from abc import ABC, abstractmethod
from contextlib import contextmanager
import logging

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from src.database.model.DBModel import Base
from custom_exceptions import DBException

logger = logging.getLogger(__name__)

class AbstractDatabaseService(ABC):
    def __init__(self, db_url):
        # Optimize connection pooling for better performance
        self.engine = create_engine(
            db_url,
            pool_size=10,              # Maintain 10 persistent connections
            max_overflow=20,           # Allow up to 20 extra connections during peak
            pool_pre_ping=True,        # Verify connections before using
            pool_recycle=3600,         # Recycle connections every hour
            echo=False                  # Disable SQL logging for performance
        )
        
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    @contextmanager
    def get_session(self):
        """One transaction per call: commit on success, roll back on error,
        always close. Callers must not commit; to share a transaction, pass
        the session instead of opening a new one. Database errors become
        DBException here and nowhere else."""
        try:
            with self.Session.begin() as session:
                yield session
        except SQLAlchemyError as e:
            logger.exception("Database error")
            raise DBException(f"Database error: {e}") from e

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
