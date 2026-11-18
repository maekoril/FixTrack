"""Add request difficulty and editable service duration estimates."""

import sqlalchemy as sa
from alembic import op

revision = "f58c09b3d426"
down_revision = "c7ab9d21e504"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "service_requests",
        sa.Column("difficulty", sa.Enum("easy", "moderate", "hard", native_enum=False)),
    )
    op.create_check_constraint(
        "difficulty", "service_requests", "difficulty IN ('easy', 'moderate', 'hard')"
    )
    op.add_column("service_requests", sa.Column("duration_override_minutes", sa.Integer()))
    op.create_check_constraint(
        "request_duration_minutes_range",
        "service_requests",
        "duration_override_minutes BETWEEN 1 AND 10080",
    )


def downgrade():
    op.drop_constraint("request_duration_minutes_range", "service_requests", type_="check")
    op.drop_column("service_requests", "duration_override_minutes")
    op.drop_constraint("difficulty", "service_requests", type_="check")
    op.drop_column("service_requests", "difficulty")
