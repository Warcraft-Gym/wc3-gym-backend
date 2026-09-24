"""Add the user battle tag table

A person holds many battle tags and one of them is active. Every users row
with a real tag gets one active row, and users.battleTag stays as a copy of
it. The three identity columns of users turn nullable, and the history
import's gnl- stand-in Discord ids are cleared to null. A signup gains the
tag it was played under, and a ladder game the tag it was fetched under.

Every change is additive or relaxes a NOT NULL, so the code of the previous
deploy keeps running while the build migrates.

Revision ID: e07324d2b4f9
Revises: 1e8e59906cec
Create Date: 2026-09-24 12:00:00.000000

"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e07324d2b4f9"
down_revision: str | Sequence[str] | None = "1e8e59906cec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The expression keys of users, as f7a2c95e3b18 and c5d9e2f47a81 built them
USER_KEYS = (
    'CREATE UNIQUE INDEX uq_users_battle_tag ON users (lower(trim("battleTag")))',
    (
        'CREATE UNIQUE INDEX uq_users_discord_tag ON users (lower(trim("discordTag")))'
        " WHERE trim(\"discordTag\") <> ''"
    ),
    (
        'CREATE UNIQUE INDEX uq_users_discord_id ON users (trim("discordId"))'
        " WHERE trim(\"discordId\") <> ''"
    ),
)
IDENTITY_COLUMNS = ("battleTag", "discordTag", "discordId")
LADDER = "w3c_ladder_matches"
LADDER_FK = "fk_w3c_ladder_matches_battle_tag_id_user_battle_tag"

# Real = Name#digits; #GNLnn, Fantasy_User# and Review# are importer stand-ins
REAL_TAG = re.compile(r"[^#\s]+#\d+")
STAND_IN_PREFIXES = ("fantasy_user#", "review#")
# The history import's stand-in Discord id, not a login
STAND_IN_ID = "gnl-%"

users = sa.table(
    "users",
    sa.column("id", sa.Integer()),
    sa.column("battleTag", sa.String()),
    sa.column("discordTag", sa.String()),
    sa.column("discordId", sa.String()),
)
tags = sa.table(
    "user_battle_tag",
    sa.column("id", sa.Integer()),
    sa.column("user_id", sa.Integer()),
    sa.column("tag", sa.String()),
    sa.column("source", sa.String()),
    sa.column("is_active", sa.Boolean()),
    sa.column("first_seen", sa.DateTime(timezone=True)),
    sa.column("last_seen", sa.DateTime(timezone=True)),
)
ladder = sa.table(LADDER, sa.column("user_id"), sa.column("battle_tag_id"))


def is_real_tag(tag: str | None) -> bool:
    text = (tag or "").strip()
    return bool(REAL_TAG.fullmatch(text)) and not text.lower().startswith(
        STAND_IN_PREFIXES
    )


def has_login(discord_id: str | None) -> bool:
    text = (discord_id or "").strip()
    return bool(text) and not text.startswith("gnl-")


def _identity_nullable(nullable: bool) -> None:
    # SQLite rewrites the table to change a NOT NULL and drops the expression
    # keys on the way, so the three keys go back by hand
    with op.batch_alter_table("users") as batch:
        for name in IDENTITY_COLUMNS:
            batch.alter_column(
                name,
                existing_type=sqlmodel.sql.sqltypes.AutoString(length=50),
                nullable=nullable,
            )
    if op.get_bind().dialect.name == "sqlite":
        for key in USER_KEYS:
            op.execute(key)


def upgrade() -> None:
    op.create_table(
        "user_battle_tag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tag", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column(
            "bnet_account_id",
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=True,
        ),
        sa.Column(
            "source", sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_battle_tag_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_battle_tag")),
    )
    op.create_index(op.f("ix_user_battle_tag_user_id"), "user_battle_tag", ["user_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_user_battle_tag_tag ON user_battle_tag (lower(trim(tag)))"
    )
    op.create_index(
        "uq_user_battle_tag_active_user",
        "user_battle_tag",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("is_active"),
        postgresql_where=sa.text("is_active"),
    )

    _identity_nullable(True)
    op.add_column(
        "user_season_signup",
        sa.Column(
            "played_as", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True
        ),
    )
    with op.batch_alter_table(LADDER) as batch:
        batch.add_column(sa.Column("battle_tag_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f(LADDER_FK),
            "user_battle_tag",
            ["battle_tag_id"],
            ["id"],
            ondelete="SET NULL",
        )

    bind = op.get_bind()
    # users has no creation time, so a backfilled tag is first seen now
    now = datetime.now(UTC)
    rows = [
        {
            "user_id": row.id,
            "tag": row.battleTag.strip(),
            "source": "signup" if has_login(row.discordId) else "sheet",
            "is_active": True,
            "first_seen": now,
            "last_seen": now,
        }
        for row in bind.execute(
            sa.select(users.c.id, users.c.battleTag, users.c.discordId)
        )
        if is_real_tag(row.battleTag)
    ]
    if rows:
        bind.execute(tags.insert(), rows)

    active = (
        sa.select(tags.c.id)
        .where(tags.c.user_id == ladder.c.user_id, tags.c.is_active)
        .scalar_subquery()
    )
    bind.execute(ladder.update().values(battle_tag_id=active))

    # A stand-in id carries a stand-in Discord tag when the sheet had no free handle
    stand_in = users.c.discordId.like(STAND_IN_ID)
    bind.execute(
        users.update()
        .where(
            stand_in,
            sa.or_(
                users.c.discordTag.like("%#GNL%"),
                sa.func.lower(sa.func.trim(users.c.discordTag))
                == sa.func.lower(sa.func.trim(users.c.battleTag)),
            ),
        )
        .values(discordTag=None)
    )
    bind.execute(users.update().where(stand_in).values(discordId=None))


def downgrade() -> None:
    # The cleared gnl- stand-ins are not restored; a null Discord tag or id comes back blank.
    # ponytail: a null battleTag refuses the downgrade; this revision writes none.
    bind = op.get_bind()
    for name in ("discordTag", "discordId"):
        column = users.c[name]
        bind.execute(users.update().where(column.is_(None)).values({name: ""}))

    with op.batch_alter_table(LADDER) as batch:
        batch.drop_constraint(op.f(LADDER_FK), type_="foreignkey")
        batch.drop_column("battle_tag_id")
    op.drop_column("user_season_signup", "played_as")
    _identity_nullable(False)
    op.drop_table("user_battle_tag")
