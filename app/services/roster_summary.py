"""An event's teams with their rosters as list rows, computed in SQL.

The read costs five statements beside the event phase the route reads for its
cache: the event's scale and phase, the page of teams with their points, the
roster players with their signup, record and MMR, the captains with their
signup, and the players' tags. A running event pays one or two more for the
current W3C season. None grows with the number of teams or players.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Row, Select, case, func, select, union_all
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.selectable import Subquery
from sqlmodel import col

from app.core.db import Session
from app.core.fantasy import race_value
from app.core.scoring import DEFAULT_SYSTEM, points_case, wins_needed
from app.models.match import Match
from app.models.relationships import DBTeamSeasonCaptain, DBUserSeasonSignup
from app.models.roster_summary import (
    RosterCaptainPublic,
    RosterPlayerPublic,
    TeamRosterSummaryPublic,
)
from app.models.season import Season
from app.models.series import Series
from app.models.team import Team
from app.models.team_season import DBTeamSeason
from app.models.user import User
from app.models.user_battle_tag import UserBattleTag
from app.models.user_team_season import DBUserTeamSeason
from app.models.w3c_stats import W3CStats
from app.services import ladder
from app.services.w3c_stats import in_window, w3c_season


def _points(event_id: int, system: str, wins: int) -> Subquery:
    """The league points of every team of the event, as derived.fill_standings
    sums them: each series pays both sides on the event's scale."""
    one, two = col(Series.player1_score), col(Series.player2_score)
    sides = union_all(
        *(
            select(
                team.label("team_id"),
                points_case(own, opp, system, wins).label("points"),
            )
            .join(Series, col(Series.match_id) == Match.id)
            .where(col(Match.season_id) == event_id)
            for team, own, opp in (
                (col(Match.team1_id), one, two),
                (col(Match.team2_id), two, one),
            )
        )
    ).subquery()
    return (
        select(sides.c.team_id, func.sum(sides.c.points).label("final_score"))
        .group_by(sides.c.team_id)
        .subquery()
    )


def _records(event_id: int, wins: int) -> Subquery:
    """The series every player won and lost in the event, as
    derived._gnl_tallies counts them: a win or a loss once both map scores are
    in and they are not both zero, a win when his score takes the maps a win
    takes."""
    one, two = col(Series.player1_score), col(Series.player2_score)
    sides = union_all(
        *(
            select(player.label("user_id"), own.label("own"), opp.label("opp"))
            .join(Match, col(Match.id) == Series.match_id)
            .where(col(Match.season_id) == event_id)
            for player, own, opp in (
                (col(Series.player1_id), one, two),
                (col(Series.player2_id), two, one),
            )
        )
    ).subquery()
    own, opp = sides.c.own, sides.c.opp
    scored = own.is_not(None) & opp.is_not(None) & ~((own == 0) & (opp == 0))
    return (
        select(
            sides.c.user_id,
            # count() skips the null a case with no else leaves behind
            func.count(case((scored & (own == wins), 1))).label("wins"),
            func.count(case((scored & (own != wins), 1))).label("losses"),
        )
        .group_by(sides.c.user_id)
        .subquery()
    )


def _mmr(
    session: OrmSession,
    event_id: int,
    running: bool,
    signup: Any,  # noqa: ANN401
) -> ColumnElement[int | None]:
    """The MMR each player shows: on a finished event the one he entered it
    with, as derived.fill_user_signup_races reads it; on a running event the
    newest rated row of his signup race in the live W3C window."""
    if not running:
        bound = ladder.w3c_seasons(session, [event_id])
        return ladder.mmr_at(
            col(User.id),
            col(signup.race),
            ladder.midnight_utc(session, col(Season.start_date)),
            select(bound.c.wc3_season).where(bound.c.event_id == event_id),
        )
    return (
        select(col(W3CStats.mmr))
        .where(
            col(W3CStats.user_id) == User.id,
            col(W3CStats.race) == col(signup.race),
            in_window(w3c_season(session)),
            col(W3CStats.mmr).is_not(None),
        )
        .order_by(col(W3CStats.wc3_season).desc())
        .limit(1)
        .correlate_except(W3CStats)
        .scalar_subquery()
    )


def _people(seat: Any, event_id: int, signup: Any) -> Select[Any]:  # noqa: ANN401
    """The seats of the event's teams with their person and his signup."""
    return (
        select(
            col(seat.team_id),
            col(User.id),
            col(User.name),
            col(User.battleTag).label("battleTag"),
            col(User.country),
            col(signup.race).label("signup_race"),
            col(signup.played_as),
        )
        .select_from(seat)
        .join(User, col(User.id) == col(seat.user_id))
        .join(
            signup,
            (col(signup.user_id) == col(seat.user_id))
            & (col(signup.season_id) == event_id),
            isouter=True,
        )
        .where(col(seat.season_id) == event_id)
        .order_by(col(seat.team_id), col(seat.user_id))
    )


def _person(row: Row[Any]) -> dict[str, Any]:
    """The fields a captain and a player share, off a row of _people."""
    return {
        "id": row.id,
        "name": row.name,
        "battleTag": row.battleTag,
        "country": row.country,
        "signup_race": race_value(row.signup_race),
        "played_as": row.played_as,
    }


def _tags(session: OrmSession, user_ids: Sequence[int]) -> dict[int, list[str]]:
    """Every tag of those players, the active one first, as User.battle_tags orders them."""
    found: dict[int, list[str]] = {}
    if not user_ids:
        return found
    for user_id, tag in session.execute(
        select(col(UserBattleTag.user_id), col(UserBattleTag.tag))
        .where(col(UserBattleTag.user_id).in_(user_ids))
        .order_by(
            col(UserBattleTag.user_id),
            col(UserBattleTag.is_active).desc(),
            col(UserBattleTag.id),
        )
    ):
        found.setdefault(user_id, []).append(tag)
    return found


def for_event(
    event_id: int, limit: int = 50, offset: int = 0
) -> list[TeamRosterSummaryPublic]:
    """One page of the event's teams in id order, each with its roster and
    captains of the event."""
    with Session.begin() as session:
        season = session.execute(
            select(
                col(Season.score_system),
                col(Season.map_rules),
                Season.running.label("running"),
            ).where(col(Season.id) == event_id)
        ).first()
        if season is None:
            return []
        system = season.score_system or DEFAULT_SYSTEM
        wins = wins_needed(season.map_rules)
        points = _points(event_id, system, wins)
        teams = session.execute(
            select(
                col(Team.id),
                col(Team.league_id),
                col(Team.name),
                col(Team.long_name),
                col(Team.icon_url),
                func.coalesce(points.c.final_score, 0).label("final_score"),
            )
            .join(points, points.c.team_id == Team.id, isouter=True)
            .where(col(Team.season_info).any(col(DBTeamSeason.season_id) == event_id))
            .order_by(col(Team.id))
            .offset(offset)
            .limit(limit)
        ).all()
        if not teams:
            return []
        team_ids = [team.id for team in teams]

        signup = aliased(DBUserSeasonSignup)
        records = _records(event_id, wins)
        players = session.execute(
            _people(DBUserTeamSeason, event_id, signup)
            .add_columns(
                func.coalesce(records.c.wins, 0).label("wins"),
                func.coalesce(records.c.losses, 0).label("losses"),
                _mmr(session, event_id, bool(season.running), signup).label("mmr"),
            )
            .join(Season, col(Season.id) == DBUserTeamSeason.season_id)
            .join(records, records.c.user_id == DBUserTeamSeason.user_id, isouter=True)
            .where(col(DBUserTeamSeason.team_id).in_(team_ids))
        ).all()
        captains = session.execute(
            _people(DBTeamSeasonCaptain, event_id, aliased(DBUserSeasonSignup)).where(
                col(DBTeamSeasonCaptain.team_id).in_(team_ids)
            )
        ).all()
        tags = _tags(session, sorted({row.id for row in players}))

    roster: dict[int, list[RosterPlayerPublic]] = {}
    for row in players:
        roster.setdefault(row.team_id, []).append(
            RosterPlayerPublic(
                **_person(row),
                tags=tags.get(row.id, []),
                wins=row.wins,
                losses=row.losses,
                mmr=row.mmr,
            )
        )
    seats: dict[int, list[RosterCaptainPublic]] = {}
    for row in captains:
        seats.setdefault(row.team_id, []).append(RosterCaptainPublic(**_person(row)))
    return [
        TeamRosterSummaryPublic(
            id=team.id,
            league_id=team.league_id,
            name=team.name,
            long_name=team.long_name,
            icon_url=team.icon_url,
            final_score=team.final_score,
            players=roster.get(team.id, []),
            captains=seats.get(team.id, []),
        )
        for team in teams
    ]
