"""The bot's posts the app keeps true, one discord_post row each."""

import os
from typing import Any

from sqlalchemy import select
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
    """Keep a post the bot made, so a later write to its subject can edit it."""
    with Session.begin() as session:
        session.add(
            DiscordPost(
                kind=kind,
                subject_id=subject_id,
                channel_id=channel_id,
                message_id=message_id,
            )
        )


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
    where the series stands now."""
    posts = _posts(series_id, kinds)
    if not posts:
        return
    series = SeriesService().get(series_id)
    # ponytail: a post deleted in Discord keeps its row and fails one PATCH per write
    for post in posts:
        discord.edit_channel_message(
            post.channel_id, post.message_id, CARDS[post.kind](series)
        )


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
    message_id = discord.post_to_channel(
        channel_id, result_card(SeriesService().get(series_id))
    )
    if message_id:
        remember(RESULT, series_id, channel_id, message_id)
