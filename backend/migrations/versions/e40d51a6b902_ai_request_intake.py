"""Add private intake snapshots, usage attempts, and intake categories."""

import sqlalchemy as sa
from alembic import op

revision = "e40d51a6b902"
down_revision = "d92b34f81a06"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "request_intakes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("branch_id", sa.Uuid(), sa.ForeignKey("branches.id")),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("service_requests.id"), unique=True),
        sa.Column("original_description", sa.Text(), nullable=False),
        sa.Column("normalized_description", sa.Text(), nullable=False),
        sa.Column("language_detected", sa.String(10), nullable=False),
        sa.Column("ai_category", sa.String(50)),
        sa.Column("ai_subcategory", sa.String(180)),
        sa.Column("ai_priority", sa.String(10)),
        sa.Column("ai_priority_reason", sa.Text()),
        sa.Column("ai_safety_flags", sa.JSON(), nullable=False),
        sa.Column("ai_confidence", sa.Numeric(4, 3)),
        sa.Column("photo_analysis", sa.JSON()),
        sa.Column("final_category", sa.String(50)),
        sa.Column("final_priority", sa.String(10)),
        sa.Column("ai_overridden", sa.Boolean(), nullable=False),
        sa.Column("ai_raw_response", sa.JSON()),
        sa.Column("conversation", sa.JSON(), nullable=False),
        sa.Column("incomplete_info", sa.Boolean(), nullable=False),
        sa.Column("needs_more_info", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_request_intakes_user_id", "request_intakes", ["user_id"])
    op.create_table(
        "intake_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
    )
    op.create_index("ix_intake_attempts_user_id", "intake_attempts", ["user_id"])
    for category_id, name in (
        ("carpentry", "Carpentry"),
        ("civil-structural", "Civil & Structural"),
        ("pest-control", "Pest Control"),
        ("cleaning-sanitation", "Cleaning & Sanitation"),
    ):
        op.execute(
            sa.text(
                "INSERT INTO service_categories (id, name) VALUES (:id, :name) "
                "ON CONFLICT DO NOTHING"
            ).bindparams(id=category_id, name=name)
        )


def downgrade():
    op.drop_table("intake_attempts")
    op.drop_table("request_intakes")
    # Keep categories that existing requests or technician specializations may use.
