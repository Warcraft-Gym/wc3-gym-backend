"""Add the natural keys the importers match on

Both importers find an existing row by a natural key: a player by battle tag,
a bettor by Discord tag, a season and a fantasy team by name, a map by short
name, a fantasy team by captain, a team series by the two teams and the
playday, a player series by the two players. Nothing but these indexes stops
a second row from holding the same key, and a second row makes the importer
pick one of them at random.

The folded indexes read lower(trim(...)) because a battle tag is not case
sensitive to Blizzard and neither importer is case sensitive to a name.
A blank Discord tag means unknown, so the index skips it.

The teams key is the Discord role, not the short name: a role belongs to one
club, which is what makes a club the same club across seasons, while a short
name is a label two clubs may reuse.

This revision adds no delete. A key that already repeats means two rows that
other tables point at, and choosing which to keep is not a migration's call:
the index fails to build and names the table.

Revision ID: f7a2c95e3b18
Revises: d4f8b3e21a97
Create Date: 2026-08-27 22:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a2c95e3b18"
down_revision: str | Sequence[str] | None = "d4f8b3e21a97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index, table, expressions, where)
KEYS: tuple[tuple[str, str, str, str | None], ...] = (
    ("uq_users_battle_tag", "users", 'lower(trim("battleTag"))', None),
    (
        "uq_users_discord_tag",
        "users",
        'lower(trim("discordTag"))',
        "trim(\"discordTag\") <> ''",
    ),
    ("uq_seasons_name", "seasons", "lower(trim(name))", None),
    ("uq_teams_discord_role", "teams", "discord_role", None),
    ("uq_maps_shortname", "maps", "lower(trim(shortname))", None),
    (
        "uq_fantasy_teams_season_id_name",
        "fantasy_teams",
        "season_id, lower(trim(name))",
        None,
    ),
    (
        "uq_fantasy_teams_season_id_captain_id",
        "fantasy_teams",
        "season_id, captain_id",
        None,
    ),
    (
        "uq_matches_season_id_team1_id_team2_id_playday",
        "matches",
        "season_id, team1_id, team2_id, playday",
        None,
    ),
    (
        "uq_series_match_id_player1_id_player2_id",
        "series",
        "match_id, player1_id, player2_id",
        None,
    ),
)


def upgrade() -> None:
    for name, table, expressions, where in KEYS:
        clause = f" WHERE {where}" if where else ""
        op.execute(f"CREATE UNIQUE INDEX {name} ON {table} ({expressions}){clause}")


def downgrade() -> None:
    for name, table, _, _ in reversed(KEYS):
        op.drop_index(name, table_name=table)
