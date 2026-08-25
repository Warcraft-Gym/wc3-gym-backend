"""The login request body."""

from sqlmodel import SQLModel


class LoginRequest(SQLModel):
    token: str
