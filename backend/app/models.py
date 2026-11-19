import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Role(str, enum.Enum):
    branch_manager = "branch_manager"
    technician = "technician"
    administrator = "administrator"


class RequestStatus(str, enum.Enum):
    submitted = "submitted"
    in_progress = "in_progress"
    awaiting_verification = "awaiting_verification"
    closed = "closed"


class Priority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class Difficulty(str, enum.Enum):
    easy = "easy"
    moderate = "moderate"
    hard = "hard"


class WorkStatus(str, enum.Enum):
    assigned = "assigned"
    in_progress = "in_progress"
    completed = "completed"


class Record:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Branch(Record, Base):
    __tablename__ = "branches"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    location: Mapped[str] = mapped_column(String(255))


class User(Record, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, create_constraint=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    specialization: Mapped[str | None] = mapped_column(String(150))


class BranchAccess(Base):
    __tablename__ = "branch_access"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), primary_key=True)


class Asset(Record, Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("id", "branch_id"),)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    asset_tag: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    condition: Mapped[str] = mapped_column(String(80))
    location: Mapped[str] = mapped_column(String(255), default="", server_default="")


class ServiceCategory(Base):
    __tablename__ = "service_categories"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class ServiceRequest(Record, Base):
    __tablename__ = "service_requests"
    __table_args__ = (
        ForeignKeyConstraint(["asset_id", "branch_id"], ["assets.id", "assets.branch_id"]),
        CheckConstraint(
            "duration_override_minutes BETWEEN 1 AND 10080", name="request_duration_minutes_range"
        ),
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    submitted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("service_categories.id"), index=True)
    category: Mapped[ServiceCategory | None] = relationship()
    difficulty: Mapped[Difficulty | None] = mapped_column(
        Enum(Difficulty, native_enum=False, create_constraint=True)
    )
    duration_override_minutes: Mapped[int | None]
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String(255))
    priority: Mapped[Priority | None] = mapped_column(
        Enum(Priority, native_enum=False, create_constraint=True)
    )
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus, native_enum=False, create_constraint=True),
        default=RequestStatus.submitted,
    )
    closed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RequestIntake(Record, Base):
    __tablename__ = "request_intakes"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"))
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_requests.id"), unique=True
    )
    original_description: Mapped[str] = mapped_column(Text)
    normalized_description: Mapped[str] = mapped_column(Text)
    language_detected: Mapped[str] = mapped_column(String(10))
    ai_category: Mapped[str | None] = mapped_column(String(50))
    ai_subcategory: Mapped[str | None] = mapped_column(String(180))
    ai_priority: Mapped[str | None] = mapped_column(String(10))
    ai_priority_reason: Mapped[str | None] = mapped_column(Text)
    ai_safety_flags: Mapped[list] = mapped_column(JSON, default=list)
    ai_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    photo_analysis: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    final_category: Mapped[str | None] = mapped_column(String(50))
    final_priority: Mapped[str | None] = mapped_column(String(10))
    ai_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_raw_response: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    conversation: Mapped[list] = mapped_column(JSON, default=list)
    incomplete_info: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_more_info: Mapped[bool] = mapped_column(Boolean, default=False)


class IntakeAttempt(Record, Base):
    __tablename__ = "intake_attempts"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")


class WorkOrder(Record, Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint("labor_cost >= 0", name="positive_labor_cost"),
        CheckConstraint("materials_cost >= 0", name="positive_materials_cost"),
        CheckConstraint(
            "(scheduled_start IS NULL AND scheduled_end IS NULL) OR "
            "(scheduled_start IS NOT NULL AND scheduled_end IS NOT NULL "
            "AND scheduled_end > scheduled_start)",
            name="valid_work_order_schedule",
        ),
    )
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_requests.id"), index=True)
    technician_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    assigned_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[WorkStatus] = mapped_column(
        Enum(WorkStatus, native_enum=False, create_constraint=True), default=WorkStatus.assigned
    )
    labor_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    materials_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    price_estimate: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    approved_price: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    overrun_reason: Mapped[str | None] = mapped_column(Text)
    lead: Mapped[User] = relationship(foreign_keys=[technician_id])
    assistants: Mapped[list[User]] = relationship(
        secondary="work_order_assistants", order_by=(User.full_name, User.id)
    )


class WorkOrderAssistant(Base):
    __tablename__ = "work_order_assistants"
    work_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_orders.id"), primary_key=True)
    technician_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True, index=True
    )


class MaintenanceLog(Record, Base):
    __tablename__ = "maintenance_logs"
    work_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_orders.id"), index=True)
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(180))
    notes: Mapped[str] = mapped_column(Text)


class RequestEvent(Record, Base):
    __tablename__ = "request_events"
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_requests.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class NotificationRead(Base):
    __tablename__ = "notification_reads"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("request_events.id"), primary_key=True)


class Attachment(Record, Base):
    __tablename__ = "attachments"
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_requests.id"), index=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_orders.id"))
    image_data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    thumbnail_data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
