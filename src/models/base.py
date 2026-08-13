from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Session

from custom_exceptions import DBException


class Base(DeclarativeBase):
    pass


class DBModel(Base):
    """Shared query helpers for the mapped classes. It has no table of its own."""

    __abstract__ = True

    @classmethod
    def add(cls, session: Session, data: dict):
        obj = cls(**data)
        session.add(obj)
        session.flush()
        return obj

    @classmethod
    def update(cls, session: Session, obj_id, **kwargs):
        obj = cls.getById(session, obj_id)
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
        obj = cls.getById(session, obj_id)
        if obj:
            session.delete(obj)
            session.flush()
        return obj

    @classmethod
    def search(cls, session: Session, filters):
        if filters is None:
            raise DBException("No search criteria was defined!")
        return session.scalars(select(cls).where(filters)).unique().all()

    @classmethod
    def getAll(cls, session: Session):
        return session.scalars(select(cls)).unique().all()

    @classmethod
    def getById(cls, session: Session, id):
        # A request can leave the id out of the body. No row has a null
        # primary key, so answer with no object instead of asking the
        # database, which warns about a fully null primary key.
        if id is None:
            return None
        return session.get(cls, id)
