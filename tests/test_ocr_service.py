import numpy as np
import pytest

from app.services.exceptions import OcrNoTextError
from app.services.ocr_service import OcrService


def _blank_image() -> np.ndarray:
    return np.full((100, 100), 255, dtype=np.uint8)


def test_extract_text_returns_stripped_text(monkeypatch):
    monkeypatch.setattr(
        "app.services.ocr_service.pytesseract.image_to_string",
        lambda image: "  Jane Doe\nSales Manager\njane@acme.com  ",
    )

    result = OcrService().extract_text(_blank_image())

    assert result == "Jane Doe\nSales Manager\njane@acme.com"


def test_extract_text_raises_when_result_below_minimum_length(monkeypatch):
    monkeypatch.setattr("app.services.ocr_service.pytesseract.image_to_string", lambda image: "  ")

    with pytest.raises(OcrNoTextError):
        OcrService().extract_text(_blank_image())
