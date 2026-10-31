"""The Discord account behind a Clerk user, from when Clerk signed members in.

No code reads or writes it: the Discord login names the account in its session.
The table is dropped in a later release, once the code that read it is gone
from every deployment (a migration must work with the code before it).
"""

from sqlmodel import Field, SQLModel

from app.models.base import DBModel


class ClerkAccount(DBModel, SQLModel, table=True):
    __tablename__ = "clerk_account"

    clerk_user_id: str = Field(max_length=64, primary_key=True)
    discord_id: str = Field(max_length=50)
