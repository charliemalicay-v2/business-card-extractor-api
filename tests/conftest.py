import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.image_storage import ImageStorage
from app.services.image_storage.local_storage import LocalImageStorage


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


@pytest.fixture
def image_storage(tmp_path) -> ImageStorage:
    return LocalImageStorage(str(tmp_path))
