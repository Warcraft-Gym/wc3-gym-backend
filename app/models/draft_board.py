"""The shapes the match draft board and the pair meetings read send.

Nothing here is a table. app.services.draft_board derives every figure from
the rosters, the ladder rows and the series already stored, and answers
figures rather than rows: neither payload grows with the ladder history.
"""

from datetime import datetime

from sqlmodel import SQLModel


class DraftBoardPlayer(SQLModel):
    """One player of either roster, as the pick lists draw him."""

    user_id: int
    team_id: int
    # The race he registered the event on; null when he never signed up
    race: str | None = None
    # His W3C rating on that race, by the rule the stage series rows read
    mmr: int | None = None
    # Ladder games on that race over the event's games-rule window
    games: int = 0
    # "under_min_games", "no_w3c_stats", or null when the rule is met or unset
    games_warning: str | None = None
    # Wins and losses on the signup race against each race, in the event window
    vs_race: dict[str, list[int]] = {}
    # His last ten counted ladder games on that race, newest first, as W and L
    form: str = ""


class DraftBoardPair(SQLModel):
    """One player of each team, holding only what a browser cannot work out.

    The MMR difference is absent: the browser subtracts the two ratings. A
    pair that never met carries no score and no last event.
    """

    player1_id: int
    player2_id: int
    # The hours both have open across the round window
    hours: float = 0.0
    # Series each side won over every finished series on the app, in this order
    wins: int | None = None
    losses: int | None = None
    # The event the two last met in; null when they never met
    last_event: str | None = None


class DraftBoard(SQLModel):
    """Everything the draft board of one match shows, in one answer."""

    match_id: int
    event_id: int
    playday: int
    team1_id: int
    team2_id: int
    # The stage default of the largest MMR difference; null off a captain draft
    max_mmr_difference: int | None = None
    series_per_round: int
    # Series the match already published, and drafts still open on it
    published_series: int = 0
    open_drafts: int = 0
    players: list[DraftBoardPlayer] = []
    pairs: list[DraftBoardPair] = []


class PairMeeting(SQLModel):
    """One finished series the two players played, whatever the event."""

    series_id: int
    # When it was played; the round's first day when the series carries no time
    date_time: datetime | None = None
    # "{league short name} - {event name}", the event name alone without a league
    event_label: str | None = None
    player1_score: int
    player2_score: int
    # The race each side played: the off race he reported, else his signup race
    player1_race: str | None = None
    player2_race: str | None = None
    # mmr_after of his last ladder game on that race before the series, else null
    player1_mmr: int | None = None
    player2_mmr: int | None = None
