import re
from datetime import date

from app.models import Document
from tests.conftest import TODAY


def doc_id(session_factory, application_id, document_type):
    with session_factory() as db:
        return (
            db.query(Document)
            .filter_by(application_id=application_id, document_type=document_type)
            .one()
            .id
        )


def stored(session_factory, document_id):
    with session_factory() as db:
        d = db.get(Document, document_id)
        return d.document_status, d.date_received, d.expiration_date, d.notes


def add_document(session_factory, application_id, document_type, status, **kwargs):
    with session_factory() as db:
        d = Document(
            application_id=application_id,
            document_type=document_type,
            document_status=status,
            **kwargs,
        )
        db.add(d)
        db.commit()
        return d.id


def post(client, app_id, document_id, body):
    return client.post(f"/applications/{app_id}/documents/{document_id}", json=body)


# ---- detail page -----------------------------------------------------------


def test_detail_page_shows_facts_and_summary(client):
    html = client.get("/applications/APP-MID").text
    assert "Mid Co" in html
    assert "Aisha Patel" in html
    assert "$100,000" in html
    assert re.search(r'id="sum-outstanding">1<', html)
    assert re.search(r'id="sum-expired">0<', html)
    assert re.search(r'id="sum-expiring">1<', html)
    assert re.search(r'id="sum-severity">8<', html)


def test_detail_unknown_application_is_404(client):
    assert client.get("/applications/NOPE").status_code == 404


def test_detail_documents_ordered_problems_first(client):
    html = client.get("/applications/APP-MID").text
    assert html.index("Insurance Verification") < html.index("Lease Agreement")


def test_detail_shows_expiration_text_and_badge(client):
    html = client.get("/applications/APP-MID").text
    assert "Expires in 14 days" in html
    assert "Expiring soon" in html


def test_detail_document_marked_expired_never_says_expires_in_days(client, session_factory):
    add_document(
        session_factory, "APP-MID", "Personal Tax Returns (3yr)", "Expired",
        date_received=date(2025, 12, 1), expiration_date=date(2028, 12, 1),
    )
    html = client.get("/applications/APP-MID").text
    assert "Marked expired" in html
    assert "Expires in 1065 days" not in html


def test_detail_status_dropdown_offers_all_statuses_and_selects_current(client):
    html = client.get("/applications/APP-MID").text
    for status in ("Pending", "Received", "Under Review", "Approved", "Expired", "Not Required"):
        assert f'<option value="{status}"' in html
    assert re.search(r'<option value="Pending"\s+selected', html)


def test_detail_back_link_keeps_filter(client):
    html = client.get("/applications/APP-MID", params={"processor": "Aisha Patel"}).text
    assert 'href="/?processor=Aisha+Patel"' in html


def test_detail_prev_next_full_order(client):
    html = client.get("/applications/APP-MID").text
    assert 'href="/applications/APP-WORST"' in html
    assert 'href="/applications/APP-MILD"' in html


def test_detail_prev_next_follow_filter(client):
    html = client.get("/applications/APP-MID", params={"processor": "Aisha Patel"}).text
    assert 'id="prev-link"' not in html
    assert 'href="/applications/APP-MILD?processor=Aisha+Patel"' in html


def test_detail_first_and_last_have_no_dangling_links(client):
    assert 'id="prev-link"' not in client.get("/applications/APP-WORST").text
    assert 'id="next-link"' not in client.get("/applications/APP-CLEAN").text


def test_list_rows_link_to_detail_with_filter(client):
    html = client.get("/", params={"processor": "Aisha Patel"}).text
    assert 'href="/applications/APP-MID?processor=Aisha+Patel"' in html


# ---- save endpoint ---------------------------------------------------------


def test_status_change_persists(client, session_factory):
    d = doc_id(session_factory, "APP-MID", "Lease Agreement")
    response = post(client, "APP-MID", d, {"document_status": "Under Review"})
    assert response.status_code == 200
    assert stored(session_factory, d)[0] == "Under Review"
    page = client.get("/applications/APP-MID").text
    assert re.search(r'<option value="Under Review"\s+selected', page)


def test_response_returns_updated_document_and_summary(client, session_factory):
    d = doc_id(session_factory, "APP-WORST", "Business Tax Returns (3yr)")
    body = post(client, "APP-WORST", d, {"document_status": "Approved"}).json()
    assert body["document"]["document_status"] == "Approved"
    assert body["document"]["state"] == ""
    assert body["summary"]["outstanding_count"] == 0
    assert body["summary"]["severity_score"] == 0


def test_received_autofills_date_and_bank_statement_expiration(client, session_factory):
    d = add_document(session_factory, "APP-CLEAN", "Bank Statements (90 day)", "Pending")
    body = post(client, "APP-CLEAN", d, {"document_status": "Received"}).json()
    assert body["document"]["date_received"] == TODAY.isoformat()
    assert body["document"]["expiration_date"] == "2026-04-01"
    assert stored(session_factory, d)[1:3] == (TODAY, date(2026, 4, 1))


def test_received_tax_return_suggests_three_years(client, session_factory):
    d = add_document(session_factory, "APP-CLEAN", "Personal Tax Returns (3yr)", "Pending")
    body = post(client, "APP-CLEAN", d, {"document_status": "Received"}).json()
    assert body["document"]["expiration_date"] == "2029-01-01"


def test_received_other_type_fills_date_but_not_expiration(client, session_factory):
    d = doc_id(session_factory, "APP-MILD", "Lease Agreement")
    body = post(client, "APP-MILD", d, {"document_status": "Received"}).json()
    assert body["document"]["date_received"] == TODAY.isoformat()
    assert body["document"]["expiration_date"] == ""


def test_received_does_not_overwrite_existing_dates(client, session_factory):
    d = add_document(
        session_factory,
        "APP-CLEAN",
        "Bank Statements (90 day)",
        "Pending",
        date_received=date(2025, 12, 1),
        expiration_date=date(2026, 6, 1),
    )
    post(client, "APP-CLEAN", d, {"document_status": "Received"})
    assert stored(session_factory, d)[1:3] == (date(2025, 12, 1), date(2026, 6, 1))


def test_received_respects_dates_sent_in_same_request(client, session_factory):
    d = add_document(session_factory, "APP-CLEAN", "Bank Statements (90 day)", "Pending")
    post(
        client,
        "APP-CLEAN",
        d,
        {"document_status": "Received", "date_received": "2025-12-15", "expiration_date": None},
    )
    assert stored(session_factory, d)[1:3] == (date(2025, 12, 15), None)


def test_already_received_status_does_not_refill(client, session_factory):
    d = add_document(session_factory, "APP-CLEAN", "Lease Agreement", "Received")
    post(client, "APP-CLEAN", d, {"document_status": "Received"})
    assert stored(session_factory, d)[1] is None


def test_dates_can_be_edited_and_cleared(client, session_factory):
    d = doc_id(session_factory, "APP-MID", "Insurance Verification")
    post(client, "APP-MID", d, {"expiration_date": "2026-12-31"})
    assert stored(session_factory, d)[2] == date(2026, 12, 31)
    post(client, "APP-MID", d, {"expiration_date": None})
    assert stored(session_factory, d)[2] is None


def test_partial_update_leaves_other_fields_alone(client, session_factory):
    d = doc_id(session_factory, "APP-MID", "Insurance Verification")
    post(client, "APP-MID", d, {"notes": "called borrower"})
    status, _, expiration, notes = stored(session_factory, d)
    assert (status, expiration, notes) == ("Approved", date(2026, 1, 15), "called borrower")


def test_blank_notes_stored_as_none(client, session_factory):
    d = doc_id(session_factory, "APP-MID", "Lease Agreement")
    post(client, "APP-MID", d, {"notes": "something"})
    post(client, "APP-MID", d, {"notes": "   "})
    assert stored(session_factory, d)[3] is None


def test_invalid_status_rejected_and_unchanged(client, session_factory):
    d = doc_id(session_factory, "APP-MID", "Lease Agreement")
    assert post(client, "APP-MID", d, {"document_status": "Bogus"}).status_code == 422
    assert stored(session_factory, d)[0] == "Pending"


def test_malformed_date_rejected(client, session_factory):
    d = doc_id(session_factory, "APP-MID", "Lease Agreement")
    assert post(client, "APP-MID", d, {"expiration_date": "not-a-date"}).status_code == 422


def test_document_from_other_application_is_404(client, session_factory):
    d = doc_id(session_factory, "APP-MID", "Lease Agreement")
    assert post(client, "APP-CLEAN", d, {"notes": "x"}).status_code == 404
    assert stored(session_factory, d)[3] is None


def test_unknown_document_is_404(client):
    assert post(client, "APP-MID", 99999, {"notes": "x"}).status_code == 404


def test_updates_change_list_ranking(client, session_factory):
    d = doc_id(session_factory, "APP-WORST", "Business Tax Returns (3yr)")
    post(client, "APP-WORST", d, {"document_status": "Approved"})
    ids = re.findall(r'data-application-id="([^"]+)"', client.get("/").text)
    assert ids == ["APP-MID", "APP-MILD", "APP-CLEAN", "APP-WORST"]


# ---- explicit per-row save -------------------------------------------------


def test_rows_start_with_hidden_save_and_cancel_buttons(client):
    html = client.get("/applications/APP-MID").text
    assert html.count('class="row-actions" hidden') == 2
    assert html.count('class="row-save"') == 2
    assert html.count('class="row-cancel') == 2


def test_multiple_fields_save_together_in_one_request(client, session_factory):
    d = doc_id(session_factory, "APP-MID", "Lease Agreement")
    response = post(
        client,
        "APP-MID",
        d,
        {"document_status": "Under Review", "date_received": "2025-12-30", "notes": "checking"},
    )
    assert response.status_code == 200
    assert stored(session_factory, d) == (
        "Under Review", date(2025, 12, 30), None, "checking"
    )
