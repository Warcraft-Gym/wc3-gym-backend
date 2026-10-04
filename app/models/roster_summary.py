"""The list row of an event's teams with their rosters.

Nothing here is a table. app.services.roster_summary computes every field in
SQL; only the rows are put together in Python.
"""

from sqlmodel import SQLModel

from app.models.team_summary import TeamSummaryPublic


class RosterCaptainPublic(SQLModel):
    """A captain of the team in the event."""

    id: int
    name: str
    battleTag: str | None = None
    country: str | None = None
    # The race and the tag of his signup to the event, null without one
    signup_race: str | None = None
    played_as: str | None = None


class RosterPlayerPublic(RosterCaptainPublic):
    """A player on the team's roster of the event."""

    # Series won and lost in the event, counted as his event record counts them
    wins: int = 0
    losses: int = 0
    # The MMR he entered a finished event with, else his current rating on the signup race
    mmr: int | None = None


class TeamRosterSummaryPublic(TeamSummaryPublic):
    """One team of an event with its roster and captains there, flat."""

    # The league points the team took in the event
    final_score: int = 0
    players: list[RosterPlayerPublic] = []
    captains: list[RosterCaptainPublic] = []
