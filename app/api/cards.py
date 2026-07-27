import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi import status as http_status

from app.api.dependencies import get_card_processing_service, get_card_repository, get_image_storage
from app.config import settings
from app.db.card_repository import CardRepository
from app.schemas.response import (
    CardListItemResponse,
    CardListResponse,
    CardResponse,
    ReviewResolutionRequest,
)
from app.services.card_processing_service import CardProcessingService
from app.services.image_storage import ImageStorage

router = APIRouter(prefix="/cards", tags=["cards"])


@router.post("", response_model=CardResponse, status_code=http_status.HTTP_201_CREATED)
async def upload_card(
    file: UploadFile = File(...),
    service: CardProcessingService = Depends(get_card_processing_service),
    image_storage: ImageStorage = Depends(get_image_storage),
) -> CardResponse:
    if file.content_type not in settings.allowed_content_types:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "unsupported_format",
                "message": (
                    f"Unsupported content type '{file.content_type}'. "
                    f"Allowed: {settings.allowed_content_types}."
                ),
            },
        )

    raw_bytes = await file.read()

    if len(raw_bytes) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=http_status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "error_code": "file_too_large",
                "message": f"File exceeds the maximum allowed size of {settings.max_upload_size_bytes} bytes.",
            },
        )

    if not raw_bytes:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "invalid_image", "message": "Uploaded file is empty."},
        )

    record = service.process(raw_bytes, image_filename=file.filename, content_type=file.content_type)
    return CardResponse.from_record(record, image_storage)


@router.get("/{card_id}", response_model=CardResponse)
def get_card(
    card_id: uuid.UUID,
    repository: CardRepository = Depends(get_card_repository),
    image_storage: ImageStorage = Depends(get_image_storage),
) -> CardResponse:
    record = repository.get_by_id(card_id)
    if record is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error_code": "record_not_found", "message": f"No record found with id {card_id}."},
        )
    return CardResponse.from_record(record, image_storage)


@router.get("", response_model=CardListResponse)
def list_cards(
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    repository: CardRepository = Depends(get_card_repository),
    image_storage: ImageStorage = Depends(get_image_storage),
) -> CardListResponse:
    records, total = repository.list(status=status, page=page, page_size=page_size)
    return CardListResponse(
        items=[CardListItemResponse.from_record(r, image_storage) for r in records],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch("/{card_id}/review", response_model=CardResponse)
def resolve_review(
    card_id: uuid.UUID,
    payload: ReviewResolutionRequest,
    repository: CardRepository = Depends(get_card_repository),
    image_storage: ImageStorage = Depends(get_image_storage),
) -> CardResponse:
    record = repository.get_by_id(card_id)
    if record is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error_code": "record_not_found", "message": f"No record found with id {card_id}."},
        )

    if record.status != "needs_review":
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "invalid_review_payload",
                "message": "Record is not pending review.",
            },
        )

    resolved_fields = payload.model_dump(exclude_unset=True)
    if not resolved_fields:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "invalid_review_payload",
                "message": "At least one resolved field value must be provided.",
            },
        )

    updated = repository.resolve_review(card_id, resolved_fields)
    return CardResponse.from_record(updated, image_storage)
