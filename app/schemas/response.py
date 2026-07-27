import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.config import settings
from app.models import BusinessCardRecord
from app.services.image_storage import ImageStorage

_FIELD_NAMES = ("name", "position", "company", "email", "phone")


def build_image_url(record: BusinessCardRecord, image_storage: ImageStorage) -> str | None:
    if record.image_storage_key is None:
        return None
    if settings.image_storage_backend == "local":
        return f"/cards/{record.id}/image"
    return image_storage.url(record.image_storage_key)


class FieldResponse(BaseModel):
    value: str | None
    status: str
    ocr_llm_value: str | None = None
    qr_value: str | None = None


class QrInfoResponse(BaseModel):
    detected: bool
    decoded: bool


def _build_fields(record: BusinessCardRecord) -> dict[str, FieldResponse]:
    return {
        field_name: FieldResponse(
            value=getattr(record, f"{field_name}_value"),
            status=getattr(record, f"{field_name}_status"),
            ocr_llm_value=getattr(record, f"{field_name}_ocr_llm_value"),
            qr_value=getattr(record, f"{field_name}_qr_value"),
        )
        for field_name in _FIELD_NAMES
    }


class CardListItemResponse(BaseModel):
    """Slimmer record shape for GET /cards list items -- omits raw_ocr_text, which
    adds unnecessary payload weight when echoed for every row in a paginated list.
    Use CardResponse (via GET /cards/{id}) for the full record including raw OCR text."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    fields: dict[str, FieldResponse]
    optional_fields: dict[str, str]
    qr: QrInfoResponse
    image_url: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: BusinessCardRecord, image_storage: ImageStorage) -> "CardListItemResponse":
        return cls(
            id=record.id,
            status=record.status,
            fields=_build_fields(record),
            optional_fields=record.optional_fields,
            qr=QrInfoResponse(detected=record.qr_detected, decoded=record.qr_decoded),
            image_url=build_image_url(record, image_storage),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class CardResponse(CardListItemResponse):
    raw_ocr_text: str

    @classmethod
    def from_record(cls, record: BusinessCardRecord, image_storage: ImageStorage) -> "CardResponse":
        return cls(
            id=record.id,
            status=record.status,
            fields=_build_fields(record),
            optional_fields=record.optional_fields,
            qr=QrInfoResponse(detected=record.qr_detected, decoded=record.qr_decoded),
            image_url=build_image_url(record, image_storage),
            raw_ocr_text=record.raw_ocr_text,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class CardListResponse(BaseModel):
    items: list[CardListItemResponse]
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
