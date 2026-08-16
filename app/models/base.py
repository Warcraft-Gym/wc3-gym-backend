from collections.abc import Sequence
from typing import Any, Self

from sqlalchemy import ColumnExpressionArgument, select
from sqlalchemy.orm import Session
from sqlmodel import SQLModel


class DBModel(SQLModel):
    """Shared query helpers for the mapped classes. It has no table of its own."""

    @classmethod
    def add(cls, session: Session, data: dict[str, Any]) -> Self:
        obj = cls(**data)
        session.add(obj)
        session.flush()
        return obj

    @classmethod
    def update(
        cls, session: Session, obj_id: int | None, **kwargs: object
    ) -> Self | None:
        obj = cls.getById(session, obj_id)
        if obj:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            session.flush()
        return obj

    @classmethod
    def updateObject(
        cls, session: Session, obj: Self | None, **kwargs: object
    ) -> Self | None:
        if obj:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            session.flush()
        return obj

    @classmethod
    def delete(cls, session: Session, obj_id: int | None) -> Self | None:
        obj = cls.getById(session, obj_id)
        if obj:
            session.delete(obj)
            session.flush()
        return obj

    @classmethod
    def search(
        cls, session: Session, filters: ColumnExpressionArgument[bool] | None
    ) -> Sequence[Self]:
        if filters is None:
            raise ValueError("No search criteria was defined!")
        return session.scalars(select(cls).where(filters)).unique().all()

    @classmethod
    def getAll(cls, session: Session) -> Sequence[Self]:
        return session.scalars(select(cls)).unique().all()

    @classmethod
    def getById(cls, session: Session, id: int | None) -> Self | None:
        # No row has a null primary key, and session.get warns on one
        if id is None:
            return None
        return session.get(cls, id)
