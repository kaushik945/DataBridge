"""Immutable validation, approval, and agent snapshots.

Revision ID: 002
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "002"
down_revision = "001"


def upgrade():
    # The initial migration is frozen to the tables present at revision 001.
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "upload_id", sa.String(), sa.ForeignKey("uploads.id"), nullable=False
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("artifacts")
