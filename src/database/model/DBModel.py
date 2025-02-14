from sqlalchemy import Column, Integer, String, Sequence, ForeignKey
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.orm.session import Session
from sqlalchemy.ext.declarative import AbstractConcreteBase

Base = declarative_base()

class DBModel(AbstractConcreteBase, Base):

    @classmethod
    def add(cls, session: Session, data : dict):
        obj = cls(**data)
        session.add(obj)
        session.commit()
        return obj

    @classmethod
    def update(cls, session: Session, obj_id, **kwargs):
        obj = session.query(cls).filter_by(id=obj_id).first()
        if obj:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            session.commit()
        return obj

    @classmethod
    def delete(cls, session: Session, obj_id):
        obj = session.query(cls).filter_by(id=obj_id).first()
        if obj:
            session.delete(obj)
            session.commit()
        return obj
