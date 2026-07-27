import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

FIELD_STATUS_VALUES = ("confirmed", "conflict", "unverified")
RECORD_STATUS_VALUES = ("confirmed", "needs_review")

_FIELD_PREFIXES = ("name", "position", "company", "email", "phone")


class BusinessCardRecord(Base):
    __tablename__ = "business_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String, nullable=False)

    name_value: Mapped[str | None] = mapped_column(String, nullable=True)
    name_status: Mapped[str] = mapped_column(String, nullable=False)
    name_ocr_llm_value: Mapped[str | None] = mapped_column(String, nullable=True)
    name_qr_value: Mapped[str | None] = mapped_column(String, nullable=True)

    position_value: Mapped[str | None] = mapped_column(String, nullable=True)
    position_status: Mapped[str] = mapped_column(String, nullable=False)
    position_ocr_llm_value: Mapped[str | None] = mapped_column(String, nullable=True)
    position_qr_value: Mapped[str | None] = mapped_column(String, nullable=True)

    company_value: Mapped[str | None] = mapped_column(String, nullable=True)
    company_status: Mapped[str] = mapped_column(String, nullable=False)
    company_ocr_llm_value: Mapped[str | None] = mapped_column(String, nullable=True)
    company_qr_value: Mapped[str | None] = mapped_column(String, nullable=True)

    email_value: Mapped[str | None] = mapped_column(String, nullable=True)
    email_status: Mapped[str] = mapped_column(String, nullable=False)
    email_ocr_llm_value: Mapped[str | None] = mapped_column(String, nullable=True)
    email_qr_value: Mapped[str | None] = mapped_column(String, nullable=True)

    phone_value: Mapped[str | None] = mapped_column(String, nullable=True)
    phone_status: Mapped[str] = mapped_column(String, nullable=False)
    phone_ocr_llm_value: Mapped[str | None] = mapped_column(String, nullable=True)
    phone_qr_value: Mapped[str | None] = mapped_column(String, nullable=True)

    optional_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    raw_ocr_text: Mapped[str] = mapped_column(Text, nullable=False)

    qr_detected: Mapped[bool] = mapped_column(nullable=False, default=False)
    qr_decoded: Mapped[bool] = mapped_column(nullable=False, default=False)
    qr_raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    image_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    image_storage_key: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(f"status IN {RECORD_STATUS_VALUES}", name="ck_business_cards_status"),
        *(
            CheckConstraint(f"{prefix}_status IN {FIELD_STATUS_VALUES}", name=f"ck_business_cards_{prefix}_status")
            for prefix in _FIELD_PREFIXES
        ),
    )
