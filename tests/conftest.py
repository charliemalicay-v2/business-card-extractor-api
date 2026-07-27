import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal


@pytest.fixture
def db_session():
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(text("TRUNCATE TABLE business_cards"))
        session.commit()
        session.close()
