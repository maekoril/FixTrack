"""Rename employee accounts to branch managers."""

import sqlalchemy as sa
from alembic import op

revision = "91afee1c2012"
down_revision = "0d5b207d02af"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("role", "users", type_="check")
    op.alter_column("users", "role", type_=sa.String(14), existing_type=sa.String(13))
    op.execute("UPDATE users SET role = 'branch_manager' WHERE role = 'employee'")
    op.create_check_constraint(
        "role", "users", "role IN ('branch_manager', 'technician', 'administrator')"
    )


def downgrade():
    op.drop_constraint("role", "users", type_="check")
    op.execute("UPDATE users SET role = 'employee' WHERE role = 'branch_manager'")
    op.alter_column("users", "role", type_=sa.String(13), existing_type=sa.String(14))
    op.create_check_constraint(
        "role", "users", "role IN ('employee', 'technician', 'administrator')"
    )
