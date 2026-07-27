from enum import Enum
from typing import Literal

from pydantic import BaseModel


class FieldStatus(str, Enum):
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"
    UNVERIFIED = "unverified"


class CardFields(BaseModel):
    """A best-effort set of contact fields, as parsed from a single source (e.g. a QR payload)."""

    name: str | None = None
    position: str | None = None
    company: str | None = None
    email: str | None = None
    phone: str | None = None
    optional_fields: dict[str, str] = {}


class ClassificationResult(BaseModel):
    is_card: bool
    failed_stage: Literal["shape", "text_pattern"] | None = None
    reason_code: str | None = None
    ocr_text: str | None = None


class QrResult(BaseModel):
    detected: bool
    decoded: bool
    raw_payload: str | None = None
    parsed_fields: CardFields | None = None


class ExtractedField(BaseModel):
    value: str | None = None
    confidence: float = 0.5


class LlmExtractionResult(BaseModel):
    name: ExtractedField
    position: ExtractedField
    company: ExtractedField
    email: ExtractedField
    phone: ExtractedField
    optional_fields: dict[str, str] = {}


class ReconciledField(BaseModel):
    value: str | None
    status: FieldStatus
    ocr_llm_value: str | None = None
    qr_value: str | None = None


class ReconciledCard(BaseModel):
    name: ReconciledField
    position: ReconciledField
    company: ReconciledField
    email: ReconciledField
    phone: ReconciledField
    optional_fields: dict[str, str] = {}
    overall_status: Literal["confirmed", "needs_review"]
