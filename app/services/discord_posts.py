"""The bot's posts the app keeps true, one discord_post row each."""

from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.models.discord_post import DiscordPost
from app.services import discord
from app.services.commands import announce, veto
from app.services.series import SeriesService

# The cards about a series, by the command that posts them
SERIES_KINDS = ("veto", "announce")


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


def refresh_series(series_id: int) -> None:
    """Rebuild every post about the series, so each card says where the series
    stands now: its time and its veto."""
    with Session() as session:
        posts = list(
            session.scalars(
                select(DiscordPost)
                .where(
                    col(DiscordPost.kind).in_(SERIES_KINDS),
                    col(DiscordPost.subject_id) == series_id,
                )
                .order_by(col(DiscordPost.id))
            )
        )
    if not posts:
        return
    series = SeriesService().get(series_id)
    cards = {"veto": veto.card, "announce": announce.card}
    # ponytail: a post deleted in Discord keeps its row and fails one PATCH per write
    for post in posts:
        discord.edit_channel_message(
            post.channel_id, post.message_id, cards[post.kind](series)
        )
