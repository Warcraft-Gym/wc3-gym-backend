"""The bot's posts the app keeps true, one discord_post row each."""

import os
from datetime import timedelta
from time import sleep
from typing import Any

from sqlalchemy import func, select, update
from sqlmodel import col

from app.core.db import Session
from app.models.discord_post import DiscordPost
from app.models.series import SeriesPublic
from app.models.settings import Settings
from app.models.types import utcnow
from app.models.user import UserPublic
from app.services import discord, replays
from app.services.commands import announce, veto
from app.services.series import SeriesService

# The cards about a series that show its time and veto, by the command that posts them
SERIES_KINDS = ("veto", "announce")
# The result card the app posts itself, in the channel the old bot's setting names
RESULT = "result"
RESULTS_CHANNEL = "results_channel_id"
# Discord takes five edits per five seconds in a channel: one edit a second per channel
EDIT_INTERVAL = timedelta(seconds=1)
# Tries, about a second each, a task gives a post before it leaves the edit to the next write
CLAIM_TRIES = 5


def result_card(series: SeriesPublic) -> dict[str, Any]:
    """The score, one download link per game, the match on the site, and when
    the card was last written."""

    def name(player: UserPublic | None) -> str:
        return (player.name if player else None) or "?"

    match = series.match
    score = f"{series.player1_score}-{series.player2_score}"
    week = match.playday if match else "?"
    lines = [
        f"{name(series.player1)} {score} {name(series.player2)} · Wk {week} · #{series.id}"
    ]
    # ponytail: the links expire after 7 days; the match page keeps the files
    lines += [f"Game {row.game_no}: {row.url}" for row in replays.for_series(series.id)]
    site = (os.getenv("FRONTEND_URL") or "").rstrip("/")
    if site and match:
        lines.append(f"{site}/match/{match.id}")
    lines.append(f"Updated <t:{int(utcnow().timestamp())}:R>")
    return {"content": "\n".join(lines)}


CARDS = {"veto": veto.card, "announce": announce.card, RESULT: result_card}


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


def _flush(post: DiscordPost) -> None:
    for _ in range(CLAIM_TRIES):
        claimed, wait = _claim(post)
        if claimed:
            # the card is built after the claim, so it carries every change so far
            series = SeriesService().get(post.subject_id)
            # ponytail: a post deleted in Discord keeps its row and fails one PATCH per write
            discord.edit_channel_message(
                post.channel_id, post.message_id, CARDS[post.kind](series)
            )
            return
        if not wait:
            return
        sleep(wait)
    # ponytail: a channel busy for five seconds keeps this change until the next write


def post_result(series_id: int) -> None:
    """Post the result card in the results channel the first time a series has
    a score; a corrected score edits that post. Nothing without the setting."""
    if _posts(series_id, (RESULT,)):
        refresh_series(series_id, (RESULT,))
        return
    with Session() as session:
        setting = Settings.get_by_key(session, RESULTS_CHANNEL)
    channel_id = setting.value if setting else None
    if not channel_id:
        return
    wait_for_channel(channel_id)
    message_id = discord.post_to_channel(
        channel_id, result_card(SeriesService().get(series_id))
    )
    if message_id:
        remember(RESULT, series_id, channel_id, message_id)
