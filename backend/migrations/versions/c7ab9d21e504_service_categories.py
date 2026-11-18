"""Add shared service categories."""

import sqlalchemy as sa
from alembic import op

revision = "c7ab9d21e504"
down_revision = "b80c12d6a221"
branch_labels = None
depends_on = None


def upgrade():
    categories = op.create_table(
        "service_categories",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
    )
    op.bulk_insert(
        categories,
        [
            {"id": "electrical", "name": "Electrical"},
            {"id": "plumbing", "name": "Plumbing"},
            {"id": "air-conditioning-ventilation", "name": "Air Conditioning & Ventilation"},
            {"id": "it-network", "name": "IT & Network"},
            {"id": "equipment-repair", "name": "Equipment Repair"},
            {"id": "building-facilities", "name": "Building & Facilities"},
            {"id": "other", "name": "Other"},
        ],
    )
    op.add_column("service_requests", sa.Column("category_id", sa.String(50)))
    op.create_foreign_key(
        "fk_service_requests_category_id_service_categories",
        "service_requests",
        "service_categories",
        ["category_id"],
        ["id"],
    )
    op.create_index("ix_service_requests_category_id", "service_requests", ["category_id"])


def downgrade():
    op.drop_index("ix_service_requests_category_id", table_name="service_requests")
    op.drop_constraint(
        "fk_service_requests_category_id_service_categories",
        "service_requests",
        type_="foreignkey",
    )
    op.drop_column("service_requests", "category_id")
    op.drop_table("service_categories")
