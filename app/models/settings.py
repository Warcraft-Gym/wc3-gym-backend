from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlmodel import Field

from app.models.base import DBModel


class DBSettings(DBModel, table=True):
    __tablename__ = "settings"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(max_length=255, unique=True, index=True)
    value: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=500)

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }

    def __repr__(self):
        return f"<DBSettings(key='{self.key}', value='{self.value}')>"

    @classmethod
    def get_by_key(cls, session: Session, key):
        """Get a setting by its key"""
        return session.scalars(select(cls).where(cls.key == key).limit(1)).first()

    @classmethod
    def get_all_as_dict(cls, session: Session):
        """Get all settings as a dictionary"""
        settings = session.scalars(select(cls)).all()
        return {s.key: s.value for s in settings}
