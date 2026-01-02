from sqlalchemy import Column, Integer, String, Sequence
from sqlalchemy.orm.session import Session
from src.database.model.DBModel import DBModel

class DBSettings(DBModel):
    __tablename__ = 'settings'
    
    id = Column(Integer, Sequence(f'{__tablename__}_id_seq'), primary_key=True)
    key = Column(String(255), unique=True, nullable=False, index=True)
    value = Column(String(1000), nullable=True)
    description = Column(String(500), nullable=True)
    
    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
    
    def __repr__(self):
        return f"<DBSettings(key='{self.key}', value='{self.value}')>"
    
    @classmethod
    def get_by_key(cls, session: Session, key):
        """Get a setting by its key"""
        return session.query(cls).filter_by(key=key).first()
    
    @classmethod
    def get_all_as_dict(cls, session: Session):
        """Get all settings as a dictionary"""
        settings = session.query(cls).all()
        return {s.key: s.value for s in settings}
