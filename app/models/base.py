from collections.abc import Sequence
from typing import Any, Self

from sqlalchemy import ColumnExpressionArgument, select
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from app.core.exceptions import BadRequestError


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
        obj = cls.get_by_id(session, obj_id)
        if obj:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            session.flush()
        return obj

    @classmethod
    def update_object(
        cls, session: Session, obj: Self | None, **kwargs: object
    ) -> Self | None:
        if obj:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            session.flush()
        return obj

    @classmethod
    def delete(cls, session: Session, obj_id: int | None) -> Self | None:
        obj = cls.get_by_id(session, obj_id)
        if obj:
            session.delete(obj)
            session.flush()
        return obj

    @classmethod
    def search(
        cls,
        session: Session,
        filters: ColumnExpressionArgument[bool] | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[Self]:
        if filters is None:
            raise BadRequestError("No search criteria was defined!")
        statement = select(cls).where(filters)
        if limit is not None or offset:
            # Offset paging is deterministic only with a fixed order
            statement = statement.order_by(*cls.__table__.primary_key).offset(offset)
            if limit is not None:
                statement = statement.limit(limit)
        return session.scalars(statement).unique().all()

    @classmethod
    def get_all(
        cls, session: Session, limit: int | None = None, offset: int = 0
    ) -> Sequence[Self]:
        statement = select(cls)
        if limit is not None or offset:
            # Offset paging is deterministic only with a fixed order
            statement = statement.order_by(*cls.__table__.primary_key).offset(offset)
            if limit is not None:
                statement = statement.limit(limit)
        return session.scalars(statement).unique().all()

    @classmethod
    def get_by_id(cls, session: Session, id: int | None) -> Self | None:
        # No row has a null primary key, and session.get warns on one
        if id is None:
            return None
        return session.get(cls, id)
