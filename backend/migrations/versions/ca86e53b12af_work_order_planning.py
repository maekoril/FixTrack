"""Add work order teams, schedules, and price estimates."""

import sqlalchemy as sa
from alembic import op

revision = "ca86e53b12af"
down_revision = "f58c09b3d426"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "work_order_assistants",
        sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("work_orders.id"), primary_key=True),
        sa.Column("technician_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
    )
    op.create_index(
        "ix_work_order_assistants_technician_id", "work_order_assistants", ["technician_id"]
    )
    op.add_column("work_orders", sa.Column("scheduled_start", sa.DateTime(timezone=True)))
    op.add_column("work_orders", sa.Column("scheduled_end", sa.DateTime(timezone=True)))
    op.add_column("work_orders", sa.Column("price_estimate", sa.JSON()))
    op.create_check_constraint(
        "valid_work_order_schedule",
        "work_orders",
        "(scheduled_start IS NULL AND scheduled_end IS NULL) OR "
        "(scheduled_start IS NOT NULL AND scheduled_end IS NOT NULL "
        "AND scheduled_end > scheduled_start)",
    )


def downgrade():
    op.drop_constraint("valid_work_order_schedule", "work_orders", type_="check")
    op.drop_column("work_orders", "price_estimate")
    op.drop_column("work_orders", "scheduled_end")
    op.drop_column("work_orders", "scheduled_start")
    op.drop_table("work_order_assistants")
