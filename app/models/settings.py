from typing import Annotated, Any, Self

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlmodel import Field, SQLModel

from app.models.base import DBModel
from app.models.types import NumToStr


class SettingsBase(SQLModel):
    key: str = Field(max_length=255, unique=True, index=True)
    # A setting value is a string in the database, and callers pass numbers.
    value: Annotated[str | None, NumToStr] = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=500)


class Settings(SettingsBase, DBModel, table=True):
    __tablename__ = "settings"

    id: int | None = Field(default=None, primary_key=True)

    def __repr__(self) -> str:
        return f"<Settings(key='{self.key}', value='{self.value}')>"

    @classmethod
    def get_by_key(cls, session: Session, key: str) -> Self | None:
        """Get a setting by its key"""
        return session.scalars(select(cls).where(cls.key == key).limit(1)).first()

    @classmethod
    def get_all_as_dict(cls, session: Session) -> dict[str, str | None]:
        """Get all settings as a dictionary"""
        settings = session.scalars(select(cls)).all()
        return {s.key: s.value for s in settings}


class SettingsCreate(SettingsBase):
    pass


class SettingsUpdate(SQLModel):
    key: str | None = None
    value: Annotated[str | None, NumToStr] = None
    description: str | None = None


class SettingsPublic(SettingsBase):
    id: int

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SettingsList(SQLModel):
    settings: list[SettingsPublic]


class W3CConfig(SQLModel):
    w3c_url: str
    # None when w3champions is unreachable and no season is configured.
    current_season: int | None


class SettingsUpdated(SQLModel):
    message: str
    updated: list[SettingsPublic]


class SettingUpdated(SQLModel):
    message: str
    setting: SettingsPublic


class NightbotToken(SQLModel):
    token: str | None
    exists: bool


class GeneratedNightbotToken(SQLModel):
    token: str
    message: str
