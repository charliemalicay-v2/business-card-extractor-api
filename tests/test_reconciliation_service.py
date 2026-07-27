import pytest

from app.schemas import CardFields, ExtractedField, FieldStatus, LlmExtractionResult, QrResult
from app.services.reconciliation_service import ReconciliationService


def _llm_result(**field_values: str | None) -> LlmExtractionResult:
    defaults = {"name": None, "position": None, "company": None, "email": None, "phone": None}
    defaults.update(field_values)
    return LlmExtractionResult(
        name=ExtractedField(value=defaults["name"]),
        position=ExtractedField(value=defaults["position"]),
        company=ExtractedField(value=defaults["company"]),
        email=ExtractedField(value=defaults["email"]),
        phone=ExtractedField(value=defaults["phone"]),
    )


def _qr_result(parsed_fields: CardFields | None) -> QrResult:
    if parsed_fields is None:
        return QrResult(detected=False, decoded=False)
    return QrResult(detected=True, decoded=True, raw_payload="raw", parsed_fields=parsed_fields)


@pytest.fixture
def service() -> ReconciliationService:
    return ReconciliationService()


class TestFieldReconciliation:
    @pytest.mark.parametrize(
        "ocr_llm_value,qr_value,expected_status,expected_value",
        [
            ("Jane Doe", "Jane Doe", FieldStatus.CONFIRMED, "Jane Doe"),
            ("Jane Doe", "  jane   doe ", FieldStatus.CONFIRMED, "Jane Doe"),
            ("JANE DOE", "jane doe", FieldStatus.CONFIRMED, "JANE DOE"),
            ("Jane Doe", "John Smith", FieldStatus.CONFLICT, None),
            ("Acme Corp", None, FieldStatus.UNVERIFIED, "Acme Corp"),
        ],
        ids=["exact-match", "whitespace-only-diff", "case-only-diff", "mismatch", "missing-qr-value"],
    )
    def test_name_field_reconciliation(
        self, service, ocr_llm_value, qr_value, expected_status, expected_value
    ):
        llm_result = _llm_result(name=ocr_llm_value)
        qr_result = _qr_result(CardFields(name=qr_value) if qr_value is not None else CardFields())

        result = service.reconcile(llm_result, qr_result)

        assert result.name.status == expected_status
        assert result.name.value == expected_value
        assert result.name.ocr_llm_value == ocr_llm_value
        assert result.name.qr_value == qr_value


def test_field_reconciliation_falls_back_to_qr_value_when_ocr_llm_value_missing(service):
    """Only one source available (QR) should be unverified, not treated as a conflict
    against a missing OCR/LLM value."""
    llm_result = _llm_result(name=None)
    qr_result = _qr_result(CardFields(name="Jane Doe"))

    result = service.reconcile(llm_result, qr_result)

    assert result.name.status == FieldStatus.UNVERIFIED
    assert result.name.value == "Jane Doe"


def test_reconcile_marks_all_fields_unverified_when_qr_not_decoded(service):
    llm_result = _llm_result(name="Jane Doe", email="jane@acme.com")
    qr_result = QrResult(detected=False, decoded=False)

    result = service.reconcile(llm_result, qr_result)

    assert result.name.status == FieldStatus.UNVERIFIED
    assert result.email.status == FieldStatus.UNVERIFIED
    assert result.overall_status == "confirmed"


def test_reconcile_sets_overall_status_needs_review_on_any_conflict(service):
    llm_result = _llm_result(name="Jane Doe", company="Acme Corp")
    qr_result = _qr_result(CardFields(name="Jane Doe", company="Acme Corporation"))

    result = service.reconcile(llm_result, qr_result)

    assert result.name.status == FieldStatus.CONFIRMED
    assert result.company.status == FieldStatus.CONFLICT
    assert result.overall_status == "needs_review"


def test_reconcile_sets_overall_status_confirmed_when_no_conflicts(service):
    llm_result = _llm_result(name="Jane Doe", email="jane@acme.com")
    qr_result = _qr_result(CardFields(name="Jane Doe"))

    result = service.reconcile(llm_result, qr_result)

    assert result.overall_status == "confirmed"


def test_reconcile_passes_through_optional_fields_from_llm_and_qr(service):
    llm_result = _llm_result(name="Jane Doe")
    llm_result.optional_fields = {"website": "acme.com"}
    qr_result = _qr_result(CardFields(name="Jane Doe", optional_fields={"fax": "555-9999"}))

    result = service.reconcile(llm_result, qr_result)

    assert result.optional_fields == {"website": "acme.com", "fax": "555-9999"}


def test_reconcile_llm_optional_fields_take_precedence_on_key_collision(service):
    llm_result = _llm_result(name="Jane Doe")
    llm_result.optional_fields = {"website": "acme.com"}
    qr_result = _qr_result(CardFields(name="Jane Doe", optional_fields={"website": "acme.io"}))

    result = service.reconcile(llm_result, qr_result)

    assert result.optional_fields == {"website": "acme.com"}
