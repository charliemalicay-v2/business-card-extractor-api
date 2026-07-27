import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.services.exceptions import (
    ExtractionServiceUnavailableError,
    ImageStorageError,
    InvalidImageError,
    NotABusinessCardError,
    OcrNoTextError,
)

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        # Our route handlers raise HTTPException(detail={"error_code": ..., "message": ...})
        # to produce the same flat error shape as the typed-exception handlers below. FastAPI's
        # default handler would otherwise nest this under {"detail": {...}}.
        content = exc.detail if isinstance(exc.detail, dict) else {"error_code": "error", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)

    @app.exception_handler(InvalidImageError)
    async def handle_invalid_image(request: Request, exc: InvalidImageError) -> JSONResponse:
        logger.warning("Invalid image upload rejected: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error_code": "invalid_image", "message": "Uploaded file is not a valid image."},
        )

    @app.exception_handler(NotABusinessCardError)
    async def handle_not_a_business_card(request: Request, exc: NotABusinessCardError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error_code": "not_a_business_card",
                "message": "Image does not appear to be a business card.",
                "stage": exc.stage,
            },
        )

    @app.exception_handler(OcrNoTextError)
    async def handle_ocr_no_text(request: Request, exc: OcrNoTextError) -> JSONResponse:
        logger.warning("OCR produced no usable text: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"error_code": "ocr_no_text", "message": "No readable text could be extracted from the image."},
        )

    @app.exception_handler(ExtractionServiceUnavailableError)
    async def handle_extraction_unavailable(
        request: Request, exc: ExtractionServiceUnavailableError
    ) -> JSONResponse:
        logger.exception("LLM extraction service unavailable")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error_code": "extraction_service_unavailable",
                "message": "The extraction service is temporarily unavailable. Please try again later.",
            },
        )

    @app.exception_handler(ImageStorageError)
    async def handle_image_storage_error(request: Request, exc: ImageStorageError) -> JSONResponse:
        logger.exception("Image storage operation failed")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error_code": "image_storage_unavailable",
                "message": "The image storage backend is temporarily unavailable. Please try again later.",
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("Database operation failed")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error_code": "persistence_failed", "message": "A database error occurred."},
        )
