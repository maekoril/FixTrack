"""Add asset location for the registry."""

import sqlalchemy as sa
from alembic import op

revision = "b80c12d6a221"
down_revision = "a66f2a243a77"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assets", sa.Column("location", sa.String(255), nullable=False, server_default="")
    )


def downgrade():
    op.drop_column("assets", "location")
