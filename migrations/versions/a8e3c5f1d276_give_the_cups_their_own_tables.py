"""Give the cups their own tables: cup series and cup teams

A cup's series move out of `series` into `cup_series`, with its games, veto
steps and sides in tables of their own, and a cup's teams move out of the
GNL team tables into `cup_team` and `cup_team_member`. The invitations of a
cup team follow as `cup_team_invite`. GNL and KOTH keep the tables they had,
and `teams` loses the cup column it took for the team cups: every team names
its league again.

No cup was played on a live database, so nothing is copied over: the draws
and the teams of the cups made while testing are deleted, and those cups
keep their stages, rounds and solo entrants. A team cup loses its teams.

Revision ID: a8e3c5f1d276
Revises: c4e8a2f7d915
Create Date: 2026-10-12 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a8e3c5f1d276"
down_revision: str | Sequence[str] | None = "c4e8a2f7d915"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RACES = ("RANDOM", "HU", "OC", "NE", "UD")
# The rounds of every cup, which the cup series of the draws hang off
CUP_ROUNDS = (
    "SELECT r.id FROM event_round r JOIN event e ON e.id = r.season_id "
    "WHERE e.kind = 'cup'"
)
CUP_SERIES = f"SELECT id FROM series WHERE round_id IN ({CUP_ROUNDS})"
CUP_TEAMS = (
    "SELECT t.id FROM teams t JOIN event e ON e.id = t.event_id WHERE e.kind = 'cup'"
)
SERIES_POSTS = "('result', 'result_change', 'cast', 'reminder', 'veto', 'announce')"
ONE_ENTRANT = (
    "(CASE WHEN user_id IS NULL THEN 0 ELSE 1 END "
    "+ CASE WHEN team_id IS NULL THEN 0 ELSE 1 END "
    "+ CASE WHEN historical_participant_id IS NULL THEN 0 ELSE 1 END) = 1"
)
ONE_ENTRANT_WITH_CUP_TEAM = (
    "(CASE WHEN user_id IS NULL THEN 0 ELSE 1 END "
    "+ CASE WHEN team_id IS NULL THEN 0 ELSE 1 END "
    "+ CASE WHEN cup_team_id IS NULL THEN 0 ELSE 1 END "
    "+ CASE WHEN historical_participant_id IS NULL THEN 0 ELSE 1 END) = 1"
)


def race_type() -> sa.Enum:
    """The race enum. Postgres already holds the type, so it is not created again."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*RACES, name="race", create_type=False)
    return sa.Enum(*RACES, name="race")


def _delete_test_cups() -> None:
    """Delete the draws and the teams the cups made while testing hold."""
    op.execute(
        f"DELETE FROM discord_post WHERE kind IN {SERIES_POSTS} "
        f"AND subject_id IN ({CUP_SERIES})"
    )
    # The keys of a series take its games, vetoes, sides, replays and casts along
    op.execute(f"DELETE FROM series WHERE id IN ({CUP_SERIES})")
    op.execute(f"DELETE FROM matches WHERE round_id IN ({CUP_ROUNDS})")
    op.execute(
        "DELETE FROM event_entrant WHERE team_id IS NOT NULL AND event_id IN "
        "(SELECT id FROM event WHERE kind = 'cup')"
    )
    op.execute(
        "DELETE FROM event_award WHERE event_id IN "
        "(SELECT id FROM event WHERE kind = 'cup')"
    )
    for table in ("user_team_season", "team_season_captain", "team_season"):
        op.execute(f"DELETE FROM {table} WHERE team_id IN ({CUP_TEAMS})")
    op.execute(f"DELETE FROM teams WHERE id IN ({CUP_TEAMS})")


def _create_team_invite() -> None:
    """The invitation table as the team cups first wrote it, onto `teams`."""
    op.create_table(
        "team_invite",
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_team_invite_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_team_invite_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_team_invite_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("team_id", "user_id", name=op.f("pk_team_invite")),
    )
    op.create_index(
        op.f("ix_team_invite_user_id"), "team_invite", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_team_invite_event_id"), "team_invite", ["event_id"], unique=False
    )


def _create_cup_teams() -> None:
    op.create_table(
        "cup_team",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_cup_team_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cup_team")),
    )
    op.create_index(op.f("ix_cup_team_event_id"), "cup_team", ["event_id"])
    op.create_table(
        "cup_team_member",
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("captain", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["cup_team.id"],
            name=op.f("fk_cup_team_member_team_id_cup_team"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_cup_team_member_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("team_id", "user_id", name=op.f("pk_cup_team_member")),
    )
    op.create_index(op.f("ix_cup_team_member_user_id"), "cup_team_member", ["user_id"])
    op.create_table(
        "cup_team_invite",
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["cup_team.id"],
            name=op.f("fk_cup_team_invite_team_id_cup_team"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_cup_team_invite_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_cup_team_invite_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("team_id", "user_id", name=op.f("pk_cup_team_invite")),
    )
    op.create_index(op.f("ix_cup_team_invite_user_id"), "cup_team_invite", ["user_id"])
    op.create_index(
        op.f("ix_cup_team_invite_event_id"), "cup_team_invite", ["event_id"]
    )


def _create_cup_series() -> None:
    op.create_table(
        "cup_series",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("division_id", sa.Integer(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("entrant1_id", sa.Integer(), nullable=True),
        sa.Column("entrant2_id", sa.Integer(), nullable=True),
        sa.Column("player1_id", sa.Integer(), nullable=True),
        sa.Column("player2_id", sa.Integer(), nullable=True),
        sa.Column("player1_score", sa.Integer(), nullable=True),
        sa.Column("player2_score", sa.Integer(), nullable=True),
        sa.Column(
            "result_kind",
            sa.String(length=10),
            server_default="played",
            nullable=False,
        ),
        sa.Column("player1_off_race", race_type(), nullable=True),
        sa.Column("player2_off_race", race_type(), nullable=True),
        sa.Column("side_size", sa.Integer(), server_default="1", nullable=False),
        sa.Column("slot1_from_series_id", sa.Integer(), nullable=True),
        sa.Column(
            "slot1_takes_loser", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("slot2_from_series_id", sa.Integer(), nullable=True),
        sa.Column(
            "slot2_takes_loser", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["event_round.id"],
            name=op.f("fk_cup_series_round_id_event_round"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["division_id"],
            ["event_division.id"],
            name=op.f("fk_cup_series_division_id_event_division"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entrant1_id"],
            ["event_entrant.id"],
            name=op.f("fk_cup_series_entrant1_id_event_entrant"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entrant2_id"],
            ["event_entrant.id"],
            name=op.f("fk_cup_series_entrant2_id_event_entrant"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["player1_id"],
            ["users.id"],
            name=op.f("fk_cup_series_player1_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["player2_id"],
            ["users.id"],
            name=op.f("fk_cup_series_player2_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["slot1_from_series_id"],
            ["cup_series.id"],
            name=op.f("fk_cup_series_slot1_from_series_id_cup_series"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["slot2_from_series_id"],
            ["cup_series.id"],
            name=op.f("fk_cup_series_slot2_from_series_id_cup_series"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cup_series")),
    )
    for column in (
        "round_id",
        "entrant1_id",
        "entrant2_id",
        "player1_id",
        "player2_id",
    ):
        op.create_index(op.f(f"ix_cup_series_{column}"), "cup_series", [column])
    op.create_table(
        "cup_series_game",
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("game_no", sa.Integer(), nullable=False),
        sa.Column("winner_side", sa.String(length=1), nullable=True),
        sa.Column("map_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["cup_series.id"],
            name=op.f("fk_cup_series_game_series_id_cup_series"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["map_id"],
            ["maps.id"],
            name=op.f("fk_cup_series_game_map_id_maps"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "series_id", "game_no", name=op.f("pk_cup_series_game")
        ),
    )
    op.create_table(
        "cup_veto_step",
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=1), nullable=False),
        sa.Column("action", sa.String(length=4), nullable=False),
        sa.Column("map_id", sa.Integer(), nullable=False),
        sa.Column("entered_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["cup_series.id"],
            name=op.f("fk_cup_veto_step_series_id_cup_series"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["map_id"], ["maps.id"], name=op.f("fk_cup_veto_step_map_id_maps")
        ),
        sa.ForeignKeyConstraint(
            ["entered_by"],
            ["users.id"],
            name=op.f("fk_cup_veto_step_entered_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("series_id", "step_no", name=op.f("pk_cup_veto_step")),
    )
    op.create_table(
        "cup_series_side",
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("side_no", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), server_default="0", nullable=False),
        sa.Column("entrant_id", sa.Integer(), nullable=True),
        sa.Column("place", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["cup_series.id"],
            name=op.f("fk_cup_series_side_series_id_cup_series"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entrant_id"],
            ["event_entrant.id"],
            name=op.f("fk_cup_series_side_entrant_id_event_entrant"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "series_id", "side_no", "user_id", name=op.f("pk_cup_series_side")
        ),
    )
    op.create_index(op.f("ix_cup_series_side_user_id"), "cup_series_side", ["user_id"])


def upgrade() -> None:
    _delete_test_cups()
    with op.batch_alter_table("teams") as batch:
        batch.drop_constraint(op.f("fk_teams_event_id_event"), type_="foreignkey")
        batch.drop_index(op.f("ix_teams_event_id"))
        batch.drop_column("event_id")
        batch.alter_column("league_id", existing_type=sa.Integer(), nullable=False)
    op.drop_index(op.f("ix_team_invite_event_id"), table_name="team_invite")
    op.drop_index(op.f("ix_team_invite_user_id"), table_name="team_invite")
    op.drop_table("team_invite")
    _create_cup_teams()
    _create_cup_series()
    with op.batch_alter_table("event_entrant") as batch:
        batch.add_column(sa.Column("cup_team_id", sa.Integer(), nullable=True))
        batch.create_unique_constraint(
            op.f("uq_event_entrant_cup_team_id"), ["cup_team_id"]
        )
        batch.create_foreign_key(
            op.f("fk_event_entrant_cup_team_id_cup_team"),
            "cup_team",
            ["cup_team_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.drop_constraint(op.f("ck_event_entrant_one_entrant"), type_="check")
        batch.create_check_constraint(
            op.f("ck_event_entrant_one_entrant"), ONE_ENTRANT_WITH_CUP_TEAM
        )


def downgrade() -> None:
    # A cup team has no row in the older schema, so its entrants go with it
    op.execute("DELETE FROM event_entrant WHERE cup_team_id IS NOT NULL")
    with op.batch_alter_table("event_entrant") as batch:
        batch.drop_constraint(
            op.f("fk_event_entrant_cup_team_id_cup_team"), type_="foreignkey"
        )
        batch.drop_constraint(op.f("uq_event_entrant_cup_team_id"), type_="unique")
        batch.drop_constraint(op.f("ck_event_entrant_one_entrant"), type_="check")
        batch.drop_column("cup_team_id")
        batch.create_check_constraint(op.f("ck_event_entrant_one_entrant"), ONE_ENTRANT)
    op.drop_index(op.f("ix_cup_series_side_user_id"), table_name="cup_series_side")
    for table in ("cup_series_side", "cup_veto_step", "cup_series_game"):
        op.drop_table(table)
    for column in (
        "round_id",
        "entrant1_id",
        "entrant2_id",
        "player1_id",
        "player2_id",
    ):
        op.drop_index(op.f(f"ix_cup_series_{column}"), table_name="cup_series")
    op.drop_table("cup_series")
    op.drop_index(op.f("ix_cup_team_invite_event_id"), table_name="cup_team_invite")
    op.drop_index(op.f("ix_cup_team_invite_user_id"), table_name="cup_team_invite")
    op.drop_table("cup_team_invite")
    op.drop_index(op.f("ix_cup_team_member_user_id"), table_name="cup_team_member")
    op.drop_table("cup_team_member")
    op.drop_index(op.f("ix_cup_team_event_id"), table_name="cup_team")
    op.drop_table("cup_team")
    with op.batch_alter_table("teams") as batch:
        batch.alter_column("league_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("event_id", sa.Integer(), nullable=True))
        batch.create_index(op.f("ix_teams_event_id"), ["event_id"], unique=False)
        batch.create_foreign_key(
            op.f("fk_teams_event_id_event"),
            "event",
            ["event_id"],
            ["id"],
            ondelete="CASCADE",
        )
    _create_team_invite()
