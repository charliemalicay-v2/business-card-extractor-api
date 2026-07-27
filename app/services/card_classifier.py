import re

import cv2
import numpy as np

from app.schemas import ClassificationResult
from app.services.exceptions import OcrNoTextError
from app.services.ocr_service import OcrService

_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_PATTERN = re.compile(r"(\+?\d[\d\-\.\s()]{6,}\d)")

_MIN_ASPECT_RATIO = 1.3
_MAX_ASPECT_RATIO = 2.4
_MIN_AREA_RATIO = 0.2


class CardClassifier:
    def check_shape(self, image: np.ndarray) -> bool:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        edges = cv2.Canny(gray, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return False

        image_area = gray.shape[0] * gray.shape[1]
        largest = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(largest)

        if h == 0 or w == 0:
            return False

        area_ratio = (w * h) / image_area
        aspect_ratio = max(w, h) / min(w, h)

        return area_ratio >= _MIN_AREA_RATIO and _MIN_ASPECT_RATIO <= aspect_ratio <= _MAX_ASPECT_RATIO

    def check_text_patterns(self, ocr_text: str) -> bool:
        return bool(_EMAIL_PATTERN.search(ocr_text) or _PHONE_PATTERN.search(ocr_text))

    def classify(self, image: np.ndarray, ocr_service: OcrService) -> ClassificationResult:
        if not self.check_shape(image):
            return ClassificationResult(is_card=False, failed_stage="shape", reason_code="not_a_business_card")

        try:
            ocr_text = ocr_service.extract_text(image)
        except OcrNoTextError:
            return ClassificationResult(is_card=False, failed_stage="text_pattern", reason_code="not_a_business_card")

        if not self.check_text_patterns(ocr_text):
            return ClassificationResult(
                is_card=False, failed_stage="text_pattern", reason_code="not_a_business_card", ocr_text=ocr_text
            )

        return ClassificationResult(is_card=True, ocr_text=ocr_text)
