import cv2
import numpy as np
import pytest

from app.services.exceptions import InvalidImageError
from app.services.image_preprocessor import ImagePreprocessor


def _valid_image_bytes() -> bytes:
    image = np.full((200, 350, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (10, 10), (340, 190), (0, 0, 0), 2)
    cv2.putText(image, "Jane Doe", (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    success, buffer = cv2.imencode(".png", image)
    assert success
    return buffer.tobytes()


def test_load_decodes_valid_image_bytes():
    preprocessor = ImagePreprocessor()

    image = preprocessor.load(_valid_image_bytes())

    assert image is not None
    assert image.shape[0] > 0 and image.shape[1] > 0


def test_load_raises_on_empty_bytes():
    preprocessor = ImagePreprocessor()

    with pytest.raises(InvalidImageError):
        preprocessor.load(b"")


def test_load_raises_on_corrupted_bytes():
    preprocessor = ImagePreprocessor()

    with pytest.raises(InvalidImageError):
        preprocessor.load(b"this is not a valid image file")


def test_preprocess_returns_single_channel_image_of_same_dimensions():
    preprocessor = ImagePreprocessor()
    image = preprocessor.load(_valid_image_bytes())

    processed = preprocessor.preprocess(image)

    assert processed.ndim == 2
    assert processed.shape[:2] == image.shape[:2]
