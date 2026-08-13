from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from src.models.base import DBModel

class DBSettings(DBModel):
    __tablename__ = 'settings'

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    value: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str | None] = mapped_column(String(500))

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

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
