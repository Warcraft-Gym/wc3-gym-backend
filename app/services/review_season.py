"""A season to review the player flows on: the two Discord accounts you name captain opposing
teams and meet in an unplayed series every week, on a roster of real players, so the dashboard,
availability, veto and fantasy tier pages have something to click.

`just vercel review-season <env> <reviewer discord id>` calls build. The season becomes the
current one and both accounts get an admin grant. Running it again replaces the season.
Rosters, maps and rules copy from the latest real season.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col, select

from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.models.admin_grant import AdminGrant
from app.models.base import ident
from app.models.enums import Race
from app.models.match import Match
from app.models.relationships import (
    DBMapSeason,
    DBSeasonWeekMap,
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

NAME = "GNL Review Season"
WEEKS = 4
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


def build(discord_a: str, discord_b: str) -> str:
    """Replace the review season and answer a summary of who plays whom."""
    with Session.begin() as session:
        old = session.scalar(select(Season).where(col(Season.name) == NAME))
        if old:
            # The two link tables without a cascade from the season
            for table in (DBUserSeasonAvailability, DBTeamSeasonCaptain):
                session.execute(delete(table).where(col(table.season_id) == old.id))
            session.delete(old)
            session.flush()
        source = session.scalar(select(Season).order_by(col(Season.id).desc()))
        if source is None:
            raise NotFoundError("no season to copy the maps, rules and roster from")

        today = datetime.now(UTC).date()
        season = Season(
            name=NAME,
            number_weeks=WEEKS,
            series_per_week=PER_TEAM,
            pick_ban=source.pick_ban,
            map_rules="week,veto,veto",
            start_date=today,
            end_date=today + timedelta(weeks=WEEKS + 1),
            score_system=source.score_system,
        )
        session.add(season)
        session.flush()
        sid = ident(season)

        pool = list(
            session.scalars(
                select(col(DBMapSeason.map_id)).where(
                    col(DBMapSeason.season_id) == source.id
                )
            )
        )
        for map_id in pool:
            session.add(DBMapSeason(map_id=map_id, season_id=sid))
        for week in range(1, WEEKS + 1):
            session.add(
                DBSeasonWeekMap(
                    season_id=sid,
                    playday=week,
                    map_id=pool[(week - 1) % len(pool)],
                )
            )

        a, b = player(session, discord_a), player(session, discord_b)
        # Real players with a ladder MMR, so the tier strip and the MMR chips draw something
        rostered = session.scalars(
            select(User)
            .join(DBUserTeamSeason, col(DBUserTeamSeason.user_id) == col(User.id))
            .join(W3CStats, col(W3CStats.user_id) == col(User.id))
            .where(col(DBUserTeamSeason.season_id) == source.id, col(W3CStats.mmr) > 0)
            .where(col(User.id).notin_([a.id, b.id]))
            .group_by(col(User.id))
            .order_by(func.max(col(W3CStats.mmr)).desc())
        ).all()
        pairs = min(PER_TEAM - 1, len(rostered) // 2)
        side_a = [a] + rostered[0 : 2 * pairs : 2]
        side_b = [b] + rostered[1 : 2 * pairs : 2]

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
                        race=signup_race.get(user.id) or user.race,
                    )
                )
                session.add(
                    DBUserTeamSeason(
                        user_id=ident(user), team_id=team_id, season_id=sid
                    )
                )
        session.flush()

        # Every week the two teams meet; pair 0 is always the two named accounts
        for week in range(1, WEEKS + 1):
            match = Match(team1_id=team_a, team2_id=team_b, season_id=sid, playday=week)
            session.add(match)
            session.flush()
            when = (
                None
                if week == 1
                else datetime.combine(
                    today + timedelta(weeks=week - 1), datetime.min.time(), UTC
                )
                + timedelta(hours=20)
            )
            for p1, p2 in zip(side_a, side_b, strict=True):
                session.add(
                    Series(
                        match_id=ident(match),
                        player1_id=ident(p1),
                        player2_id=ident(p2),
                        host_player_id=ident(p1),
                        date_time=when,
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
                f"season {sid} '{NAME}': {WEEKS} weeks, teams {team_a} vs {team_b}, {2 * len(side_a)} players",
                f"A: {a.name} ({a.discordId}) captains team {team_a}; B: {b.name} ({b.discordId}) captains team {team_b}",
                "week 1 series between them is unscheduled; weeks 2+ are scheduled 20:00 UTC",
            )
        )
