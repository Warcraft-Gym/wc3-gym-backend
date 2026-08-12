from sqlalchemy import Column, Integer, String, Sequence, ForeignKey, or_, and_
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.orm.session import Session
from sqlalchemy.ext.declarative import AbstractConcreteBase
from custom_exceptions import DBException

Base = declarative_base()

class DBModel(AbstractConcreteBase, Base):

    @classmethod
    def add(cls, session: Session, data : dict):
        obj = cls(**data)
        session.add(obj)
        session.flush()
        return obj

    @classmethod
    def update(cls, session: Session, obj_id, **kwargs):
        obj = session.query(cls).filter_by(id=obj_id).first()
        if obj:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            session.flush()
        return obj

    @classmethod
    def updateObject(cls, session: Session, obj, **kwargs):
        if obj:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            session.flush()
        return obj

    @classmethod
    def delete(cls, session: Session, obj_id):
        obj = session.query(cls).filter_by(id=obj_id).first()
        if obj:
            session.delete(obj)
            session.flush()
        return obj

    @classmethod
    def search(cls, session: Session, filters):
        if filters is None:
            raise DBException(f"No search criteria was defined!")
        query = session.query(cls).filter(filters)
        return query.all()
    
    @classmethod
    def getAll(cls, session: Session):
        return session.query(cls).all()
    
    @classmethod
    def getById(cls, session: Session, id):
        return session.query(cls).filter_by(id=id).first()