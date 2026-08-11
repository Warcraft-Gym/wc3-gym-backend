from abc import ABC, abstractmethod
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.model.DBModel import Base
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager

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
        self.Session = scoped_session(sessionmaker(bind=self.engine))

    @contextmanager
    def get_session(self):
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            self.Session.remove()  # remove() closes + purges from thread-local registry

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
