import json
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi import status as http_status
from fastapi.responses import FileResponse

from app.api.dependencies import get_card_processing_service, get_card_repository, get_image_storage
from app.config import settings
from app.db.card_repository import CardRepository
from app.schemas.response import (
    CardListItemResponse,
    CardListResponse,
    CardResponse,
    CardUpdateRequest,
    ReviewResolutionRequest,
)
from app.services.card_processing_service import CardProcessingService
from app.services.exceptions import ImageStorageError
from app.services.image_storage import ImageStorage, generate_image_storage_key
from app.services.image_storage.local_storage import LocalImageStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cards", tags=["cards"])


async def _read_and_validate_image(file: UploadFile) -> bytes:
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

    return raw_bytes


@router.post("", response_model=CardResponse, status_code=http_status.HTTP_201_CREATED)
async def upload_card(
    file: UploadFile = File(...),
    service: CardProcessingService = Depends(get_card_processing_service),
    image_storage: ImageStorage = Depends(get_image_storage),
) -> CardResponse:
    raw_bytes = await _read_and_validate_image(file)

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


@router.get("/{card_id}/image")
def get_card_image(
    card_id: uuid.UUID,
    repository: CardRepository = Depends(get_card_repository),
    image_storage: ImageStorage = Depends(get_image_storage),
) -> FileResponse:
    record = repository.get_by_id(card_id)
    if record is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error_code": "record_not_found", "message": f"No record found with id {card_id}."},
        )

    image_not_found = HTTPException(
        status_code=http_status.HTTP_404_NOT_FOUND,
        detail={"error_code": "image_not_found", "message": f"No stored image found for record {card_id}."},
    )

    if settings.image_storage_backend != "local" or not isinstance(image_storage, LocalImageStorage):
        raise image_not_found
    if record.image_storage_key is None:
        raise image_not_found

    path = image_storage.path_for(record.image_storage_key)
    if not path.is_file():
        raise image_not_found

    return FileResponse(path)


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


@router.patch("/{card_id}", response_model=CardResponse)
async def update_card(
    card_id: uuid.UUID,
    file: UploadFile | None = File(None),
    name_value: str | None = Form(None),
    position_value: str | None = Form(None),
    company_value: str | None = Form(None),
    email_value: str | None = Form(None),
    phone_value: str | None = Form(None),
    optional_fields: str | None = Form(None),
    repository: CardRepository = Depends(get_card_repository),
    image_storage: ImageStorage = Depends(get_image_storage),
) -> CardResponse:
    record = repository.get_by_id(card_id)
    if record is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error_code": "record_not_found", "message": f"No record found with id {card_id}."},
        )

    parsed_optional_fields = None
    if optional_fields is not None:
        try:
            parsed_optional_fields = json.loads(optional_fields)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "invalid_update_payload",
                    "message": "optional_fields must be valid JSON.",
                },
            ) from exc
        if not isinstance(parsed_optional_fields, dict):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "invalid_update_payload",
                    "message": "optional_fields must be a JSON object.",
                },
            )

    update_payload = CardUpdateRequest(
        name_value=name_value,
        position_value=position_value,
        company_value=company_value,
        email_value=email_value,
        phone_value=phone_value,
        optional_fields=parsed_optional_fields,
    )
    fields = update_payload.model_dump(exclude_none=True)

    if not fields and file is None:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "invalid_update_payload",
                "message": "At least one field value or an image file must be provided.",
            },
        )

    old_image_storage_key = record.image_storage_key
    if file is not None:
        raw_bytes = await _read_and_validate_image(file)
        new_key = generate_image_storage_key(file.filename)
        image_storage.put(new_key, raw_bytes, file.content_type or "application/octet-stream")
        fields["image_storage_key"] = new_key
        fields["image_filename"] = file.filename

    updated = repository.update(card_id, fields)
    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error_code": "record_not_found", "message": f"No record found with id {card_id}."},
        )

    if file is not None and old_image_storage_key is not None:
        image_storage.delete(old_image_storage_key)

    return CardResponse.from_record(updated, image_storage)


@router.delete("/{card_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def delete_card(
    card_id: uuid.UUID,
    repository: CardRepository = Depends(get_card_repository),
    image_storage: ImageStorage = Depends(get_image_storage),
) -> None:
    record = repository.get_by_id(card_id)
    if record is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error_code": "record_not_found", "message": f"No record found with id {card_id}."},
        )

    if record.image_storage_key is not None:
        try:
            image_storage.delete(record.image_storage_key)
        except ImageStorageError:
            logger.exception(
                "Failed to delete stored image for record %s during delete; proceeding with record deletion.",
                card_id,
            )

    deleted = repository.delete(card_id)
    if not deleted:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error_code": "record_not_found", "message": f"No record found with id {card_id}."},
        )
