import numpy as np
import pytesseract

from app.config import settings
from app.services.exceptions import OcrNoTextError


class OcrService:
    def extract_text(self, image: np.ndarray) -> str:
        text = pytesseract.image_to_string(image).strip()

        if len(text) < settings.ocr_min_text_length:
            raise OcrNoTextError("OCR produced no usable text from the image.")

        return text
