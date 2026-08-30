"""The Discord account behind a Clerk user.

Clerk names the Discord account once, on the first request of a user; the row
answers every request after, so no request waits on Clerk's API.
"""

from sqlmodel import Field, SQLModel

from app.models.base import DBModel


class ClerkAccount(DBModel, SQLModel, table=True):
    __tablename__ = "clerk_account"

    clerk_user_id: str = Field(max_length=64, primary_key=True)
    discord_id: str = Field(max_length=50)
