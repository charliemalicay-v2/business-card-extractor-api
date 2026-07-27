import uuid

from app.db.card_repository import CardRepository
from app.models import BusinessCardRecord


def _make_record(status: str = "confirmed", name_value: str = "Jane Doe") -> BusinessCardRecord:
    return BusinessCardRecord(
        status=status,
        name_value=name_value,
        name_status="confirmed",
        position_value="Sales Manager",
        position_status="confirmed",
        company_value="Acme Corp",
        company_status="confirmed",
        email_value="jane@acme.com",
        email_status="confirmed",
        phone_value="+1-555-0100",
        phone_status="confirmed",
        optional_fields={"website": "acme.com"},
        raw_ocr_text="Jane Doe\nSales Manager\nAcme Corp\njane@acme.com\n+1-555-0100",
        qr_detected=False,
        qr_decoded=False,
    )


def test_create_persists_and_returns_record_with_generated_id(db_session):
    repo = CardRepository(db_session)

    created = repo.create(_make_record())

    assert created.id is not None
    assert created.created_at is not None
    assert created.name_value == "Jane Doe"


def test_get_by_id_returns_persisted_record(db_session):
    repo = CardRepository(db_session)
    created = repo.create(_make_record())

    fetched = repo.get_by_id(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.email_value == "jane@acme.com"


def test_get_by_id_returns_none_for_unknown_id(db_session):
    repo = CardRepository(db_session)

    assert repo.get_by_id(uuid.uuid4()) is None


def test_list_filters_by_status(db_session):
    repo = CardRepository(db_session)
    repo.create(_make_record(status="confirmed", name_value="Confirmed One"))
    repo.create(_make_record(status="needs_review", name_value="Needs Review One"))

    confirmed_records, confirmed_total = repo.list(status="confirmed")
    review_records, review_total = repo.list(status="needs_review")

    assert confirmed_total == 1
    assert confirmed_records[0].name_value == "Confirmed One"
    assert review_total == 1
    assert review_records[0].name_value == "Needs Review One"


def test_list_paginates_results(db_session):
    repo = CardRepository(db_session)
    for i in range(5):
        repo.create(_make_record(name_value=f"Person {i}"))

    page_one, total = repo.list(page=1, page_size=2)
    page_two, _ = repo.list(page=2, page_size=2)

    assert total == 5
    assert len(page_one) == 2
    assert len(page_two) == 2
    assert {r.id for r in page_one}.isdisjoint({r.id for r in page_two})


def test_resolve_review_updates_fields_and_sets_confirmed_status(db_session):
    repo = CardRepository(db_session)
    record = repo.create(_make_record(status="needs_review"))

    resolved = repo.resolve_review(record.id, {"company": "Acme Corporation"})

    assert resolved is not None
    assert resolved.status == "confirmed"
    assert resolved.company_value == "Acme Corporation"
    assert resolved.company_status == "confirmed"


def test_resolve_review_returns_none_for_unknown_id(db_session):
    repo = CardRepository(db_session)

    assert repo.resolve_review(uuid.uuid4(), {"name": "Someone"}) is None
