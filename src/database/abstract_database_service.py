from abc import ABC, abstractmethod
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.model.DBModel import Base
import logging

logger = logging.getLogger(__name__)

class AbstractDatabaseService(ABC):
    def __init__(self, db_url):
        self.engine = create_engine(db_url)
        logger.debug("DB URL: " + db_url)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

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
