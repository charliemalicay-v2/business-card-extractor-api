from app.db.base import Base
from app.models import BusinessCardRecord


def test_table_name_and_registration():
    assert BusinessCardRecord.__tablename__ == "business_cards"
    assert "business_cards" in Base.metadata.tables


def test_all_design_columns_are_present():
    columns = {c.name for c in BusinessCardRecord.__table__.columns}

    expected = {"id", "status", "optional_fields", "raw_ocr_text", "qr_detected", "qr_decoded",
                "qr_raw_payload", "image_filename", "created_at", "updated_at"}
    for prefix in ("name", "position", "company", "email", "phone"):
        expected |= {f"{prefix}_value", f"{prefix}_status", f"{prefix}_ocr_llm_value", f"{prefix}_qr_value"}

    assert expected <= columns


def test_status_and_field_status_check_constraints_are_registered():
    constraint_names = {c.name for c in BusinessCardRecord.__table__.constraints if c.name}

    assert "ck_business_cards_status" in constraint_names
    for prefix in ("name", "position", "company", "email", "phone"):
        assert f"ck_business_cards_{prefix}_status" in constraint_names


def test_required_fields_are_not_nullable():
    non_nullable = {c.name for c in BusinessCardRecord.__table__.columns if not c.nullable}

    assert {"id", "status", "raw_ocr_text", "qr_detected", "qr_decoded", "created_at", "updated_at"} <= non_nullable
    for prefix in ("name", "position", "company", "email", "phone"):
        assert f"{prefix}_status" in non_nullable
        assert f"{prefix}_value" not in non_nullable
