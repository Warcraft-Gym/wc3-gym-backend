"""Drop the old KOTH tables and the compatibility views

The contract drop of the events model, one deploy after every reader moved.
`app/services/koth/legacy.py` answers every old /koth/* path from the event
model and the nightly backfill writes onto the model, so the four koth_*
tables hold history alone and go, and `koth_events.round_id` goes with its
table. The `season_rounds` and `user_season_availability` views stood in for
the renamed tables while the running deploy read them; nothing reads them now.

CSV copies of the four tables and of alembic_version were taken from prod
first: 2 nights, 9 signups, 1 match, 1 match participant, at c9f2b6a41d38.

The downgrade builds the four tables and the two views again. It restores no
row: the rows live in those CSV copies.

Revision ID: e7d4b1c6a539
Revises: c9f2b6a41d38
Create Date: 2026-09-14 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e7d4b1c6a539"
down_revision: str | Sequence[str] | None = "c9f2b6a41d38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RACES = ("RANDOM", "HU", "OC", "NE", "UD")
# The two views of 96c0d36de81c, in the words that migration wrote them with
ROUNDS_VIEW = (
    "CREATE VIEW season_rounds AS SELECT season_id, number AS playday, "
    "start_date, end_date, map_id FROM event_round"
)
AVAILABILITY_VIEW = (
    "CREATE VIEW user_season_availability AS SELECT user_id, season_id, playday, "
    "available, set_by_user_id FROM round_availability"
)
# The computed columns the two natural keys of a signup stand on
ACTIVE_TWITCH_USERNAME = (
    "CASE WHEN is_active = 1 AND twitch_username <> '' THEN twitch_username END"
)
ACTIVE_BATTLE_TAG = "CASE WHEN is_active = 1 THEN lower(trim(battle_tag)) END"


def race_type() -> sa.Enum:
    """The race enum. Postgres already holds the type, so it is not created again."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*RACES, name="race", create_type=False)
    return sa.Enum(*RACES, name="race")


def upgrade() -> None:
    op.execute("DROP VIEW user_season_availability")
    op.execute("DROP VIEW season_rounds")

    # A child goes before its parent, so no key names a table that is gone
    op.drop_table("koth_match_participants")
    op.drop_table("koth_matches")
    op.drop_table("koth_signups")
    op.drop_table("koth_events")


def downgrade() -> None:
    op.create_table(
        "koth_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("bracket_1_threshold", sa.Integer(), nullable=False),
        sa.Column("bracket_2_threshold", sa.Integer(), nullable=False),
        # A night outlives its round, so the key clears the column
        sa.Column("round_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["event_round.id"],
            name=op.f("fk_koth_events_round_id_event_round"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_koth_events")),
    )
    op.create_index(op.f("ix_koth_events_round_id"), "koth_events", ["round_id"])

    op.create_table(
        "koth_signups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("twitch_username", sa.String(length=50), nullable=True),
        sa.Column("battle_tag", sa.String(length=50), nullable=False),
        sa.Column("w3c_name", sa.String(length=50), nullable=False),
        sa.Column("race", race_type(), nullable=False),
        sa.Column("mmr", sa.Integer(), nullable=False),
        sa.Column("bracket", sa.Integer(), nullable=False),
        sa.Column("is_king", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False),
        # The database computes these two; the application never writes them
        sa.Column(
            "active_twitch_username",
            sa.String(length=50),
            sa.Computed(ACTIVE_TWITCH_USERNAME),
            nullable=True,
        ),
        sa.Column(
            "active_battle_tag",
            sa.String(length=50),
            sa.Computed(ACTIVE_BATTLE_TAG),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["koth_events.id"],
            name=op.f("fk_koth_signups_event_id_koth_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_koth_signups")),
    )
    op.create_index(
        "uq_koth_signups_active_twitch_username_race",
        "koth_signups",
        ["event_id", "active_twitch_username", "race"],
        unique=True,
    )
    op.create_index(
        "uq_koth_signups_active_battle_tag_race",
        "koth_signups",
        ["event_id", "active_battle_tag", "race"],
        unique=True,
    )

    op.create_table(
        "koth_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("bracket", sa.Integer(), nullable=False),
        sa.Column("game_mode", sa.String(length=50), nullable=False),
        sa.Column("num_teams", sa.Integer(), nullable=False),
        sa.Column("winner_team_number", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["koth_events.id"],
            name=op.f("fk_koth_matches_event_id_koth_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_koth_matches")),
    )
    op.create_index(op.f("ix_koth_matches_event_id"), "koth_matches", ["event_id"])

    op.create_table(
        "koth_match_participants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("signup_id", sa.Integer(), nullable=False),
        sa.Column("team_number", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["koth_matches.id"],
            name=op.f("fk_koth_match_participants_match_id_koth_matches"),
        ),
        sa.ForeignKeyConstraint(
            ["signup_id"],
            ["koth_signups.id"],
            name=op.f("fk_koth_match_participants_signup_id_koth_signups"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_koth_match_participants")),
    )
    op.create_index(
        op.f("ix_koth_match_participants_match_id"),
        "koth_match_participants",
        ["match_id"],
    )
    op.create_index(
        op.f("ix_koth_match_participants_signup_id"),
        "koth_match_participants",
        ["signup_id"],
    )

    op.execute(ROUNDS_VIEW)
    op.execute(AVAILABILITY_VIEW)
