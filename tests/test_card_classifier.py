import cv2
import numpy as np
import pytest

from app.services.card_classifier import CardClassifier
from app.services.exceptions import OcrNoTextError


class _StubOcrService:
    def __init__(self, text: str | None = None, raises: bool = False):
        self._text = text
        self._raises = raises

    def extract_text(self, image: np.ndarray) -> str:
        if self._raises:
            raise OcrNoTextError("no text")
        return self._text


def _card_shaped_image() -> np.ndarray:
    """A wide rectangle filling most of the frame, matching business-card aspect ratio (~1.75)."""
    image = np.full((200, 350, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (5, 5), (345, 195), (0, 0, 0), 3)
    return image


def _non_card_shaped_image() -> np.ndarray:
    """A small circle occupying a tiny fraction of the frame -> fails the area-ratio check."""
    image = np.full((400, 400, 3), 255, dtype=np.uint8)
    cv2.circle(image, (200, 200), 15, (0, 0, 0), 2)
    return image


def _fragmented_card_outline_image() -> np.ndarray:
    """Four disjoint corner marks tracing a card-shaped rectangle, with no single contour
    spanning the outline. Each mark alone fails the area/aspect checks; the union of all
    of them does not."""
    image = np.full((200, 350, 3), 255, dtype=np.uint8)
    for x, y in ((5, 5), (335, 5), (5, 185), (335, 185)):
        cv2.rectangle(image, (x, y), (x + 10, y + 10), (0, 0, 0), -1)
    return image


def _blank_image() -> np.ndarray:
    """A featureless image with no edges, so Canny detects zero contours."""
    return np.full((200, 350, 3), 255, dtype=np.uint8)


@pytest.fixture
def classifier() -> CardClassifier:
    return CardClassifier()


def test_check_shape_accepts_card_like_rectangle(classifier):
    assert classifier.check_shape(_card_shaped_image()) is True


def test_check_shape_rejects_small_non_rectangular_shape(classifier):
    assert classifier.check_shape(_non_card_shaped_image()) is False


def test_check_shape_accepts_fragmented_card_outline(classifier):
    """Regression test: the largest single contour is a tiny corner mark, but the union of
    all contours traces a card-shaped rectangle, so the shape check should pass."""
    assert classifier.check_shape(_fragmented_card_outline_image()) is True


def test_check_shape_falls_back_to_image_dimensions_when_no_contours(classifier):
    """Regression test: when Canny finds no edges at all, check_shape should fall back to
    the raw image dimensions instead of returning False outright."""
    assert classifier.check_shape(_blank_image()) is True


def test_check_text_patterns_accepts_email(classifier):
    assert classifier.check_text_patterns("Jane Doe\njane@acme.com") is True


def test_check_text_patterns_accepts_phone(classifier):
    assert classifier.check_text_patterns("Jane Doe\n+1 555 123 4567") is True


def test_check_text_patterns_rejects_text_without_contact_info(classifier):
    assert classifier.check_text_patterns("Just some random words on a page") is False


def test_classify_valid_card_returns_is_card_true(classifier):
    ocr_service = _StubOcrService(text="Jane Doe\nSales Manager\njane@acme.com")

    result = classifier.classify(_card_shaped_image(), ocr_service)

    assert result.is_card is True
    assert result.failed_stage is None
    assert result.ocr_text == "Jane Doe\nSales Manager\njane@acme.com"


def test_classify_fails_at_shape_stage_for_non_card_shape(classifier):
    ocr_service = _StubOcrService(text="jane@acme.com")

    result = classifier.classify(_non_card_shaped_image(), ocr_service)

    assert result.is_card is False
    assert result.failed_stage == "shape"


def test_classify_fails_at_text_pattern_stage_when_no_contact_info(classifier):
    ocr_service = _StubOcrService(text="Just some random words on a page")

    result = classifier.classify(_card_shaped_image(), ocr_service)

    assert result.is_card is False
    assert result.failed_stage == "text_pattern"


def test_classify_fails_at_text_pattern_stage_when_ocr_finds_no_text(classifier):
    ocr_service = _StubOcrService(raises=True)

    result = classifier.classify(_card_shaped_image(), ocr_service)

    assert result.is_card is False
    assert result.failed_stage == "text_pattern"
