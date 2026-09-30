from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app, get_today
from app.models import Application, Document

TODAY = date(2026, 1, 1)


def _application(app_id, business, processor, loan=100000.0):
    return Application(
        application_id=app_id,
        business_name=business,
        borrower_name=f"Owner of {business}",
        loan_amount=loan,
        application_date=date(2025, 11, 1),
        assigned_processor=processor,
    )


def _document(app_id, doc_type, status, expiration=None):
    return Document(
        application_id=app_id,
        document_type=doc_type,
        document_status=status,
        expiration_date=expiration,
    )


def build_sample_data(db):
    db.add_all(
        [
            _application("APP-WORST", "Worst Co", "Ricardo Fuentes", 250000.0),
            _application("APP-MID", "Mid Co", "Aisha Patel"),
            _application("APP-MILD", "Mild Co", "Aisha Patel"),
            _application("APP-CLEAN", "Clean Co", "Janet Morrison"),
        ]
    )
    db.add_all(
        [
            _document("APP-WORST", "Business Tax Returns (3yr)", "Expired"),
            _document("APP-MID", "Lease Agreement", "Pending"),
            _document("APP-MID", "Insurance Verification", "Approved", date(2026, 1, 15)),
            _document("APP-MILD", "Lease Agreement", "Pending"),
            _document("APP-CLEAN", "Lease Agreement", "Approved"),
        ]
    )
    db.commit()


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


@pytest.fixture
def client(session_factory):
    with session_factory() as db:
        build_sample_data(db)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_today] = lambda: TODAY
    # No context manager: skips the startup hook so the real newity.db is never touched.
    yield TestClient(app)
    app.dependency_overrides.clear()
