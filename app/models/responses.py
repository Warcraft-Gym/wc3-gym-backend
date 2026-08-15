"""Response schemas that carry a message instead of an entity."""

from sqlmodel import SQLModel


class Message(SQLModel):
    message: str
