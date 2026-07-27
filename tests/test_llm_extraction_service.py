import json

import pytest

from app.services.exceptions import ExtractionServiceUnavailableError
from app.services.llm.extraction_service import LlmExtractionService


class _FakeModel:
    def __init__(self, output: str | None = None, raises: Exception | None = None):
        self._output = output
        self._raises = raises
        self.last_prompt: str | None = None

    def generate_json(self, prompt: str) -> str:
        self.last_prompt = prompt
        if self._raises:
            raise self._raises
        return self._output


def _full_extraction_json() -> str:
    return json.dumps(
        {
            "name": {"value": "Jane Doe", "confidence": 0.95},
            "position": {"value": "Sales Manager", "confidence": 0.9},
            "company": {"value": "Acme Corp", "confidence": 0.92},
            "email": {"value": "jane@acme.com", "confidence": 0.99},
            "phone": {"value": "+1-555-0100", "confidence": 0.88},
            "optional_fields": {"website": "acme.com"},
        }
    )


def _partial_extraction_json() -> str:
    return json.dumps(
        {
            "name": {"value": "Jane Doe", "confidence": 0.9},
            "position": {"value": None, "confidence": 0.1},
            "company": {"value": None, "confidence": 0.1},
            "email": {"value": "jane@acme.com", "confidence": 0.95},
            "phone": {"value": None, "confidence": 0.1},
            "optional_fields": {},
        }
    )


def test_extract_returns_full_result_when_all_fields_identified():
    service = LlmExtractionService(_FakeModel(output=_full_extraction_json()))

    result = service.extract("Jane Doe\nSales Manager\nAcme Corp\njane@acme.com\n+1-555-0100")

    assert result.name.value == "Jane Doe"
    assert result.email.value == "jane@acme.com"
    assert result.optional_fields == {"website": "acme.com"}


def test_extract_returns_null_values_for_unidentified_fields_without_raising():
    service = LlmExtractionService(_FakeModel(output=_partial_extraction_json()))

    result = service.extract("Jane Doe\njane@acme.com")

    assert result.name.value == "Jane Doe"
    assert result.position.value is None
    assert result.company.value is None
    assert result.phone.value is None


def test_extract_raises_extraction_service_unavailable_when_model_inference_fails():
    service = LlmExtractionService(_FakeModel(raises=RuntimeError("model crashed")))

    with pytest.raises(ExtractionServiceUnavailableError):
        service.extract("some ocr text")


def test_extract_raises_extraction_service_unavailable_on_malformed_json():
    service = LlmExtractionService(_FakeModel(output="not valid json"))

    with pytest.raises(ExtractionServiceUnavailableError):
        service.extract("some ocr text")


def test_extract_includes_ocr_text_in_prompt():
    model = _FakeModel(output=_full_extraction_json())
    service = LlmExtractionService(model)

    service.extract("Jane Doe\njane@acme.com")

    assert "Jane Doe" in model.last_prompt
    assert "jane@acme.com" in model.last_prompt
