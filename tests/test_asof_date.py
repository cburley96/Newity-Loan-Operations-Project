from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app, get_today
from tests.conftest import build_sample_data


def test_get_today_defaults_to_the_real_date(monkeypatch):
    monkeypatch.delenv("ASOF_DATE", raising=False)
    assert get_today() == date.today()


def test_get_today_honours_asof_date(monkeypatch):
    monkeypatch.setenv("ASOF_DATE", "2026-02-15")
    assert get_today() == date(2026, 2, 15)


def test_get_today_rejects_a_malformed_asof_date(monkeypatch):
    monkeypatch.setenv("ASOF_DATE", "15/02/2026")
    with pytest.raises(ValueError):
        get_today()


@pytest.fixture
def real_today_client(session_factory):
    with session_factory() as db:
        build_sample_data(db)

    def override_get_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_asof_date_drives_days_since_activity_and_stalled(real_today_client, monkeypatch):
    monkeypatch.setenv("ASOF_DATE", "2026-01-01")
    fresh = real_today_client.get("/").text
    assert "Today" in fresh
    assert "Stalled" not in fresh

    monkeypatch.setenv("ASOF_DATE", "2026-03-01")
    later = real_today_client.get("/").text
    assert "59d ago" in later
    assert "Stalled" in later
