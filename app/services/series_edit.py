"""What a captain writes on the published series of his team's fixtures, and
who takes a result back.

An admin writes every series and every field. A captain of either team of a
fixture adds a series to it, edits one and deletes one; the routes check the
seat against the fixture. An edit by a captain names the time, the result, the
races played, the host and the fantasy mark: who plays and the fixture stay an
admin's, because a captain changes players through a replacement draft. A
captain's add publishes as his draft does, up to the round's series. Whoever
may report the result may clear it.
"""

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.series import Series, SeriesCreate, SeriesPublic, SeriesUpdate
from app.services import discord_posts, draft_series
from app.services.series import SeriesService, add_in
from app.services.series_rules import acts_for_side

# The fields a captain sends on the edit; any other is an admin's
CAPTAIN_FIELDS = frozenset(
    {
        "date_time",
        "player1_score",
        "player2_score",
        "player1_off_race",
        "player2_off_race",
        "host_player_id",
        "is_fantasy_match",
    }
)

NOT_AUTHORIZED = {"error": "not_authorized_for_this_series"}


def fixture_of(series_id: int) -> int | None:
    """The fixture a series plays, for the seat check; null for a series of a
    stage or a KOTH night, which no captain writes."""
    with Session() as session:
        row = session.get(Series, series_id)
        if row is None:
            raise NotFoundError("series_not_found")
        return row.match_id


def add(data: SeriesCreate, *, admin: bool) -> SeriesPublic:
    """Publish one series. A captain's add counts against the round as a
    published draft does, and names one of the two players as the host."""
    if admin:
        return SeriesService().add(data)
    if data.host_player_id not in (data.player1_id, data.player2_id):
        raise BadRequestError("The host is one of the two players")
    with Session.begin() as session:
        players = (data.player1_id, data.player2_id)
        draft_series.refuse_repeat(session, data.match_id, players)
        draft_series.refuse_full(session, data.match_id)
        series_id = add_in(session, data)
    return SeriesService().get(series_id)


def edit(
    series_id: int, data: SeriesUpdate, *, admin: bool, force: bool = False
) -> SeriesPublic:
    """Write the edit of an admin or of a captain of the fixture, and keep the
    bot's cards in step. `force` loses a later bracket result, an admin's call."""
    if not admin:
        sent = data.model_fields_set
        if force or not sent <= CAPTAIN_FIELDS:
            raise ApiError(403, NOT_AUTHORIZED)
        if "host_player_id" in sent:
            with Session() as session:
                row = session.get(Series, series_id)
                players = (row.player1_id, row.player2_id) if row else ()
            if data.host_player_id not in players:
                raise BadRequestError("The host is one of the two players")
    return _write(series_id, data, force)


def clear_result(
    series_id: int, *, admin: bool, user_id: int | None, force: bool = False
) -> SeriesPublic:
    """Take back the result: the scores, the races played and the games go,
    the result card comes down, and the replays stay for the next report. A
    walkover or a forfeit was an admin's call, so an admin clears it."""
    with Session() as session:
        row = session.get(Series, series_id)
        if row is None:
            raise NotFoundError("series_not_found")
        if not admin and (force or acts_for_side(session, row, user_id) is None):
            raise ApiError(403, NOT_AUTHORIZED)
        if not admin and row.result_kind != "played":
            raise ApiError(403, {"error": "An admin clears a walkover or a forfeit"})
    cleared = SeriesUpdate(
        player1_score=None,
        player2_score=None,
        player1_off_race=None,
        player2_off_race=None,
    )
    return _write(series_id, cleared, force)


def _write(series_id: int, data: SeriesUpdate, force: bool) -> SeriesPublic:
    """The write itself, and the bot's cards after it. The cards need the time
    and the score from before, which the row holds, so no full read is paid."""
    with Session() as session:
        row = session.get(Series, series_id)
        if row is None:
            raise NotFoundError("series_not_found")
        before = discord_posts.CardFacts.of(row)
    after = SeriesService().update(series_id, data, force)
    discord_posts.follow_series(series_id, before, after)
    return after
