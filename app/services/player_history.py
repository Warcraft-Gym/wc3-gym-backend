"""What one player did in the league, derived at read time.

Nine statements answer the whole page, and none of them grows with the number
of events or opponents: one reads every series the player stood in with its
event and its opponent, one the teams they were rostered on, one the events
they entered as an entrant, one the teams each of those events held, one the
current season setting, a pair reads the maps of the played series (the fixed
map and the veto picks), and the last pair is the score system and the points
of every team, borrowed from app.services.derived.

Every kind of event answers here. A GNL series hangs off a fixture, which
names the season; a bracket series has no fixture and names its round, which
names the event. The entrant read carries an event the player entered but has
played no series in yet.

A series with no map score is unplayed: it pays no record and shows in no
meeting. A won series is one the player took more maps in, as the career
totals count it, so a drawn series is neither won nor lost.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, func, select, union_all
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import aliased
from sqlmodel import col

from app.core.db import Session
from app.core.fantasy import race_value
from app.models.enums import EventKind
from app.models.event_entrant import EventEntrant
from app.models.map import Map
from app.models.match import Match
from app.models.player_history import (
    HistoryEvent,
    HistoryMeeting,
    HistoryOpponent,
    PlayerHistory,
)
from app.models.relationships import DBEventRound, DBUserSeasonSignup
from app.models.season import LEAGUE_SHORT_NAME, Season
from app.models.series import Series
from app.models.series_veto_step import DBSeriesVetoStep
from app.models.settings import Settings
from app.models.team import Team
from app.models.team_season import DBTeamSeason
from app.models.types import utcnow
from app.models.user import User
from app.models.user_team_season import DBUserTeamSeason
from app.services import derived

# season -> the team the player was on, its name, the season name and its league
type Rosters = dict[int, tuple[int, str | None, str, str | None]]
# (team, season) -> where the team finished and how many teams stood
type Places = dict[tuple[int, int], tuple[int, int]]
# event -> the row of the event the player entered as an entrant
type Entered = dict[int, Row[Any]]


def _meetings(session: OrmSession, user_id: int) -> Sequence[Row[Any]]:
    """Every series the player stood in, newest first, in one statement.

    A series holds the player on either side, so the two sides union and the
    other side is the opponent. The fixture is left joined: a bracket series
    has none, and names its event through the round it is played in.
    """
    opponent1, opponent2 = aliased(User), aliased(User)
    signup1, signup2 = aliased(DBUserSeasonSignup), aliased(DBUserSeasonSignup)
    mine1, mine2 = aliased(DBUserSeasonSignup), aliased(DBUserSeasonSignup)
    sides = union_all(
        select(
            col(Series.id).label("series_id"),
            func.coalesce(Match.season_id, DBEventRound.season_id).label("season_id"),
            func.coalesce(Match.playday, DBEventRound.number).label("playday"),
            col(Series.date_time).label("date_time"),
            func.coalesce(Series.player1_score, 0).label("own"),
            func.coalesce(Series.player2_score, 0).label("opp"),
            col(opponent1.id).label("opponent_id"),
            col(opponent1.name).label("opponent_name"),
            derived.race_of(col(Series.player2_off_race), signup1).label("race"),
            derived.race_of(col(Series.player1_off_race), mine1).label("my_race"),
            col(opponent1.country).label("country"),
        )
        .join(Match, col(Match.id) == Series.match_id, isouter=True)
        .join(DBEventRound, col(DBEventRound.id) == Series.round_id, isouter=True)
        .join(opponent1, col(opponent1.id) == Series.player2_id)
        .join(signup1, derived.signup_on(signup1, col(Series.player2_id)), isouter=True)
        .join(mine1, derived.signup_on(mine1, col(Series.player1_id)), isouter=True)
        .where(col(Series.player1_id) == user_id),
        select(
            col(Series.id),
            func.coalesce(Match.season_id, DBEventRound.season_id),
            func.coalesce(Match.playday, DBEventRound.number),
            col(Series.date_time),
            func.coalesce(Series.player2_score, 0),
            func.coalesce(Series.player1_score, 0),
            col(opponent2.id),
            col(opponent2.name),
            derived.race_of(col(Series.player1_off_race), signup2).label("race"),
            derived.race_of(col(Series.player2_off_race), mine2).label("my_race"),
            col(opponent2.country),
        )
        .join(Match, col(Match.id) == Series.match_id, isouter=True)
        .join(DBEventRound, col(DBEventRound.id) == Series.round_id, isouter=True)
        .join(opponent2, col(opponent2.id) == Series.player1_id)
        .join(signup2, derived.signup_on(signup2, col(Series.player1_id)), isouter=True)
        .join(mine2, derived.signup_on(mine2, col(Series.player2_id)), isouter=True)
        .where(col(Series.player2_id) == user_id),
    ).subquery()

    return session.execute(
        select(
            sides,
            col(Season.name).label("season_name"),
            LEAGUE_SHORT_NAME,
            col(Season.kind).label("kind"),
        )
        .join(Season, col(Season.id) == sides.c.season_id)
        .order_by(
            sides.c.season_id.desc(), sides.c.playday.desc(), sides.c.series_id.desc()
        )
    ).all()


def _rosters(session: OrmSession, user_id: int) -> Rosters:
    """The team the player was rostered on in every season, in one statement."""
    rows = session.execute(
        select(
            col(DBUserTeamSeason.season_id),
            col(DBUserTeamSeason.team_id),
            col(Team.name),
            col(Season.name),
            LEAGUE_SHORT_NAME,
        )
        .join(Team, col(Team.id) == DBUserTeamSeason.team_id)
        .join(Season, col(Season.id) == DBUserTeamSeason.season_id)
        .where(col(DBUserTeamSeason.user_id) == user_id)
    ).all()
    return {
        season_id: (team_id, team_name, season_name, league)
        for season_id, team_id, team_name, season_name, league in rows
    }


def _entered(session: OrmSession, user_id: int) -> Entered:
    """Every event the player stands in as an entrant, in one statement.

    A GNL season signs its players up through the signup table, so this read
    carries the other kinds: a cup the player entered answers here from the
    moment they signed up, whether or not a bracket exists yet. A withdrawn
    entrant stands in the event no more.
    """
    rows = session.execute(
        select(
            col(Season.id).label("season_id"),
            col(Season.name).label("season_name"),
            LEAGUE_SHORT_NAME,
            col(Season.kind).label("kind"),
            col(Season.start_date).label("start_date"),
            col(Season.end_date).label("end_date"),
        )
        .join(EventEntrant, col(EventEntrant.event_id) == Season.id)
        .where(
            col(EventEntrant.user_id) == user_id,
            col(EventEntrant.withdrawn_at).is_(None),
        )
    ).all()
    return {row.season_id: row for row in rows}


def _runs_today(row: Row[Any] | None) -> bool:
    """An event the player entered is running when today falls in its window."""
    if row is None or row.start_date is None:
        return False
    today = utcnow().date()
    return row.start_date <= today and (row.end_date is None or today <= row.end_date)


def _places(session: OrmSession, season_ids: set[int]) -> Places:
    """Where every team of those seasons finished, by the points it scored.

    Teams that scored the same share a place, and the next team takes the one
    after. A season no team has scored in yet stands nowhere, so it answers
    nothing rather than a made-up first place.
    """
    rules = derived._rules_by_season(session, season_ids)
    sums = derived._sums_by_team(session, rules)
    rows = session.execute(
        select(col(DBTeamSeason.season_id), col(DBTeamSeason.team_id)).where(
            col(DBTeamSeason.season_id).in_(season_ids)
        )
    ).all()

    by_season: dict[int, list[int]] = {}
    for season_id, team_id in rows:
        by_season.setdefault(season_id, []).append(team_id)

    places: Places = {}
    for season_id, team_ids in by_season.items():
        scores = {
            team_id: sums.get((team_id, season_id), [0, 0])[0] for team_id in team_ids
        }
        if not any(scores.values()):
            continue
        for team_id, score in scores.items():
            ahead = sum(1 for other in scores.values() if other > score)
            places[(team_id, season_id)] = (ahead + 1, len(team_ids))
    return places


def _events(
    rows: Sequence[Row[Any]],
    rosters: Rosters,
    entered: Entered,
    places: Places,
    current_id: int | None,
) -> list[HistoryEvent]:
    """One row per event the player was rostered in, entered, or played in.

    A rostered event is a team league, so its kind is the default; the played
    series and the entrant rows carry the kind of every other event.
    """
    names = {season_id: name for season_id, (_, _, name, _) in rosters.items()}
    names |= {row.season_id: row.season_name for row in rows}
    names |= {row.season_id: row.season_name for row in entered.values()}
    leagues = {season_id: one for season_id, (_, _, _, one) in rosters.items()}
    leagues |= {row.season_id: row.league_short_name for row in rows}
    leagues |= {row.season_id: row.league_short_name for row in entered.values()}
    kinds = {row.season_id: row.kind for row in rows}
    kinds |= {row.season_id: row.kind for row in entered.values()}

    tallies: dict[int, list[int]] = {}
    for row in rows:
        if row.own == 0 and row.opp == 0:
            continue
        tally = tallies.setdefault(row.season_id, [0, 0, 0])
        tally[0] += 1
        if row.own > row.opp:
            tally[1] += 1
        elif row.opp > row.own:
            tally[2] += 1

    events = []
    for season_id in sorted(names, reverse=True):
        team_id, team_name, _, _ = rosters.get(season_id, (None, None, None, None))
        played, won, lost = tallies.get(season_id, [0, 0, 0])
        place, team_count = places.get((team_id, season_id), (None, None))
        events.append(
            HistoryEvent(
                season_id=season_id,
                season_name=names[season_id],
                league_short_name=leagues.get(season_id),
                kind=kinds.get(season_id, EventKind.gnl),
                team_id=team_id,
                team_name=team_name,
                played=played,
                won=won,
                lost=lost,
                place=place,
                team_count=team_count,
                running=season_id == current_id or _runs_today(entered.get(season_id)),
            )
        )
    return events


def _series_maps(session: OrmSession, series_ids: set[int]) -> dict[int, list[str]]:
    """The maps of every played series: the match's fixed map, then the picks.

    Which game ran on which map, and who won it, is stored nowhere, so the
    names are all there is to tell.
    """
    if not series_ids:
        return {}
    maps: dict[int, list[str]] = {}
    fixed = session.execute(
        select(col(Series.id), col(Map.name))
        .join(Match, col(Match.id) == Series.match_id)
        .join(Map, col(Map.id) == Match.fixed_map_id)
        .where(col(Series.id).in_(series_ids))
    ).all()
    for series_id, name in fixed:
        maps.setdefault(series_id, []).append(name)
    picks = session.execute(
        select(col(DBSeriesVetoStep.series_id), col(Map.name))
        .join(Map, col(Map.id) == DBSeriesVetoStep.map_id)
        .where(
            col(DBSeriesVetoStep.series_id).in_(series_ids),
            col(DBSeriesVetoStep.action) == "pick",
        )
        .order_by(col(DBSeriesVetoStep.series_id), col(DBSeriesVetoStep.step_no))
    ).all()
    for series_id, name in picks:
        maps.setdefault(series_id, []).append(name)
    return maps


def _opponents(
    rows: Sequence[Row[Any]], maps: dict[int, list[str]]
) -> list[HistoryOpponent]:
    """One row per opponent the player ever played, most met first.

    The rows arrive newest first, so the first one an opponent shows in is the
    last time the two met.
    """
    opponents: dict[int, HistoryOpponent] = {}
    for row in rows:
        if row.own == 0 and row.opp == 0:
            continue
        opponent = opponents.get(row.opponent_id)
        if opponent is None:
            opponent = opponents[row.opponent_id] = HistoryOpponent(
                id=row.opponent_id,
                name=row.opponent_name,
                race=race_value(row.race),
                country=row.country,
                played=0,
                won=0,
                lost=0,
                last_season_name=row.season_name,
                last_playday=row.playday,
                meetings=[],
            )
        opponent.played += 1
        if row.own > row.opp:
            opponent.won += 1
        elif row.opp > row.own:
            opponent.lost += 1
        opponent.meetings.append(
            HistoryMeeting(
                series_id=row.series_id,
                season_id=row.season_id,
                season_name=row.season_name,
                league_short_name=row.league_short_name,
                kind=row.kind,
                playday=row.playday,
                my_score=row.own,
                their_score=row.opp,
                date_time=row.date_time,
                my_race=race_value(row.my_race),
                their_race=race_value(row.race),
                maps=maps.get(row.series_id, []),
            )
        )
    return sorted(opponents.values(), key=lambda one: (-one.played, one.name or ""))


def history(user_id: int) -> PlayerHistory:
    """Every event the player took part in, and every opponent they ever met."""
    with Session.begin() as session:
        rows = _meetings(session, user_id)
        rosters = _rosters(session, user_id)
        entered = _entered(session, user_id)
        season_ids = {row.season_id for row in rows} | set(rosters) | set(entered)
        played_ids = {row.series_id for row in rows if row.own or row.opp}
        current = Settings.get_by_key(session, "current_gnl_season")
        value = current.value if current else None
        return PlayerHistory(
            events=_events(
                rows,
                rosters,
                entered,
                _places(session, season_ids),
                int(value) if value and value.isdigit() else None,
            ),
            opponents=_opponents(rows, _series_maps(session, played_ids)),
        )
