import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BusinessCardRecord

_FIELD_NAMES = ("name", "position", "company", "email", "phone")


class CardRepository:
    def __init__(self, session: Session):
        self._session = session

    def create(self, record: BusinessCardRecord) -> BusinessCardRecord:
        self._session.add(record)
        self._session.commit()
        self._session.refresh(record)
        return record

    def get_by_id(self, record_id: uuid.UUID) -> BusinessCardRecord | None:
        return self._session.get(BusinessCardRecord, record_id)

    def list(
        self, status: str | None = None, page: int = 1, page_size: int = 20
    ) -> tuple[list[BusinessCardRecord], int]:
        query = select(BusinessCardRecord)
        count_query = select(func.count()).select_from(BusinessCardRecord)

        if status is not None:
            query = query.where(BusinessCardRecord.status == status)
            count_query = count_query.where(BusinessCardRecord.status == status)

        total = self._session.scalar(count_query) or 0

        query = (
            query.order_by(BusinessCardRecord.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        records = list(self._session.scalars(query).all())

        return records, total

    def update(self, record_id: uuid.UUID, fields: dict) -> BusinessCardRecord | None:
        record = self.get_by_id(record_id)
        if record is None:
            return None

        for key, value in fields.items():
            setattr(record, key, value)

        self._session.commit()
        self._session.refresh(record)
        return record

    def delete(self, record_id: uuid.UUID) -> bool:
        record = self.get_by_id(record_id)
        if record is None:
            return False

        self._session.delete(record)
        self._session.commit()
        return True

    def resolve_review(self, record_id: uuid.UUID, resolved_fields: dict[str, str | None]) -> BusinessCardRecord | None:
        record = self.get_by_id(record_id)
        if record is None:
            return None

        for field_name in _FIELD_NAMES:
            if field_name in resolved_fields:
                setattr(record, f"{field_name}_value", resolved_fields[field_name])
                setattr(record, f"{field_name}_status", "confirmed")

        record.status = "confirmed"
        self._session.commit()
        self._session.refresh(record)
        return record
