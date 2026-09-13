"""The parent event and the series feeders

The fourth deploy of the events model, and every change is additive. An event
gains a parent, so a qualifier hangs off the event it feeds; a signup policy,
so a KOTH night takes a battle tag where a season takes a member; and the
entrant kind its league enters with.

GNL is its own stage format: the admin sets the fixtures of a round and the
captains draft the series inside them, which is not a round robin. The 4a
backfill wrote `round_robin` on the GNL stages and this corrects it.

An entrant is a player or a pre-made team, so `user_id` turns nullable, a
`team_id` arrives beside it and a check keeps exactly one of the two filled.
A series gains the feeder graph the bracket engine fills from: each slot
takes the winner, or the loser, of another series, so a generated series has
no sides until its feeders are scored and its player ids turn nullable too.
Every series that exists keeps both sides, so the GNL payloads are unchanged.

Revision ID: 3d5e9a1c7b62
Revises: 96c0d36de81c
Create Date: 2026-09-13 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3d5e9a1c7b62"
down_revision: str | Sequence[str] | None = "96c0d36de81c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIGNUP_POLICY = ("members", "anyone")
ENTRANT_KIND = ("solo", "team", "drafted_teams")
# Postgres counts the filled columns with one call; SQLite adds the two tests
ONE_ENTRANT = {
    "postgresql": "num_nonnulls(user_id, team_id) = 1",
    "sqlite": (
        "(CASE WHEN user_id IS NULL THEN 0 ELSE 1 END "
        "+ CASE WHEN team_id IS NULL THEN 0 ELSE 1 END) = 1"
    ),
}


def enum_type(name: str, values: tuple[str, ...]) -> sa.Enum:
    """A reference to an enum type that already exists on Postgres."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def event_columns() -> list[sa.Column]:
    """The columns an event gains: its parent, its policy and its entrant kind."""
    return [
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column(
            "signup_policy",
            enum_type("signuppolicy", SIGNUP_POLICY),
            nullable=False,
            server_default="members",
        ),
        sa.Column(
            "entrant_kind",
            enum_type("entrantkind", ENTRANT_KIND),
            nullable=False,
            server_default="solo",
        ),
    ]


def entrant_columns() -> list[sa.Column]:
    """The columns an entrant row gains, all nullable or defaulted."""
    return [
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("mmr_at_seed", sa.Integer(), nullable=True),
        sa.Column("seed_source", sa.String(length=20), nullable=True),
        sa.Column(
            "manual_placement",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("qualified_from_event_id", sa.Integer(), nullable=True),
    ]


def series_columns() -> list[sa.Column]:
    """The columns a series gains, all nullable or defaulted."""
    return [
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("side_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("pick_rule", sa.String(length=10), nullable=True),
        sa.Column(
            "result_kind", sa.String(length=10), nullable=False, server_default="played"
        ),
        sa.Column("slot1_from_series_id", sa.Integer(), nullable=True),
        sa.Column(
            "slot1_takes_loser", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("slot2_from_series_id", sa.Integer(), nullable=True),
        sa.Column(
            "slot2_takes_loser", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("division_id", sa.Integer(), nullable=True),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if not sqlite:
        # A label is usable only by the transactions that follow the one adding it
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE stageformat ADD VALUE IF NOT EXISTS 'gnl'")
            op.execute("ALTER TYPE entrantkind ADD VALUE IF NOT EXISTS 'team'")
        sa.Enum(*SIGNUP_POLICY, name="signuppolicy").create(bind, checkfirst=True)

    # The event gains a parent, a signup policy and the entrant kind. SQLite
    # adds the self reference inline: a batch rebuild would turn the inline
    # league_id reference into a table-level one and leave the 4a downgrade
    # unable to drop that column.
    if sqlite:
        for column in event_columns()[1:]:
            op.add_column("event", column)
        op.execute(
            "ALTER TABLE event ADD COLUMN parent_id INTEGER "
            "REFERENCES event (id) ON DELETE SET NULL"
        )
    else:
        for column in event_columns():
            op.add_column("event", column)
        op.create_foreign_key(
            op.f("fk_event_parent_id_event"),
            "event",
            "event",
            ["parent_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(op.f("ix_event_parent_id"), "event", ["parent_id"])
    # An event enters what its league enters; a GNL season drafts its teams
    op.execute(
        "UPDATE event SET entrant_kind = (SELECT l.entrant_kind FROM league l "
        "WHERE l.id = event.league_id) WHERE league_id IS NOT NULL"
    )

    # The captains draft the series of a GNL round, which no round robin does
    op.execute(
        "UPDATE event_stage SET format = 'gnl' WHERE event_id IN "
        "(SELECT id FROM event WHERE kind = 'gnl')"
    )
    op.add_column("event_stage", sa.Column("group_size", sa.Integer(), nullable=True))
    op.add_column(
        "event_stage", sa.Column("group_advance", sa.Integer(), nullable=True)
    )
    op.add_column(
        "event_stage",
        sa.Column(
            "auto_advance", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )

    # An entrant is a player or a team. SQLite drops a NOT NULL and takes a
    # check only by rebuilding the table, so the whole change is one batch.
    if sqlite:
        with op.batch_alter_table("event_entrant") as batch:
            for column in entrant_columns():
                batch.add_column(column)
            batch.alter_column("user_id", existing_type=sa.Integer(), nullable=True)
            batch.create_foreign_key(
                op.f("fk_event_entrant_team_id_teams"),
                "teams",
                ["team_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch.create_foreign_key(
                op.f("fk_event_entrant_qualified_from_event_id_event"),
                "event",
                ["qualified_from_event_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_unique_constraint(
                op.f("uq_event_entrant_event_id_team_id"), ["event_id", "team_id"]
            )
            batch.create_check_constraint(
                op.f("ck_event_entrant_one_entrant"), ONE_ENTRANT["sqlite"]
            )
    else:
        for column in entrant_columns():
            op.add_column("event_entrant", column)
        op.alter_column(
            "event_entrant", "user_id", existing_type=sa.Integer(), nullable=True
        )
        op.create_foreign_key(
            op.f("fk_event_entrant_team_id_teams"),
            "event_entrant",
            "teams",
            ["team_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            op.f("fk_event_entrant_qualified_from_event_id_event"),
            "event_entrant",
            "event",
            ["qualified_from_event_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_unique_constraint(
            op.f("uq_event_entrant_event_id_team_id"),
            "event_entrant",
            ["event_id", "team_id"],
        )
        op.create_check_constraint(
            op.f("ck_event_entrant_one_entrant"),
            "event_entrant",
            ONE_ENTRANT["postgresql"],
        )
    op.create_index(op.f("ix_event_entrant_team_id"), "event_entrant", ["team_id"])

    # The series gains the feeder graph and loses the NOT NULL on its sides
    if sqlite:
        with op.batch_alter_table("series") as batch:
            for column in series_columns():
                batch.add_column(column)
            for slot in ("slot1", "slot2"):
                batch.create_foreign_key(
                    op.f(f"fk_series_{slot}_from_series_id_series"),
                    "series",
                    [f"{slot}_from_series_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            batch.create_foreign_key(
                op.f("fk_series_division_id_event_division"),
                "event_division",
                ["division_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.alter_column("player1_id", existing_type=sa.Integer(), nullable=True)
            batch.alter_column("player2_id", existing_type=sa.Integer(), nullable=True)
    else:
        for column in series_columns():
            op.add_column("series", column)
        for slot in ("slot1", "slot2"):
            op.create_foreign_key(
                op.f(f"fk_series_{slot}_from_series_id_series"),
                "series",
                "series",
                [f"{slot}_from_series_id"],
                ["id"],
                ondelete="SET NULL",
            )
        op.create_foreign_key(
            op.f("fk_series_division_id_event_division"),
            "series",
            "event_division",
            ["division_id"],
            ["id"],
            ondelete="SET NULL",
        )
        for side in ("player1_id", "player2_id"):
            op.alter_column("series", side, existing_type=sa.Integer(), nullable=True)

    # A fixture of a divided event is played inside one division
    if sqlite:
        with op.batch_alter_table("matches") as batch:
            batch.add_column(sa.Column("division_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                op.f("fk_matches_division_id_event_division"),
                "event_division",
                ["division_id"],
                ["id"],
                ondelete="SET NULL",
            )
    else:
        op.add_column("matches", sa.Column("division_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            op.f("fk_matches_division_id_event_division"),
            "matches",
            "event_division",
            ["division_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"

    if sqlite:
        with op.batch_alter_table("matches") as batch:
            batch.drop_constraint(
                op.f("fk_matches_division_id_event_division"), type_="foreignkey"
            )
            batch.drop_column("division_id")
    else:
        op.drop_constraint(
            op.f("fk_matches_division_id_event_division"), "matches", type_="foreignkey"
        )
        op.drop_column("matches", "division_id")

    names = [column.name for column in series_columns()]
    if sqlite:
        with op.batch_alter_table("series") as batch:
            batch.alter_column("player1_id", existing_type=sa.Integer(), nullable=False)
            batch.alter_column("player2_id", existing_type=sa.Integer(), nullable=False)
            for name in names:
                batch.drop_column(name)
    else:
        for side in ("player1_id", "player2_id"):
            op.alter_column("series", side, existing_type=sa.Integer(), nullable=False)
        for name in names:
            op.drop_column("series", name)

    op.drop_index(op.f("ix_event_entrant_team_id"), table_name="event_entrant")
    names = [column.name for column in entrant_columns()]
    if sqlite:
        with op.batch_alter_table("event_entrant") as batch:
            batch.drop_constraint(op.f("ck_event_entrant_one_entrant"), type_="check")
            batch.drop_constraint(
                op.f("uq_event_entrant_event_id_team_id"), type_="unique"
            )
            batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
            for name in names:
                batch.drop_column(name)
    else:
        op.drop_constraint(
            op.f("ck_event_entrant_one_entrant"), "event_entrant", type_="check"
        )
        op.drop_constraint(
            op.f("uq_event_entrant_event_id_team_id"), "event_entrant", type_="unique"
        )
        op.alter_column(
            "event_entrant", "user_id", existing_type=sa.Integer(), nullable=False
        )
        for name in names:
            op.drop_column("event_entrant", name)

    # The old code reads no gnl format, so the stages read round robin again
    op.execute("UPDATE event_stage SET format = 'round_robin' WHERE format = 'gnl'")
    for name in ("auto_advance", "group_advance", "group_size"):
        op.drop_column("event_stage", name)

    op.drop_index(op.f("ix_event_parent_id"), table_name="event")
    names = [column.name for column in event_columns()]
    if sqlite:
        for name in names:
            op.drop_column("event", name)
    else:
        op.drop_constraint(
            op.f("fk_event_parent_id_event"), "event", type_="foreignkey"
        )
        for name in names:
            op.drop_column("event", name)

    if not sqlite:
        # Postgres drops no enum label, so gnl and team stay in their types
        sa.Enum(*SIGNUP_POLICY, name="signuppolicy").drop(bind, checkfirst=True)
