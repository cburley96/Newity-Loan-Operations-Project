import re

from app.seed import seed_if_empty
from app.models import Application, Document


def row_ids(html):
    return re.findall(r'data-application-id="([^"]+)"', html)


def test_list_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Applications" in response.text
    assert "pico" in response.text


def test_list_sorted_most_severe_first(client):
    assert row_ids(client.get("/").text) == [
        "APP-WORST",
        "APP-MID",
        "APP-MILD",
        "APP-CLEAN",
    ]


def test_processor_filter_narrows_rows_and_keeps_order(client):
    response = client.get("/", params={"processor": "Aisha Patel"})
    assert row_ids(response.text) == ["APP-MID", "APP-MILD"]


def test_processor_filter_marks_selection(client):
    html = client.get("/", params={"processor": "Janet Morrison"}).text
    assert re.search(r'<option value="Janet Morrison"\s+selected', html)


def test_processor_dropdown_lists_all_processors(client):
    html = client.get("/", params={"processor": "Janet Morrison"}).text
    for name in ("Aisha Patel", "Janet Morrison", "Ricardo Fuentes"):
        assert f'<option value="{name}"' in html


def test_unknown_processor_shows_empty_state(client):
    html = client.get("/", params={"processor": "Nobody"}).text
    assert row_ids(html) == []
    assert "No applications match this filter." in html


def test_expiration_flags_render(client):
    html = client.get("/").text
    worst_row = html.split('data-application-id="APP-WORST"')[1].split("</tr>")[0]
    mid_row = html.split('data-application-id="APP-MID"')[1].split("</tr>")[0]
    clean_row = html.split('data-application-id="APP-CLEAN"')[1].split("</tr>")[0]
    assert "1 expired" in worst_row
    assert "1 expiring soon" in mid_row
    assert "badge" not in clean_row


def test_outstanding_count_and_loan_amount_render(client):
    html = client.get("/").text
    worst_row = html.split('data-application-id="APP-WORST"')[1].split("</tr>")[0]
    assert "$250,000" in worst_row
    assert '<td class="num">1</td>' in worst_row


def test_static_stylesheet_served(client):
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert "badge-expired" in response.text


def test_seed_loads_full_sample_dataset(session_factory):
    with session_factory() as db:
        seed_if_empty(db)
        assert db.query(Application).count() == 60
        assert db.query(Document).count() == 620


def test_seed_is_idempotent(session_factory):
    with session_factory() as db:
        seed_if_empty(db)
        seed_if_empty(db)
        assert db.query(Application).count() == 60
