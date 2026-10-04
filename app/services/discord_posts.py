"""The bot's posts the app keeps true, one discord_post row each."""

from datetime import datetime, timedelta
from time import sleep
from typing import Any, NamedTuple

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import ExternalServiceError
from app.models.discord_post import DiscordPost
from app.models.enums import Race
from app.models.season import Season
from app.models.series import Series, SeriesPublic
from app.models.series_game import DBSeriesGame
from app.models.settings import Settings
from app.models.types import utcnow
from app.models.user import User
from app.services import discord, event_cards, series_cards
from app.services.commands import announce, veto
from app.services.events import EventService
from app.services.series import SeriesService

# The result card the app posts itself, in the channel the old bot's setting names
RESULT = "result"
# The note beside the result card that a player or a captain changed a reported
# result or took it back. It is never edited: it records the change.
RESULT_CHANGE = "result_change"
# The card that says a member claimed the series, posted when the claim lands
CAST = "cast"
# The card that calls the audience to the stream, posted shortly before the start
REMINDER = "reminder"
# The card about an event, with its Sign up and Check in buttons; _card builds it
EVENT = "event"
# The cards about a series that show its time, its veto or its casters. The
# reminder is not one: it carries a relative time Discord renders itself.
SERIES_KINDS = ("veto", "announce", CAST)
# The channel each card the app posts itself goes to, by settings key. A claim
# and its reminder both belong where the league shares content.
CHANNEL_OF = {
    RESULT: "results_channel_id",
    RESULT_CHANGE: "results_channel_id",
    CAST: "content_channel_id",
    REMINDER: "content_channel_id",
}
# Discord takes five edits per five seconds in a channel: one edit a second per channel
EDIT_INTERVAL = timedelta(seconds=1)
# Tries, about a second each, a task gives a post before it leaves the edit to the next write
CLAIM_TRIES = 5


CARDS = {
    "veto": veto.card,
    "announce": announce.card,
    RESULT: series_cards.result_card,
    CAST: series_cards.claim_card,
    REMINDER: series_cards.reminder_card,
}


def remember(kind: str, subject_id: int, channel_id: str, message_id: str) -> None:
    """Keep a post the bot made, so a later write to its subject can edit it.
    The post counts as the channel's write of this second."""
    with Session.begin() as session:
        session.add(
            DiscordPost(
                kind=kind,
                subject_id=subject_id,
                channel_id=channel_id,
                message_id=message_id,
                edited_at=utcnow(),
            )
        )


def wait_for_channel(channel_id: str) -> None:
    """A new post waits for the channel's second, as an edit does."""
    with Session() as session:
        last = session.scalar(
            select(func.max(DiscordPost.edited_at)).where(
                col(DiscordPost.channel_id) == channel_id
            )
        )
    wait = (last + EDIT_INTERVAL - utcnow()).total_seconds() if last else 0
    if wait > 0:
        sleep(wait)


def _posts(series_id: int, kinds: tuple[str, ...]) -> list[DiscordPost]:
    with Session() as session:
        return list(
            session.scalars(
                select(DiscordPost)
                .where(
                    col(DiscordPost.kind).in_(kinds),
                    col(DiscordPost.subject_id) == series_id,
                )
                .order_by(col(DiscordPost.id))
            )
        )


def refresh_series(series_id: int, kinds: tuple[str, ...] = SERIES_KINDS) -> None:
    """Rebuild every post of these kinds about the series, so each card says
    where the series stands now. A burst of writes edits each card once a
    second, and the last edit carries the latest state."""
    mark_series(series_id, kinds)
    flush_series(series_id, kinds)


def mark_series(series_id: int, kinds: tuple[str, ...] = SERIES_KINDS) -> None:
    """The series changed: every post about it is due an edit."""
    with Session.begin() as session:
        session.execute(
            update(DiscordPost)
            .where(
                col(DiscordPost.kind).in_(kinds),
                col(DiscordPost.subject_id) == series_id,
            )
            .values(changed_at=utcnow())
        )


def flush_series(series_id: int, kinds: tuple[str, ...] = SERIES_KINDS) -> None:
    """Edit every post of the series that is due, one a second per channel."""
    for post in _posts(series_id, kinds):
        _flush(post)


def _claim(post: DiscordPost) -> tuple[bool, float]:
    """Take the post's edit when it is due and its channel had none this second.
    Whether it was taken, and otherwise how long to wait for the channel."""
    now = utcnow()
    with Session.begin() as session:
        row = session.get(DiscordPost, post.id)
        if row is None or row.changed_at is None:
            return False, 0
        if row.edited_at and row.edited_at >= row.changed_at:
            return False, 0  # a later task edited it after the latest change
        in_channel = col(DiscordPost.channel_id) == row.channel_id
        last = session.scalar(select(func.max(DiscordPost.edited_at)).where(in_channel))
        # the whole channel, not the row being updated: correlate(None) keeps the FROM
        busy = (
            select(col(DiscordPost.id))
            .where(in_channel, col(DiscordPost.edited_at) > now - EDIT_INTERVAL)
            .correlate(None)
            .exists()
        )
        claimed = session.execute(
            update(DiscordPost)
            .where(
                col(DiscordPost.id) == post.id,
                ~busy,
                col(DiscordPost.edited_at).is_(None)
                | (col(DiscordPost.edited_at) < col(DiscordPost.changed_at)),
            )
            .values(edited_at=now)
            .returning(col(DiscordPost.id)),
            execution_options={"synchronize_session": False},
        ).scalar()
    if claimed:
        return True, 0
    wait = (last + EDIT_INTERVAL - now).total_seconds() if last else 0
    return False, max(wait, 0.05)


def _card(post: DiscordPost) -> dict[str, Any]:
    """The card the post shows, built now so it carries every change so far."""
    if post.kind == EVENT:
        return event_cards.event_card(EventService().get(post.subject_id))
    return CARDS[post.kind](SeriesService().get(post.subject_id))


def _flush(post: DiscordPost) -> None:
    for _ in range(CLAIM_TRIES):
        claimed, wait = _claim(post)
        if claimed:
            # ponytail: a post deleted in Discord keeps its row and fails one PATCH per write
            discord.edit_channel_message(post.channel_id, post.message_id, _card(post))
            return
        if not wait:
            return
        sleep(wait)
    # ponytail: a channel busy for five seconds keeps this change until the next write


def _channel(kind: str) -> str | None:
    """The channel the kind's setting names, or None without the setting."""
    with Session() as session:
        setting = Settings.get_by_key(session, CHANNEL_OF[kind])
    return setting.value if setting else None


def _post_card(kind: str, series_id: int) -> bool:
    """Post the kind's card about the series in the channel its setting names.
    Nothing happens without the setting, and False says nothing was posted."""
    channel_id = _channel(kind)
    if not channel_id:
        return False
    wait_for_channel(channel_id)
    message_id = discord.post_to_channel(
        channel_id, CARDS[kind](SeriesService().get(series_id))
    )
    if not message_id:
        return False
    remember(kind, series_id, channel_id, message_id)
    return True


def post_result(series_id: int) -> None:
    """Post the result card in the results channel the first time a series has
    a score; a corrected score edits that post."""
    if _posts(series_id, (RESULT,)):
        refresh_series(series_id, (RESULT,))
        return
    _post_card(RESULT, series_id)


def withdraw_result(series_id: int) -> None:
    """Take down the result card of a series whose result was cleared, so the
    next report posts a fresh one."""
    for post in _posts(series_id, (RESULT,)):
        discord.delete_channel_message(post.channel_id, post.message_id)
    with Session.begin() as session:
        session.execute(
            delete(DiscordPost).where(
                col(DiscordPost.kind) == RESULT,
                col(DiscordPost.subject_id) == series_id,
            )
        )


class CardFacts(NamedTuple):
    """What the bot's cards show of a series: its time and its score."""

    date_time: datetime | None
    player1_score: int | None
    player2_score: int | None

    @classmethod
    def of(cls, series: Series | SeriesPublic) -> "CardFacts":
        return cls(series.date_time, series.player1_score, series.player2_score)


def follow_series(series_id: int, before: CardFacts, after: SeriesPublic) -> None:
    """The bot's cards follow a series write: the time on the announce card,
    the score on the result card, which a cleared result takes down."""
    now = CardFacts.of(after)
    if before.date_time != now.date_time:
        refresh_series(series_id)
    if before[1:] == now[1:]:
        return
    if now.player1_score is None:
        withdraw_result(series_id)
    else:
        post_result(series_id)


def _race(race: Race | str | None) -> str | None:
    return race.value if isinstance(race, Race) else race


class ResultFacts(NamedTuple):
    """What a reported result holds: the score, the races played off the
    signup race, and each game's winner and map."""

    player1_score: int | None
    player2_score: int | None
    player1_off_race: str | None
    player2_off_race: str | None
    games: tuple[tuple[int, str | None, int | None], ...]

    @classmethod
    def read(cls, session: OrmSession, series: Series) -> "ResultFacts":
        games = session.scalars(
            select(DBSeriesGame)
            .where(col(DBSeriesGame.series_id) == series.id)
            .order_by(col(DBSeriesGame.game_no))
        )
        return cls(
            series.player1_score,
            series.player2_score,
            _race(series.player1_off_race),
            _race(series.player2_off_race),
            tuple((game.game_no, game.winner_side, game.map_id) for game in games),
        )

    @property
    def score(self) -> tuple[int, int] | None:
        """Both map scores, or None while the series holds no result."""
        if self.player1_score is None or self.player2_score is None:
            return None
        return self.player1_score, self.player2_score


def post_result_change(
    series_id: int, before: ResultFacts, actor_id: int | None
) -> None:
    """Post a note beside the result card when a player or a captain changes a
    reported result or takes it back, naming who did it, so a past result
    never changes unseen. A first report posts the card alone, and nothing is
    posted without the setting or when the write changed nothing the result
    holds."""
    if before.score is None:
        return
    channel_id = _channel(RESULT_CHANGE)
    if not channel_id:
        return
    with Session() as session:
        series = session.get(Series, series_id)
        if series is None:
            return
        after = ResultFacts.read(session, series)
        actor = session.get(User, actor_id) if actor_id else None
    if after == before:
        return
    # The score says most; a note names what else changed while a result stands
    also = []
    if after.score is not None:
        if after.score == before.score and after.games != before.games:
            also.append("The games changed")
        if after[2:4] != before[2:4]:
            also.append("The races played changed")
    card = series_cards.change_card(
        SeriesService().get(series_id), actor, before.score, after.score, also
    )
    wait_for_channel(channel_id)
    message_id = discord.post_to_channel(channel_id, card)
    if message_id:
        remember(RESULT_CHANGE, series_id, channel_id, message_id)


def post_cast(series_id: int) -> None:
    """Post the claim card in the content channel the first time the series is
    claimed; a second claim edits it, as every other write to the series does."""
    if _posts(series_id, (CAST,)):
        refresh_series(series_id, (CAST,))
        return
    _post_card(CAST, series_id)


def post_reminder(series_id: int) -> bool:
    """Call the audience to a stream about to start, once per series. A series
    that already has its card is left alone, so a job that runs every few
    minutes posts nothing twice."""
    if _posts(series_id, (REMINDER,)):
        return False
    return _post_card(REMINDER, series_id)


def post_event(event_id: int, channel_id: str) -> str:
    """Post the event card in the channel, or edit the card already there.

    The card the channel holds is edited through the same refresh a series
    card takes, which paces itself over the whole channel. "posted" or
    "edited", so the admin page says which one happened.
    """
    if any(post.channel_id == channel_id for post in _posts(event_id, (EVENT,))):
        refresh_series(event_id, (EVENT,))
        return "edited"
    # The card is built before the pacing wait, so a draft answers 404 at once
    card = event_cards.event_card(EventService().get(event_id))
    wait_for_channel(channel_id)
    message_id = discord.post_to_channel(channel_id, card)
    if not message_id:
        raise ExternalServiceError("Discord did not take the event card")
    remember(EVENT, event_id, channel_id, message_id)
    with Session.begin() as session:
        event = session.get(Season, event_id)
        if event is not None:
            event.discord_event_id = message_id
    return "posted"
