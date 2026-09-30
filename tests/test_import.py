from datetime import date

import pytest

from app.importer import ImportFileError, import_csv
from app.models import Application, Document

HEADER = (
    "application_id,business_name,borrower_name,loan_amount,application_date,"
    "assigned_processor,document_type,document_status,date_received,expiration_date,notes\n"
)


def csv_bytes(*rows, header=HEADER):
    return (header + "\n".join(rows) + "\n").encode("utf-8")


NEW_ROW = "APP-NEW,New Co,Pat Owner,\"120,000\",3/5/2026,Aisha Patel,Lease Agreement,Pending,,,"


def counts(session_factory):
    with session_factory() as db:
        return db.query(Application).count(), db.query(Document).count()


def test_adds_new_application_and_document(session_factory):
    with session_factory() as db:
        result = import_csv(db, csv_bytes(NEW_ROW))
    assert (result.new_applications, result.added_documents) == (1, 1)
    assert result.duplicates == [] and result.invalid == []
    with session_factory() as db:
        application = db.get(Application, "APP-NEW")
        assert application.loan_amount == 120000.0
        assert application.application_date == date(2026, 3, 5)
        assert application.last_activity == date(2026, 3, 5)
        assert len(application.documents) == 1


def test_existing_document_is_duplicate_and_not_overwritten(client, session_factory):
    row = "APP-MILD,Mild Co,Owner,1,1/1/2026,Aisha Patel,Lease Agreement,Approved,,,changed"
    with session_factory() as db:
        result = import_csv(db, csv_bytes(row))
    assert result.added_documents == 0
    assert result.duplicates == [
        {"row": 2, "application_id": "APP-MILD", "document_type": "Lease Agreement"}
    ]
    with session_factory() as db:
        doc = db.query(Document).filter_by(application_id="APP-MILD").one()
        assert doc.document_status == "Pending" and doc.notes is None


def test_new_document_type_on_existing_application_is_added(client, session_factory):
    row = "APP-MILD,Mild Co,Owner,1,1/1/2026,Aisha Patel,Ownership Verification,Received,1/2/2026,,"
    with session_factory() as db:
        result = import_csv(db, csv_bytes(row))
    assert (result.new_applications, result.added_documents) == (0, 1)
    with session_factory() as db:
        assert db.get(Application, "APP-MILD").business_name == "Mild Co"
        assert db.query(Document).filter_by(application_id="APP-MILD").count() == 2


def test_duplicate_within_the_same_file(session_factory):
    with session_factory() as db:
        result = import_csv(db, csv_bytes(NEW_ROW, NEW_ROW))
    assert result.added_documents == 1
    assert [d["row"] for d in result.duplicates] == [3]
    assert counts(session_factory) == (1, 1)


@pytest.mark.parametrize(
    "row, reason",
    [
        ("APP-X,Co,Own,1,1/1/2026,Aisha Patel,Lease Agreement,Bogus,,,", "Unknown document_status"),
        ("APP-X,Co,Own,abc,1/1/2026,Aisha Patel,Lease Agreement,Pending,,,", "loan_amount"),
        ("APP-X,Co,Own,-5,1/1/2026,Aisha Patel,Lease Agreement,Pending,,,", "negative"),
        ("APP-X,Co,Own,1,2026-01-01,Aisha Patel,Lease Agreement,Pending,,,", "application_date"),
        ("APP-X,Co,Own,1,1/1/2026,Aisha Patel,Lease Agreement,Pending,13/40/2026,,", "date_received"),
        (",Co,Own,1,1/1/2026,Aisha Patel,Lease Agreement,Pending,,,", "application_id is missing"),
        ("APP-X,Co,Own,1,1/1/2026,,Lease Agreement,Pending,,,", "assigned_processor is missing"),
    ],
)
def test_invalid_rows_are_reported_and_not_imported(session_factory, row, reason):
    with session_factory() as db:
        result = import_csv(db, csv_bytes(row))
    assert result.added_documents == 0
    assert len(result.invalid) == 1
    assert result.invalid[0]["row"] == 2
    assert reason in result.invalid[0]["reason"]
    assert counts(session_factory) == (0, 0)


def test_invalid_rows_do_not_block_valid_ones(session_factory):
    bad = "APP-BAD,Co,Own,1,1/1/2026,Aisha Patel,Lease Agreement,Bogus,,,"
    with session_factory() as db:
        result = import_csv(db, csv_bytes(bad, NEW_ROW))
    assert result.added_documents == 1
    assert [r["row"] for r in result.invalid] == [2]
    assert counts(session_factory) == (1, 1)


def test_missing_columns_reject_the_file(session_factory):
    with session_factory() as db:
        with pytest.raises(ImportFileError, match="Missing column"):
            import_csv(db, b"application_id,business_name\nA,B\n")


def test_non_utf8_file_is_rejected(session_factory):
    with session_factory() as db:
        with pytest.raises(ImportFileError, match="not a readable CSV"):
            import_csv(db, b"\xff\xfe\x00bad")


def test_byte_order_mark_and_blank_lines_are_tolerated(session_factory):
    content = b"\xef\xbb\xbf" + csv_bytes(NEW_ROW, ",,,,,,,,,,")
    with session_factory() as db:
        result = import_csv(db, content)
    assert result.total_rows == 1 and result.added_documents == 1


def test_importing_the_same_file_twice_adds_nothing_the_second_time(session_factory):
    with session_factory() as db:
        import_csv(db, csv_bytes(NEW_ROW))
    with session_factory() as db:
        second = import_csv(db, csv_bytes(NEW_ROW))
    assert second.added_documents == 0 and len(second.duplicates) == 1
    assert counts(session_factory) == (1, 1)


def upload(client, content, name="data.csv"):
    return client.post("/import", files={"file": (name, content, "text/csv")})


def test_import_page_loads_with_form_and_nav_link(client):
    response = client.get("/import")
    assert response.status_code == 200
    assert 'enctype="multipart/form-data"' in response.text
    assert 'href="/import"' in response.text


def test_upload_reports_added_duplicates_and_invalid(client, session_factory):
    dup = "APP-MILD,Mild Co,Owner,1,1/1/2026,Aisha Patel,Lease Agreement,Pending,,,"
    bad = "APP-BAD,Co,Own,1,1/1/2026,Aisha Patel,Lease Agreement,Bogus,,,"
    response = upload(client, csv_bytes(NEW_ROW, dup, bad))
    assert response.status_code == 200
    assert '<strong id="res-added">1</strong>' in response.text
    assert '<strong id="res-new-apps">1</strong>' in response.text
    assert '<strong id="res-duplicates">1</strong>' in response.text
    assert '<strong id="res-invalid">1</strong>' in response.text
    assert "Unknown document_status" in response.text
    with session_factory() as db:
        assert db.get(Application, "APP-NEW") is not None


def test_uploaded_application_appears_in_the_list(client):
    upload(client, csv_bytes(NEW_ROW))
    assert "APP-NEW" in client.get("/").text


def test_bad_file_shows_error_and_changes_nothing(client, session_factory):
    before = counts(session_factory)
    response = upload(client, b"nope,nothing\n1,2\n")
    assert response.status_code == 400
    assert "Missing column" in response.text
    assert counts(session_factory) == before


def test_upload_without_a_file_is_rejected(client):
    assert client.post("/import").status_code == 422
