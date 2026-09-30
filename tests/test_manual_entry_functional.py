from datetime import date

import pytest

from app.logic import DOCUMENT_TYPES
from app.models import Application, Document
from tests.conftest import TODAY

VALID_FORM = {
    "application_id": "APP-2026-2001",
    "business_name": "Fresh Bakery",
    "borrower_name": "Dana Cook",
    "assigned_processor": "Aisha Patel",
    "loan_amount": "$1,250,000",
    "application_date": "2026-01-01",
}


def create(client, **overrides):
    return client.post(
        "/applications", data={**VALID_FORM, **overrides}, follow_redirects=False
    )


def get_application(session_factory, application_id):
    with session_factory() as db:
        application = db.get(Application, application_id)
        if application is not None:
            len(application.documents)  # load before the session closes
            db.expunge_all()
        return application


# --- new application ---------------------------------------------------------


def test_new_application_form_prefills_next_id_and_today(client):
    response = client.get("/applications/new")
    assert response.status_code == 200
    assert 'value="APP-2026-1001"' in response.text
    assert 'value="2026-01-01"' in response.text
    for processor in ("Aisha Patel", "Janet Morrison", "Ricardo Fuentes"):
        assert processor in response.text


def test_list_page_links_to_new_application(client):
    assert 'href="/applications/new"' in client.get("/").text


def test_create_application_adds_it_with_the_standard_documents(client, session_factory):
    response = create(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/applications/APP-2026-2001"

    application = get_application(session_factory, "APP-2026-2001")
    assert application.loan_amount == 1250000.0
    assert application.assigned_processor == "Aisha Patel"
    assert application.application_date == date(2026, 1, 1)
    assert application.last_activity == TODAY
    assert sorted(d.document_type for d in application.documents) == sorted(DOCUMENT_TYPES)
    assert {d.document_status for d in application.documents} == {"Pending"}


def test_created_application_appears_in_the_list_and_has_a_detail_page(client):
    create(client)
    assert "Fresh Bakery" in client.get("/").text
    assert client.get("/applications/APP-2026-2001").status_code == 200


def test_create_trims_whitespace(client, session_factory):
    create(client, business_name="  Fresh Bakery  ", application_id=" APP-2026-2001 ")
    assert get_application(session_factory, "APP-2026-2001").business_name == "Fresh Bakery"


def test_blank_application_date_is_allowed(client, session_factory):
    assert create(client, application_date="").status_code == 303
    assert get_application(session_factory, "APP-2026-2001").application_date is None


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"application_id": ""}, "Application ID is required"),
        ({"application_id": "bad id/../"}, "letters, numbers"),
        ({"application_id": "APP-MILD"}, "already exists"),
        ({"application_id": "app-mild"}, "already exists"),
        ({"business_name": "  "}, "Business name is required"),
        ({"borrower_name": ""}, "Borrower name is required"),
        ({"assigned_processor": ""}, "Choose a processor"),
        ({"assigned_processor": "Nobody Real"}, "Choose a processor"),
        ({"loan_amount": ""}, "Loan amount is required"),
        ({"loan_amount": "lots"}, "positive number"),
        ({"loan_amount": "-5"}, "positive number"),
        ({"loan_amount": "nan"}, "positive number"),
        ({"application_date": "not-a-date"}, "valid date"),
    ],
)
def test_invalid_create_shows_error_and_saves_nothing(
    client, session_factory, overrides, message
):
    with session_factory() as db:
        before = db.query(Application).count()
    response = create(client, **overrides)
    assert response.status_code == 400
    assert message in response.text
    with session_factory() as db:
        assert db.query(Application).count() == before


def test_invalid_create_keeps_what_the_user_typed(client):
    response = create(client, loan_amount="lots")
    assert 'value="Fresh Bakery"' in response.text
    assert 'value="lots"' in response.text


# --- edit application --------------------------------------------------------


def edit(client, application_id="APP-MID", **overrides):
    data = {
        "business_name": "Mid Co",
        "borrower_name": "Owner of Mid Co",
        "assigned_processor": "Aisha Patel",
        "loan_amount": "100000",
        "application_date": "2025-11-01",
        **overrides,
    }
    return client.post(
        f"/applications/{application_id}/edit", data=data, follow_redirects=False
    )


def test_edit_form_is_prefilled_and_id_is_not_editable(client):
    response = client.get("/applications/APP-MID/edit")
    assert response.status_code == 200
    assert 'value="Mid Co"' in response.text
    assert 'value="100000"' in response.text
    assert 'name="application_id"' not in response.text


def test_edit_updates_fields_and_records_activity(client, session_factory):
    with session_factory() as db:
        db.get(Application, "APP-MID").last_activity = date(2025, 6, 1)
        db.commit()
    response = edit(
        client,
        assigned_processor="Janet Morrison",
        loan_amount="175,500",
        business_name="Mid Co LLC",
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/applications/APP-MID"
    application = get_application(session_factory, "APP-MID")
    assert application.assigned_processor == "Janet Morrison"
    assert application.loan_amount == 175500.0
    assert application.business_name == "Mid Co LLC"
    assert application.last_activity == TODAY
    assert len(application.documents) == 2


def test_edit_can_clear_the_application_date(client, session_factory):
    edit(client, application_date="")
    assert get_application(session_factory, "APP-MID").application_date is None


def test_invalid_edit_is_rejected_and_changes_nothing(client, session_factory):
    response = edit(client, loan_amount="-1", business_name="Changed")
    assert response.status_code == 400
    assert "positive number" in response.text
    application = get_application(session_factory, "APP-MID")
    assert application.business_name == "Mid Co"
    assert application.loan_amount == 100000.0


def test_edit_unknown_application_is_404(client):
    assert client.get("/applications/NOPE/edit").status_code == 404
    assert edit(client, "NOPE").status_code == 404


def test_detail_page_links_to_edit(client):
    assert 'href="/applications/APP-MID/edit"' in client.get("/applications/APP-MID").text


# --- add / remove documents --------------------------------------------------


def add(client, application_id="APP-MID", document_type="Debt Schedule"):
    return client.post(
        f"/applications/{application_id}/documents",
        data={"document_type": document_type},
        follow_redirects=False,
    )


def first_document_id(session_factory, application_id, document_type):
    with session_factory() as db:
        return (
            db.query(Document)
            .filter_by(application_id=application_id, document_type=document_type)
            .one()
            .id
        )


def test_detail_offers_only_types_not_already_on_the_application(client):
    html = client.get("/applications/APP-MID").text
    form = html.split('id="add-document-form"')[1].split("</form>")[0]
    assert '<option value="Debt Schedule">' in form
    assert '<option value="Lease Agreement">' not in form
    assert '<option value="Insurance Verification">' not in form


def test_add_document_creates_a_pending_row_and_records_activity(client, session_factory):
    with session_factory() as db:
        db.get(Application, "APP-MID").last_activity = date(2025, 6, 1)
        db.commit()
    response = add(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/applications/APP-MID"
    application = get_application(session_factory, "APP-MID")
    added = [d for d in application.documents if d.document_type == "Debt Schedule"]
    assert len(added) == 1
    assert added[0].document_status == "Pending"
    assert application.last_activity == TODAY


def test_added_document_shows_up_and_raises_outstanding_count(client):
    add(client)
    html = client.get("/applications/APP-MID").text
    assert "Debt Schedule" in html
    assert '<dd id="sum-outstanding">2</dd>' in html


def test_adding_a_duplicate_type_is_a_harmless_no_op(client, session_factory):
    add(client)
    assert add(client).status_code == 303
    assert len(get_application(session_factory, "APP-MID").documents) == 3


def test_adding_an_unknown_type_is_rejected(client, session_factory):
    assert add(client, document_type="Napkin Sketch").status_code == 422
    assert add(client, document_type="").status_code == 422
    assert len(get_application(session_factory, "APP-MID").documents) == 2


def test_add_document_to_unknown_application_is_404(client):
    assert add(client, "NOPE").status_code == 404


def test_add_form_is_replaced_by_a_message_when_all_types_are_present(client, session_factory):
    with session_factory() as db:
        have = {d.document_type for d in db.get(Application, "APP-MID").documents}
        for doc_type in DOCUMENT_TYPES:
            if doc_type not in have:
                db.add(
                    Document(
                        application_id="APP-MID",
                        document_type=doc_type,
                        document_status="Pending",
                    )
                )
        db.commit()
    html = client.get("/applications/APP-MID").text
    assert 'id="add-document-form"' not in html
    assert "All standard document types are already on this application" in html


def test_each_row_has_a_remove_form_with_a_confirm_prompt(client, session_factory):
    doc_id = first_document_id(session_factory, "APP-MID", "Lease Agreement")
    html = client.get("/applications/APP-MID").text
    assert f'action="/applications/APP-MID/documents/{doc_id}/delete"' in html
    assert 'data-confirm="Remove Lease Agreement from this application?"' in html
    assert 'onsubmit="return confirm(this.dataset.confirm)"' in html


def test_remove_document_deletes_only_that_row(client, session_factory):
    doc_id = first_document_id(session_factory, "APP-MID", "Lease Agreement")
    response = client.post(
        f"/applications/APP-MID/documents/{doc_id}/delete", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/applications/APP-MID"
    application = get_application(session_factory, "APP-MID")
    assert [d.document_type for d in application.documents] == ["Insurance Verification"]
    assert application.last_activity == TODAY
    assert len(get_application(session_factory, "APP-MILD").documents) == 1


def test_removed_type_can_be_added_back(client, session_factory):
    doc_id = first_document_id(session_factory, "APP-MID", "Lease Agreement")
    client.post(f"/applications/APP-MID/documents/{doc_id}/delete")
    html = client.get("/applications/APP-MID").text
    assert '<option value="Lease Agreement">' in html


def test_removing_twice_is_a_harmless_no_op(client, session_factory):
    doc_id = first_document_id(session_factory, "APP-MID", "Lease Agreement")
    client.post(f"/applications/APP-MID/documents/{doc_id}/delete")
    response = client.post(
        f"/applications/APP-MID/documents/{doc_id}/delete", follow_redirects=False
    )
    assert response.status_code == 303


def test_cannot_remove_a_document_through_another_application(client, session_factory):
    doc_id = first_document_id(session_factory, "APP-MID", "Lease Agreement")
    client.post(f"/applications/APP-MILD/documents/{doc_id}/delete")
    assert len(get_application(session_factory, "APP-MID").documents) == 2


def test_remove_from_unknown_application_is_404(client):
    assert client.post("/applications/NOPE/documents/1/delete").status_code == 404
