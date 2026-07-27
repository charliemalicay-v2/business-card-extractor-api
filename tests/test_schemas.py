import pytest
from pydantic import ValidationError

from app.schemas import (
    ExtractedField,
    FieldStatus,
    LlmExtractionResult,
    QrResult,
    ReconciledCard,
    ReconciledField,
)


def _empty_field() -> ExtractedField:
    return ExtractedField()


def test_extracted_field_defaults_to_none_value_and_mid_confidence():
    field = ExtractedField()

    assert field.value is None
    assert field.confidence == 0.5


def test_llm_extraction_result_defaults_optional_fields_to_empty_dict():
    result = LlmExtractionResult(
        name=_empty_field(),
        position=_empty_field(),
        company=_empty_field(),
        email=_empty_field(),
        phone=_empty_field(),
    )

    assert result.optional_fields == {}


def test_qr_result_requires_detected_and_decoded_flags():
    with pytest.raises(ValidationError):
        QrResult()  # type: ignore[call-arg]

    result = QrResult(detected=False, decoded=False)
    assert result.raw_payload is None
    assert result.parsed_fields is None


def test_field_status_enum_values():
    assert {s.value for s in FieldStatus} == {"confirmed", "conflict", "unverified"}


def test_reconciled_card_rejects_invalid_overall_status():
    field = ReconciledField(value="Jane", status=FieldStatus.CONFIRMED)

    with pytest.raises(ValidationError):
        ReconciledCard(
            name=field,
            position=field,
            company=field,
            email=field,
            phone=field,
            overall_status="bogus",  # type: ignore[arg-type]
        )


def test_reconciled_card_accepts_valid_overall_status():
    field = ReconciledField(value="Jane", status=FieldStatus.CONFIRMED)

    card = ReconciledCard(
        name=field,
        position=field,
        company=field,
        email=field,
        phone=field,
        overall_status="confirmed",
    )

    assert card.overall_status == "confirmed"
    assert card.optional_fields == {}
