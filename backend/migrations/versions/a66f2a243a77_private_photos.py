"""Store private request photos and thumbnails."""

import sqlalchemy as sa
from alembic import op

revision = "a66f2a243a77"
down_revision = "e1a02df312c8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("attachments", sa.Column("work_order_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_attachments_work_order_id", "attachments", "work_orders", ["work_order_id"], ["id"]
    )
    op.add_column("attachments", sa.Column("image_data", sa.LargeBinary()))
    op.add_column("attachments", sa.Column("thumbnail_data", sa.LargeBinary()))


def downgrade():
    op.drop_column("attachments", "thumbnail_data")
    op.drop_column("attachments", "image_data")
    op.drop_constraint("fk_attachments_work_order_id", "attachments", type_="foreignkey")
    op.drop_column("attachments", "work_order_id")
