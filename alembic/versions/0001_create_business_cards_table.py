"""create business_cards table

Revision ID: 0001
Revises:
Create Date: 2026-07-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FIELD_STATUS_VALUES = ("confirmed", "conflict", "unverified")
RECORD_STATUS_VALUES = ("confirmed", "needs_review")


def _field_columns(prefix: str) -> list[sa.Column]:
    return [
        sa.Column(f"{prefix}_value", sa.String(), nullable=True),
        sa.Column(f"{prefix}_status", sa.String(), nullable=False),
        sa.Column(f"{prefix}_ocr_llm_value", sa.String(), nullable=True),
        sa.Column(f"{prefix}_qr_value", sa.String(), nullable=True),
    ]


def upgrade() -> None:
    columns = [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("status", sa.String(), nullable=False),
        *_field_columns("name"),
        *_field_columns("position"),
        *_field_columns("company"),
        *_field_columns("email"),
        *_field_columns("phone"),
        sa.Column("optional_fields", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("raw_ocr_text", sa.Text(), nullable=False),
        sa.Column("qr_detected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("qr_decoded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("qr_raw_payload", sa.Text(), nullable=True),
        sa.Column("image_filename", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table("business_cards", *columns)

    op.create_check_constraint(
        "ck_business_cards_status",
        "business_cards",
        sa.text(f"status IN {RECORD_STATUS_VALUES}").text,
    )
    for prefix in ("name", "position", "company", "email", "phone"):
        op.create_check_constraint(
            f"ck_business_cards_{prefix}_status",
            "business_cards",
            sa.text(f"{prefix}_status IN {FIELD_STATUS_VALUES}").text,
        )

    op.create_index("ix_business_cards_status", "business_cards", ["status"])


def downgrade() -> None:
    op.drop_index("ix_business_cards_status", table_name="business_cards")
    op.drop_table("business_cards")
