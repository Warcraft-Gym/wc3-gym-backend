"""Index every foreign key

InnoDB indexed every foreign key column by itself. Postgres does not, so
these 30 columns had no index: a filter on one, and every delete of the
parent row, read the whole child table. The models now say index=True.

Revision ID: 13cb8124202b
Revises: 217f5e71ca84
Create Date: 2026-08-26 20:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "13cb8124202b"
down_revision: str | Sequence[str] | None = "217f5e71ca84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_draft_series_match_id"), "draft_series", ["match_id"], unique=False
    )
    op.create_index(
        op.f("ix_draft_series_player1_id"), "draft_series", ["player1_id"], unique=False
    )
    op.create_index(
        op.f("ix_draft_series_player2_id"), "draft_series", ["player2_id"], unique=False
    )
    op.create_index(
        op.f("ix_fantasy_bets_season_id"), "fantasy_bets", ["season_id"], unique=False
    )
    op.create_index(
        op.f("ix_fantasy_bets_series_id"), "fantasy_bets", ["series_id"], unique=False
    )
    op.create_index(
        op.f("ix_fantasy_bets_user_id"), "fantasy_bets", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_fantasy_bets_winner_id"), "fantasy_bets", ["winner_id"], unique=False
    )
    op.create_index(
        op.f("ix_fantasy_team_player_user_id"),
        "fantasy_team_player",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fantasy_teams_captain_id"),
        "fantasy_teams",
        ["captain_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fantasy_teams_drafted_team_id"),
        "fantasy_teams",
        ["drafted_team_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fantasy_teams_season_id"), "fantasy_teams", ["season_id"], unique=False
    )
    op.create_index(
        op.f("ix_koth_match_participants_match_id"),
        "koth_match_participants",
        ["match_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_koth_match_participants_signup_id"),
        "koth_match_participants",
        ["signup_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_koth_matches_event_id"), "koth_matches", ["event_id"], unique=False
    )
    op.create_index(
        op.f("ix_map_season_season_id"), "map_season", ["season_id"], unique=False
    )
    op.create_index(
        op.f("ix_matches_fixed_map_id"), "matches", ["fixed_map_id"], unique=False
    )
    op.create_index(
        op.f("ix_matches_season_id"), "matches", ["season_id"], unique=False
    )
    op.create_index(op.f("ix_matches_team1_id"), "matches", ["team1_id"], unique=False)
    op.create_index(op.f("ix_matches_team2_id"), "matches", ["team2_id"], unique=False)
    op.create_index(
        op.f("ix_player_career_stats_user_id"),
        "player_career_stats",
        ["user_id"],
        unique=False,
    )
    op.create_index(op.f("ix_series_match_id"), "series", ["match_id"], unique=False)
    op.create_index(
        op.f("ix_series_player1_id"), "series", ["player1_id"], unique=False
    )
    op.create_index(
        op.f("ix_series_player2_id"), "series", ["player2_id"], unique=False
    )
    op.create_index(
        op.f("ix_team_season_coach_1_id"), "team_season", ["coach_1_id"], unique=False
    )
    op.create_index(
        op.f("ix_team_season_coach_2_id"), "team_season", ["coach_2_id"], unique=False
    )
    op.create_index(
        op.f("ix_team_season_coach_3_id"), "team_season", ["coach_3_id"], unique=False
    )
    op.create_index(
        op.f("ix_team_season_season_id"), "team_season", ["season_id"], unique=False
    )
    op.create_index(
        op.f("ix_user_season_signup_season_id"),
        "user_season_signup",
        ["season_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_team_season_season_id"),
        "user_team_season",
        ["season_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_team_season_team_id"),
        "user_team_season",
        ["team_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_team_season_team_id"), table_name="user_team_season")
    op.drop_index(op.f("ix_user_team_season_season_id"), table_name="user_team_season")
    op.drop_index(
        op.f("ix_user_season_signup_season_id"), table_name="user_season_signup"
    )
    op.drop_index(op.f("ix_team_season_season_id"), table_name="team_season")
    op.drop_index(op.f("ix_team_season_coach_3_id"), table_name="team_season")
    op.drop_index(op.f("ix_team_season_coach_2_id"), table_name="team_season")
    op.drop_index(op.f("ix_team_season_coach_1_id"), table_name="team_season")
    op.drop_index(op.f("ix_series_player2_id"), table_name="series")
    op.drop_index(op.f("ix_series_player1_id"), table_name="series")
    op.drop_index(op.f("ix_series_match_id"), table_name="series")
    op.drop_index(
        op.f("ix_player_career_stats_user_id"), table_name="player_career_stats"
    )
    op.drop_index(op.f("ix_matches_team2_id"), table_name="matches")
    op.drop_index(op.f("ix_matches_team1_id"), table_name="matches")
    op.drop_index(op.f("ix_matches_season_id"), table_name="matches")
    op.drop_index(op.f("ix_matches_fixed_map_id"), table_name="matches")
    op.drop_index(op.f("ix_map_season_season_id"), table_name="map_season")
    op.drop_index(op.f("ix_koth_matches_event_id"), table_name="koth_matches")
    op.drop_index(
        op.f("ix_koth_match_participants_signup_id"),
        table_name="koth_match_participants",
    )
    op.drop_index(
        op.f("ix_koth_match_participants_match_id"),
        table_name="koth_match_participants",
    )
    op.drop_index(op.f("ix_fantasy_teams_season_id"), table_name="fantasy_teams")
    op.drop_index(op.f("ix_fantasy_teams_drafted_team_id"), table_name="fantasy_teams")
    op.drop_index(op.f("ix_fantasy_teams_captain_id"), table_name="fantasy_teams")
    op.drop_index(
        op.f("ix_fantasy_team_player_user_id"), table_name="fantasy_team_player"
    )
    op.drop_index(op.f("ix_fantasy_bets_winner_id"), table_name="fantasy_bets")
    op.drop_index(op.f("ix_fantasy_bets_user_id"), table_name="fantasy_bets")
    op.drop_index(op.f("ix_fantasy_bets_series_id"), table_name="fantasy_bets")
    op.drop_index(op.f("ix_fantasy_bets_season_id"), table_name="fantasy_bets")
    op.drop_index(op.f("ix_draft_series_player2_id"), table_name="draft_series")
    op.drop_index(op.f("ix_draft_series_player1_id"), table_name="draft_series")
    op.drop_index(op.f("ix_draft_series_match_id"), table_name="draft_series")
