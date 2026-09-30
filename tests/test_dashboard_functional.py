import re

from app.models import Application, Document
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


# --- leadership summary ------------------------------------------------------


def table_section(html, table_id):
    return html.split(f'id="{table_id}"')[1].split("</table>")[0]


def row_ids(html, table_id):
    return re.findall(r'data-application-id="([^"]+)"', table_section(html, table_id))


def test_top_applications_are_ranked_and_skip_healthy_ones(client):
    html = client.get("/dashboard").text
    assert row_ids(html, "top-applications") == ["APP-WORST", "APP-MID", "APP-MILD"]
    assert "APP-CLEAN" not in table_section(html, "top-applications")


def test_top_applications_rows_link_to_detail_pages(client):
    section = table_section(client.get("/dashboard").text, "top-applications")
    assert 'href="/applications/APP-WORST"' in section
    assert "Worst Co" in section
    assert "Ricardo Fuentes" in section


def test_top_applications_show_flags(client, session_factory):
    set_activity(session_factory, "APP-WORST", STALE)
    section = table_section(client.get("/dashboard").text, "top-applications")
    worst_row = section.split('data-application-id="APP-WORST"')[1].split("</tr>")[0]
    assert "1 expired" in worst_row
    assert "Stalled" in worst_row


def test_attention_documents_lists_expired_then_expiring(client):
    html = client.get("/dashboard").text
    assert row_ids(html, "attention-documents") == ["APP-WORST", "APP-MID"]
    section = table_section(html, "attention-documents")
    assert "Business Tax Returns (3yr)" in section
    assert "Marked expired" in section
    assert "Insurance Verification" in section
    assert "Expires in 14 days" in section
    assert 'href="/applications/APP-MID"' in section
    assert "Showing 2 of 2" in html


def test_attention_documents_are_capped_and_show_the_total(client, session_factory):
    with session_factory() as db:
        for i in range(20):
            db.add(
                Document(
                    application_id="APP-CLEAN",
                    document_type=f"Extra {i:02d}",
                    document_status="Expired",
                )
            )
        db.commit()
    html = client.get("/dashboard").text
    assert len(row_ids(html, "attention-documents")) == 15
    assert "Showing 15 of 22" in html


def test_summary_sections_show_empty_messages(client, session_factory):
    with session_factory() as db:
        for application in db.query(Application).all():
            db.delete(application)
        db.commit()
    html = client.get("/dashboard").text
    assert "Nothing needs attention right now." in html
    assert "No expired or expiring documents." in html


# --- front-end polish --------------------------------------------------------


def current_links(html):
    return re.findall(r'<a href="([^"]+)" aria-current="page"', html)


def test_nav_marks_the_current_page(client):
    assert current_links(client.get("/dashboard").text) == ["/dashboard"]
    assert current_links(client.get("/").text) == ["/"]
    assert current_links(client.get("/import").text) == ["/import"]


def test_nav_keeps_applications_active_on_detail_pages(client):
    assert current_links(client.get("/applications/APP-WORST").text) == ["/"]


def test_list_puts_filter_and_new_button_in_one_toolbar(client):
    html = client.get("/").text
    toolbar = html.split('class="toolbar"')[1].split("</div>")[0]
    assert 'id="processor"' in toolbar
    assert 'id="new-application-link"' in toolbar
