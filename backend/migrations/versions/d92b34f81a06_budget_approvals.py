"""Preserve approved budgets and completion overrun explanations."""

import sqlalchemy as sa
from alembic import op

revision = "d92b34f81a06"
down_revision = "ca86e53b12af"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("work_orders", sa.Column("approved_price", sa.JSON()))
    op.add_column("work_orders", sa.Column("overrun_reason", sa.Text()))


def downgrade():
    op.drop_column("work_orders", "overrun_reason")
    op.drop_column("work_orders", "approved_price")
