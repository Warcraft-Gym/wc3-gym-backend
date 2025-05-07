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
        self.engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=300)
        
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
            session.close()

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
