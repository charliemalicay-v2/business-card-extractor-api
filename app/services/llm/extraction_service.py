from pydantic import ValidationError

from app.schemas import LlmExtractionResult
from app.services.exceptions import ExtractionServiceUnavailableError
from app.services.llm.model import LlmModel

_PROMPT_TEMPLATE = """You are extracting structured contact information from OCR text taken from a photo of a business card.

Return ONLY a JSON object with the fields: name, position, company, email, phone (each an object with "value" and "confidence" between 0 and 1), and "optional_fields" (an object mapping any other details found, e.g. website, address, fax, to their text values).

If a field cannot be confidently identified from the text, set its "value" to null and use a low "confidence".

OCR text:
{ocr_text}

JSON:
"""


class LlmExtractionService:
    def __init__(self, model: LlmModel):
        self._model = model

    def extract(self, ocr_text: str) -> LlmExtractionResult:
        prompt = _PROMPT_TEMPLATE.format(ocr_text=ocr_text)

        try:
            raw_output = self._model.generate_json(prompt)
        except ExtractionServiceUnavailableError:
            raise
        except Exception as exc:
            raise ExtractionServiceUnavailableError(f"Local LLM inference failed: {exc}") from exc

        try:
            return LlmExtractionResult.model_validate_json(raw_output)
        except ValidationError as exc:
            raise ExtractionServiceUnavailableError(
                f"Local LLM returned output that did not match the expected schema: {exc}"
            ) from exc
