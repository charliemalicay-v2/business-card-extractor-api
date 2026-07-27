import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import BusinessCardRecord

_FIELD_NAMES = ("name", "position", "company", "email", "phone")


class FieldResponse(BaseModel):
    value: str | None
    status: str
    ocr_llm_value: str | None = None
    qr_value: str | None = None


class QrInfoResponse(BaseModel):
    detected: bool
    decoded: bool


class CardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    fields: dict[str, FieldResponse]
    optional_fields: dict[str, str]
    qr: QrInfoResponse
    raw_ocr_text: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: BusinessCardRecord) -> "CardResponse":
        fields = {
            field_name: FieldResponse(
                value=getattr(record, f"{field_name}_value"),
                status=getattr(record, f"{field_name}_status"),
                ocr_llm_value=getattr(record, f"{field_name}_ocr_llm_value"),
                qr_value=getattr(record, f"{field_name}_qr_value"),
            )
            for field_name in _FIELD_NAMES
        }
        return cls(
            id=record.id,
            status=record.status,
            fields=fields,
            optional_fields=record.optional_fields,
            qr=QrInfoResponse(detected=record.qr_detected, decoded=record.qr_decoded),
            raw_ocr_text=record.raw_ocr_text,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class CardListResponse(BaseModel):
    items: list[CardResponse]
    total: int
    page: int
    page_size: int


class ReviewResolutionRequest(BaseModel):
    name: str | None = None
    position: str | None = None
    company: str | None = None
    email: str | None = None
    phone: str | None = None


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    stage: str | None = None
