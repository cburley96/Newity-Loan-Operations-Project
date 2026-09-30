import re
from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import Application, Document
from app.seed import derive_last_activity, seed_if_empty, upgrade_schema
from tests.conftest import TODAY

STALE = date(2025, 12, 1)


def set_activity(session_factory, application_id, value):
    with session_factory() as db:
        db.get(Application, application_id).last_activity = value
        db.commit()


def activity(session_factory, application_id):
    with session_factory() as db:
        return db.get(Application, application_id).last_activity


def only_document_id(session_factory, application_id):
    with session_factory() as db:
        return db.query(Document).filter_by(application_id=application_id).one().id


def test_stalled_application_flagged_on_list_and_moves_up(client, session_factory):
    with session_factory() as db:
        db.add(Document(application_id="APP-MILD", document_type="Insurance Verification", document_status="Pending"))
        db.commit()
    before = re.findall(r'data-application-id="([^"]+)"', client.get("/").text)
    assert before[:3] == ["APP-WORST", "APP-MID", "APP-MILD"]

    set_activity(session_factory, "APP-MILD", STALE)
    html = client.get("/").text
    assert html.count("badge-stalled") == 1
    ids = re.findall(r'data-application-id="([^"]+)"', html)
    assert ids[:3] == ["APP-WORST", "APP-MILD", "APP-MID"]


def test_stalled_only_when_work_remains(client, session_factory):
    set_activity(session_factory, "APP-CLEAN", STALE)
    assert "badge-stalled" not in client.get("/").text


def test_detail_shows_stalled_and_last_activity(client, session_factory):
    set_activity(session_factory, "APP-MILD", STALE)
    html = client.get("/applications/APP-MILD").text
    assert re.search(r'id="sum-activity">31 days ago<', html)
    assert not re.search(r'id="stalled-badge"[^>]*hidden', html)
    assert re.search(r'id="sum-severity">8<', html)


def test_detail_not_stalled_hides_badge(client):
    html = client.get("/applications/APP-MILD").text
    assert re.search(r'id="stalled-badge"[^>]*hidden', html)
    assert re.search(r'id="sum-activity">Today<', html)


def test_editing_a_document_resets_stalled(client, session_factory):
    set_activity(session_factory, "APP-MILD", STALE)
    doc_id = only_document_id(session_factory, "APP-MILD")
    body = client.post(
        f"/applications/APP-MILD/documents/{doc_id}", json={"notes": "called borrower"}
    ).json()
    assert activity(session_factory, "APP-MILD") == TODAY
    assert body["summary"]["is_stalled"] is False
    assert body["activity_text"] == "Today"
    assert body["last_activity"] == TODAY.isoformat()
    assert "badge-stalled" not in client.get("/").text


def test_failed_update_does_not_count_as_activity(client, session_factory):
    set_activity(session_factory, "APP-MILD", STALE)
    doc_id = only_document_id(session_factory, "APP-MILD")
    client.post(f"/applications/APP-MILD/documents/{doc_id}", json={"document_status": "Bogus"})
    assert activity(session_factory, "APP-MILD") == STALE


def test_derive_last_activity_uses_latest_date():
    application = Application(application_date=date(2025, 1, 1))
    application.documents = [
        Document(date_received=date(2025, 3, 1)),
        Document(date_received=None),
        Document(date_received=date(2025, 2, 1)),
    ]
    assert derive_last_activity(application) == date(2025, 3, 1)
    assert derive_last_activity(Application(application_date=None, documents=[])) is None


def test_seed_sets_last_activity_for_every_application(session_factory):
    with session_factory() as db:
        seed_if_empty(db)
        assert db.query(Application).filter(Application.last_activity.is_(None)).count() == 0


def test_upgrade_schema_adds_and_backfills_column(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE applications (application_id VARCHAR PRIMARY KEY, business_name VARCHAR,"
                " borrower_name VARCHAR, loan_amount FLOAT, application_date DATE,"
                " assigned_processor VARCHAR)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE documents (id INTEGER PRIMARY KEY, application_id VARCHAR,"
                " document_type VARCHAR, document_status VARCHAR, date_received DATE,"
                " expiration_date DATE, notes TEXT)"
            )
        )
        conn.execute(text("INSERT INTO applications VALUES ('A1','B','O',1.0,'2025-01-01','P')"))
        conn.execute(
            text("INSERT INTO documents VALUES (1,'A1','Lease','Received','2025-04-01',NULL,NULL)")
        )
    with sessionmaker(bind=engine)() as db:
        upgrade_schema(db)
        assert db.get(Application, "A1").last_activity == date(2025, 4, 1)
