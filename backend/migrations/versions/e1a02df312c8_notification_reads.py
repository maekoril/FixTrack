"""Persist per-user notification read state."""

import sqlalchemy as sa
from alembic import op

revision = "e1a02df312c8"
down_revision = "91afee1c2012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_reads",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("request_events.id"), primary_key=True),
    )


def downgrade():
    op.drop_table("notification_reads")
