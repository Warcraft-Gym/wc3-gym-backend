"""Add the grand final head start: the games the upper-bracket winner opens a
double elimination grand final with, on a stage whose modifier is lead.

The column is nullable and every existing stage keeps none, so the code before
this one and the code after it both read the table during the deploy.

Revision ID: c8f3a6d1e925
Revises: b4e7a2c9d5f1
Create Date: 2026-10-25 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8f3a6d1e925"
down_revision: str | Sequence[str] | None = "b4e7a2c9d5f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event_stage", sa.Column("grand_final_lead", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("event_stage", "grand_final_lead")
