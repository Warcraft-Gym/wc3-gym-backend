"""A season to review the player flows on: the two Discord accounts you name captain opposing
teams, every account in the test guild plays, and the pairings rotate each round, so the
dashboard, availability, veto and fantasy tier pages have something to click.

`just vercel review-season <env> <reviewer discord id>` calls build. The season becomes the
current one and both accounts get an admin grant. Running it again replaces the season.
Rosters, maps and the pick and ban order copy from the latest real season. The map rules
are always fixed,loser,loser, the format GNL plays.

A series between two accounts that are not in the test guild gets a time. A series with a
test guild account in it stays unscheduled, so the person schedules it in the app.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col, select

from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.models.admin_grant import AdminGrant
from app.models.base import ident
from app.models.enums import Race
from app.models.fantasy_team import FantasyTeam
from app.models.match import Match
from app.models.relationships import (
    DBMapSeason,
    DBSeasonRound,
    DBTeamSeasonCaptain,
    DBUserSeasonSignup,
)
from app.models.season import Season
from app.models.series import Series
from app.models.settings import Settings
from app.models.team_season import DBTeamSeason
from app.models.user import User
from app.models.user_season_availability import DBUserSeasonAvailability
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_stats import W3CStats
from app.services import discord

NAME = "GNL Review Season"
START = date(2026, 9, 1)
ROUNDS = 3
ROUND_WEEKS = 2
# The smallest roster a side gets; the test guild raises it when more accounts play.
PER_TEAM = 8


def player(session: OrmSession, discord_id: str) -> User:
    """The users row behind a Discord id, made up when the account never signed up."""
    user = session.scalar(select(User).where(col(User.discordId) == discord_id))
    if user is None:
        user = User(
            name=f"Review Player {discord_id[-4:]}",
            battleTag=f"Review#{discord_id[-4:]}",
            discordTag="",
            discordId=discord_id,
            race=Race.RANDOM,
        )
        session.add(user)
        session.flush()
    return user


def guild_players(session: OrmSession, first: list[User]) -> list[User]:
    """The named accounts, then every other human in the test guild, no account twice."""
    members = discord.guild_member_list() or []
    ids = [m["user"]["id"] for m in members if not m["user"].get("bot")]
    seated = {user.discordId: user for user in first}
    for discord_id in ids:
        if discord_id not in seated:
            seated[discord_id] = player(session, discord_id)
    return list(seated.values())


def build(discord_a: str, discord_b: str) -> str:
    """Replace the review season and answer a summary of who plays whom."""
    with Session.begin() as session:
        old = session.scalar(select(Season).where(col(Season.name) == NAME))
        if old:
            # The two link tables without a cascade from the season
            for table in (DBUserSeasonAvailability, DBTeamSeasonCaptain):
                session.execute(delete(table).where(col(table.season_id) == old.id))
            # fantasy_team_player has no cascade from fantasy_teams, so the ORM
            # takes the drafted players out before Postgres cascades the teams
            for team in session.scalars(
                select(FantasyTeam).where(col(FantasyTeam.season_id) == old.id)
            ):
                session.delete(team)
            session.delete(old)
            session.flush()
        source = session.scalar(select(Season).order_by(col(Season.id).desc()))
        if source is None:
            raise NotFoundError("no season to copy the maps, rules and roster from")

        a, b = player(session, discord_a), player(session, discord_b)
        testers = guild_players(session, [a, b])
        tester_ids = [user.id for user in testers]
        # Real players with a ladder MMR, so the tier strip and the MMR chips draw something
        rostered = session.scalars(
            select(User)
            .join(DBUserTeamSeason, col(DBUserTeamSeason.user_id) == col(User.id))
            .join(W3CStats, col(W3CStats.user_id) == col(User.id))
            .where(col(DBUserTeamSeason.season_id) == source.id, col(W3CStats.mmr) > 0)
            .where(col(User.id).notin_(tester_ids))
            .group_by(col(User.id))
            .order_by(func.max(col(W3CStats.mmr)).desc())
        ).all()
        # Testers first, dealt left and right, so both teams carry the people who review
        pool = testers + list(rostered)
        size = min(max(PER_TEAM, -(-len(testers) // 2)), len(pool) // 2)
        side_a, side_b = pool[0 : 2 * size : 2], pool[1 : 2 * size : 2]

        season = Season(
            name=NAME,
            number_weeks=ROUNDS,
            series_per_week=size,
            pick_ban=source.pick_ban,
            map_rules="fixed,loser,loser",
            start_date=START,
            end_date=START + timedelta(weeks=ROUNDS * ROUND_WEEKS),
            score_system=source.score_system,
        )
        session.add(season)
        session.flush()
        sid = ident(season)

        pool_maps = list(
            session.scalars(
                select(col(DBMapSeason.map_id)).where(
                    col(DBMapSeason.season_id) == source.id
                )
            )
        )
        for map_id in pool_maps:
            session.add(DBMapSeason(map_id=map_id, season_id=sid))
        starts = [
            START + timedelta(weeks=(r - 1) * ROUND_WEEKS) for r in range(1, ROUNDS + 1)
        ]
        for playday, start in enumerate(starts, start=1):
            session.add(
                DBSeasonRound(
                    season_id=sid,
                    playday=playday,
                    start_date=start,
                    end_date=start + timedelta(weeks=ROUND_WEEKS, days=-1),
                    map_id=pool_maps[(playday - 1) % len(pool_maps)],
                )
            )

        team_a, team_b = session.scalars(
            select(col(DBTeamSeason.team_id))
            .where(col(DBTeamSeason.season_id) == source.id)
            .order_by(col(DBTeamSeason.team_id))
            .limit(2)
        ).all()
        signup_race = {
            row.user_id: row.race
            for row in session.scalars(
                select(DBUserSeasonSignup).where(
                    col(DBUserSeasonSignup.season_id) == source.id
                )
            )
        }
        for team_id, side in ((team_a, side_a), (team_b, side_b)):
            session.add(DBTeamSeason(team_id=team_id, season_id=sid))
            session.add(
                DBTeamSeasonCaptain(
                    team_id=team_id, season_id=sid, user_id=ident(side[0])
                )
            )
            for user in side:
                session.add(
                    DBUserSeasonSignup(
                        user_id=ident(user),
                        season_id=sid,
                        race=signup_race.get(user.id) or user.race or Race.RANDOM,
                    )
                )
                session.add(
                    DBUserTeamSeason(
                        user_id=ident(user), team_id=team_id, season_id=sid
                    )
                )
        session.flush()

        # The two teams meet every round; side B rotates, so nobody repeats an opponent
        tester_set = {user.id for user in testers}
        for playday, start in enumerate(starts, start=1):
            match = Match(
                team1_id=team_a, team2_id=team_b, season_id=sid, playday=playday
            )
            session.add(match)
            session.flush()
            when = datetime.combine(
                start + timedelta(days=10), datetime.min.time(), UTC
            ) + timedelta(hours=20)
            rotated = side_b[playday - 1 :] + side_b[: playday - 1]
            for p1, p2 in zip(side_a, rotated, strict=True):
                plays_review = p1.id in tester_set or p2.id in tester_set
                session.add(
                    Series(
                        match_id=ident(match),
                        player1_id=ident(p1),
                        player2_id=ident(p2),
                        host_player_id=ident(p1),
                        date_time=None if plays_review else when,
                    )
                )

        setting = Settings.get_by_key(session, "current_gnl_season")
        if setting:
            setting.value = str(sid)
        else:
            session.add(Settings(key="current_gnl_season", value=str(sid)))
        for user in (a, b):
            if session.get(AdminGrant, user.discordId) is None:
                session.add(
                    AdminGrant(
                        discord_id=user.discordId,
                        name=user.name,
                        granted_by="review_season",
                    )
                )

        return "\n".join(
            (
                (
                    f"season {sid} '{NAME}': {ROUNDS} rounds of {ROUND_WEEKS} weeks "
                    f"from {START}, teams {team_a} vs {team_b}, {2 * size} players"
                ),
                f"A: {a.name} ({a.discordId}) captains team {team_a}; B: {b.name} ({b.discordId}) captains team {team_b}",
                f"{len(testers)} test guild accounts play; their series are unscheduled, the rest run 20:00 UTC",
            )
        )
