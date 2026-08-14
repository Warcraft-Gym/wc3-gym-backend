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

from app.models.enums import Race
from app.models.fantasy_bet import DBFantasyBet
from app.models.fantasy_team import DBFantasyTeam
from app.models.koth_event import KothEvent
from app.models.map import Map
from app.models.match import Match
from app.models.player_career_stats import DBPlayerCareerStats
from app.models.relationships import DBMapSeason, DBTeamSeason, DBUserTeamSeason
from app.models.season import Season
from app.models.series import Series
from app.models.settings import Settings
from app.models.team import Team
from app.models.user import User


def seed_league(session):
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
        player1_points=2,
        player2_points=1,
        host_player_id=players[0].id,
    )
    series_open = Series(
        match_id=match.id,
        player1_id=players[1].id,
        player2_id=players[3].id,
        host_player_id=players[3].id,
    )
    session.add_all([series_played, series_open])

    fantasy_team = DBFantasyTeam(
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
            DBFantasyBet(
                season_id=season.id,
                series_id=series_played.id,
                user_id=players[0].id,
                winner_id=players[0].id,
                bet_points=10,
            ),
            DBPlayerCareerStats(
                user_id=players[0].id,
                player_name="P1",
                series_won=1,
                games_won=2,
                games_lost=1,
            ),
            DBPlayerCareerStats(user_id=players[1].id, player_name="P2"),
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
