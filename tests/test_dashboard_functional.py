import re

from tests.conftest import TODAY
from tests.test_stalled_functional import STALE, set_activity


def text_of(html, element_id):
    return re.search(rf'id="{element_id}">(\d+)<', html).group(1)


def test_dashboard_renders_headline_numbers(client):
    html = client.get("/dashboard").text
    assert text_of(html, "stat-applications") == "4"
    assert text_of(html, "stat-outstanding") == "3"
    assert text_of(html, "stat-with-outstanding") == "3"
    assert text_of(html, "stat-expired") == "1"
    assert text_of(html, "stat-expiring") == "1"
    assert text_of(html, "ring-total") == "4"


def test_dashboard_legend_matches_ring_buckets(client):
    html = client.get("/dashboard").text
    assert text_of(html, "legend-complete") == "1"
    assert text_of(html, "legend-in-progress") == "3"
    assert text_of(html, "legend-stalled") == "0"


def test_dashboard_ring_draws_only_nonempty_segments(client):
    html = client.get("/dashboard").text
    assert "ring-segment ring-complete" in html
    assert "ring-segment ring-in-progress" in html
    assert "ring-segment ring-stalled" not in html


def test_dashboard_stalled_application_moves_between_buckets(client, session_factory):
    set_activity(session_factory, "APP-MILD", STALE)
    html = client.get("/dashboard").text
    assert text_of(html, "legend-in-progress") == "2"
    assert text_of(html, "legend-stalled") == "1"
    assert "ring-segment ring-stalled" in html


def test_dashboard_processor_table_sorted_by_workload(client):
    html = client.get("/dashboard").text
    table = html[html.index('id="processor-table"'):]
    assert table.index("Aisha Patel") < table.index("Ricardo Fuentes") < table.index("Janet Morrison")


def test_dashboard_processor_links_to_filtered_list(client):
    assert 'href="/?processor=Aisha%20Patel"' in client.get("/dashboard").text


def test_dashboard_with_no_applications(client, session_factory):
    from app.models import Application, Document

    with session_factory() as db:
        db.query(Document).delete()
        db.query(Application).delete()
        db.commit()
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert text_of(response.text, "ring-total") == "0"
    assert "No applications yet." in response.text


def test_nav_links_to_dashboard_and_applications(client):
    html = client.get("/").text
    assert 'href="/dashboard"' in html
    assert 'href="/"' in html
