"""Insert a small consistent league directly through the models.

Seeding goes through the Session, not through POST endpoints, so no test
setup depends on the write API or its auth.

The league: one season, two teams of two players, one match on playday 1
with two series. Series 1 is played (2-1, standard points 2 and 1),
series 2 has no result yet. One fantasy team with a bet on series 1, one
career stats row per player on team A, one map in the season pool, one
active KOTH event.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import Race
from app.models.fantasy_bet import FantasyBet
from app.models.fantasy_team import FantasyTeam
from app.models.koth_event import KothEvent
from app.models.ladder_achievement import default_rows
from app.models.map import Map
from app.models.match import Match
from app.models.player_career_stats import PlayerCareerStats
from app.models.relationships import DBMapSeason
from app.models.season import Season
from app.models.series import Series
from app.models.settings import Settings
from app.models.team import Team
from app.models.team_season import DBTeamSeason
from app.models.user import User
from app.models.user_team_season import DBUserTeamSeason


def seed_league(session: Session) -> dict[str, Any]:
    season = Season(
        name="Season 1",
        number_weeks=4,
        series_per_week=2,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 2, 27),
    )

    team_a = Team(name="Alpha", long_name="Team Alpha")
    team_b = Team(name="Beta", long_name="Team Beta")

    players = [
        User(
            name="P1",
            battleTag="P1#1111",
            discordTag="p1",
            discordId="1",
            race=Race.HU,
            mmr=1500,
            country="DE",
        ),
        User(
            name="P2",
            battleTag="P2#2222",
            discordTag="p2",
            discordId="2",
            race=Race.OC,
            mmr=1400,
            country="US",
        ),
        User(
            name="P3",
            battleTag="P3#3333",
            discordTag="p3",
            discordId="3",
            race=Race.NE,
            mmr=1600,
            country="FR",
        ),
        User(
            name="P4",
            battleTag="P4#4444",
            discordTag="p4",
            discordId="4",
            race=Race.UD,
            mmr=1300,
            country="SE",
        ),
    ]

    game_map = Map(name="Concealed Hill", shortname="CH")

    session.add_all([season, team_a, team_b, game_map, *players])
    session.flush()

    session.add_all(
        [
            DBTeamSeason(team_id=team_a.id, season_id=season.id),
            DBTeamSeason(team_id=team_b.id, season_id=season.id),
            DBMapSeason(map_id=game_map.id, season_id=season.id),
            DBUserTeamSeason(
                user_id=players[0].id, team_id=team_a.id, season_id=season.id
            ),
            DBUserTeamSeason(
                user_id=players[1].id, team_id=team_a.id, season_id=season.id
            ),
            DBUserTeamSeason(
                user_id=players[2].id, team_id=team_b.id, season_id=season.id
            ),
            DBUserTeamSeason(
                user_id=players[3].id, team_id=team_b.id, season_id=season.id
            ),
        ]
    )

    match = Match(
        team1_id=team_a.id, team2_id=team_b.id, season_id=season.id, playday=1
    )
    session.add(match)
    session.flush()

    series_played = Series(
        match_id=match.id,
        date_time=datetime(2026, 1, 7, 19, 0),
        player1_id=players[0].id,
        player2_id=players[2].id,
        player1_score=2,
        player2_score=1,
        host_player_id=players[0].id,
    )
    series_open = Series(
        match_id=match.id,
        player1_id=players[1].id,
        player2_id=players[3].id,
        host_player_id=players[3].id,
    )
    session.add_all([series_played, series_open])

    fantasy_team = FantasyTeam(
        name="The Optimists",
        season_id=season.id,
        captain_id=players[0].id,
        drafted_team_id=team_a.id,
        drafted_race=Race.HU,
    )
    session.add(fantasy_team)
    session.flush()

    session.add_all(
        [
            FantasyBet(
                season_id=season.id,
                series_id=series_played.id,
                user_id=players[0].id,
                winner_id=players[0].id,
                bet_points=10,
            ),
            PlayerCareerStats(user_id=players[0].id, player_name="P1"),
            PlayerCareerStats(user_id=players[1].id, player_name="P2"),
            Settings(
                key="score_system", value="standard", description="Scoring system"
            ),
            Settings(key="KOTH_NIGHTBOT_TOKEN", value="test-nightbot-token"),
            KothEvent(
                name="KOTH 1", event_date=datetime(2026, 1, 10, 20, 0), is_active=True
            ),
        ]
    )
    session.flush()
    # A real season is created with its achievement set; the fixture matches that
    session.add_all(default_rows(season.id))
    session.flush()

    return {
        "season_id": season.id,
        "team_a_id": team_a.id,
        "team_b_id": team_b.id,
        "player_ids": [p.id for p in players],
        "match_id": match.id,
        "series_played_id": series_played.id,
        "series_open_id": series_open.id,
        "fantasy_team_id": fantasy_team.id,
        "map_id": game_map.id,
    }


def add_bets(session: Session, seeded: dict[str, Any], count: int) -> None:
    """More bets in the seeded season, one per new series of the seeded match.

    The database holds one bet per bettor and series, and one series per pair
    of players inside a match, so bets that pile up need a series and a match
    of their own. Every series repeats the played one, 2-1 to player 1, and
    every bet calls it right for 10 points.
    """
    players = seeded["player_ids"]
    matches = [
        Match(
            team1_id=seeded["team_a_id"],
            team2_id=seeded["team_b_id"],
            season_id=seeded["season_id"],
            playday=index + 2,
        )
        for index in range(count)
    ]
    session.add_all(matches)
    session.flush()
    series = [
        Series(
            match_id=match.id,
            player1_id=players[0],
            player2_id=players[2],
            player1_score=2,
            player2_score=1,
            host_player_id=players[0],
        )
        for match in matches
    ]
    session.add_all(series)
    session.flush()
    session.add_all(
        [
            FantasyBet(
                season_id=seeded["season_id"],
                series_id=one.id,
                user_id=players[1],
                winner_id=players[0],
                bet_points=10,
            )
            for one in series
        ]
    )


def add_fantasy_teams(seeded: dict[str, Any], count: int) -> None:
    """More fantasy teams in the seeded season.

    One captain holds one fantasy team per season, so every extra team is
    drafted by a captain of its own.
    """
    from app.core.db import Session as AppSession  # the factory, not the type

    with AppSession() as session:
        captains = [
            User(
                name=f"Extra cap {index}",
                battleTag=f"ExtraCap{index}#9",
                discordTag=f"extracap{index}",
                discordId=f"90{index}",
                race=Race.HU,
            )
            for index in range(count)
        ]
        session.add_all(captains)
        session.flush()
        session.add_all(
            [
                FantasyTeam(
                    name=f"Extra {index}",
                    season_id=seeded["season_id"],
                    captain_id=captain.id,
                    drafted_team_id=seeded["team_a_id"],
                    drafted_race=Race.HU,
                )
                for index, captain in enumerate(captains)
            ]
        )
        session.commit()
