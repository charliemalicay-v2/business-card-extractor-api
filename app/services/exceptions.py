class InvalidImageError(Exception):
    """Raised when uploaded bytes cannot be decoded as an image."""


class NotABusinessCardError(Exception):
    """Raised when an image fails business-card classification."""

    def __init__(self, stage: str):
        self.stage = stage
        super().__init__(f"Image failed business card validation at stage: {stage}")


class OcrNoTextError(Exception):
    """Raised when OCR produces no usable text from an image."""


class ExtractionServiceUnavailableError(Exception):
    """Raised when the local LLM extraction backend fails to load or run."""
