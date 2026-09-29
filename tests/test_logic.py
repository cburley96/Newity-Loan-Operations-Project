from datetime import date
from types import SimpleNamespace

from app.logic import (
    EXPIRING_SOON_DAYS,
    application_summary,
    days_until_expiration,
    is_outstanding,
    pipeline_summary,
)

TODAY = date(2026, 1, 1)


def doc(status="Approved", expiration=None):
    return SimpleNamespace(document_status=status, expiration_date=expiration)


def app(processor="Aisha Patel", documents=()):
    return SimpleNamespace(assigned_processor=processor, documents=list(documents))


def test_is_outstanding_true_for_pending_and_expired():
    assert is_outstanding("Pending")
    assert is_outstanding("Expired")


def test_is_outstanding_false_for_all_other_statuses():
    for status in ("Approved", "Received", "Under Review", "Not Required"):
        assert not is_outstanding(status)


def test_days_until_expiration_none_when_no_date():
    assert days_until_expiration(None, TODAY) is None


def test_days_until_expiration_future_today_and_past():
    assert days_until_expiration(date(2026, 1, 11), TODAY) == 10
    assert days_until_expiration(TODAY, TODAY) == 0
    assert days_until_expiration(date(2025, 12, 22), TODAY) == -10


def test_application_summary_counts_outstanding():
    a = app(documents=[doc("Pending"), doc("Expired"), doc("Approved")])
    assert application_summary(a, TODAY)["outstanding_count"] == 2


def test_application_summary_expiration_flags():
    a = app(
        documents=[
            doc(expiration=date(2025, 12, 31)),
            doc(expiration=date(2026, 1, 31)),
            doc(expiration=date(2026, 6, 1)),
            doc(expiration=None),
        ]
    )
    s = application_summary(a, TODAY)
    assert s["expired_count"] == 1
    assert s["expiring_soon_count"] == 1
    assert s["has_expiration_issue"] is True


def test_expiring_soon_boundary_is_inclusive():
    from datetime import timedelta

    edge = TODAY + timedelta(days=EXPIRING_SOON_DAYS)
    beyond = edge + timedelta(days=1)
    assert application_summary(app(documents=[doc(expiration=edge)]), TODAY)[
        "expiring_soon_count"
    ] == 1
    assert application_summary(app(documents=[doc(expiration=beyond)]), TODAY)[
        "expiring_soon_count"
    ] == 0


def test_not_required_documents_never_flagged_for_expiration():
    a = app(documents=[doc("Not Required", expiration=date(2020, 1, 1))])
    s = application_summary(a, TODAY)
    assert s["expired_count"] == 0
    assert s["has_expiration_issue"] is False


def test_application_summary_clean_application():
    s = application_summary(app(documents=[doc("Approved")]), TODAY)
    assert s == {
        "outstanding_count": 0,
        "expired_count": 0,
        "expiring_soon_count": 0,
        "has_expiration_issue": False,
    }


def test_pipeline_summary_aggregates_and_groups_by_processor():
    apps = [
        app("Aisha Patel", [doc("Pending"), doc("Approved")]),
        app("Aisha Patel", [doc("Approved", expiration=date(2025, 1, 1))]),
        app("Janet Morrison", [doc("Expired"), doc("Pending")]),
    ]
    s = pipeline_summary(apps, TODAY)
    assert s["total_applications"] == 3
    assert s["total_outstanding"] == 3
    assert s["applications_with_outstanding"] == 2
    assert s["applications_with_expiration_issue"] == 1
    assert s["by_processor"]["Aisha Patel"] == {
        "applications": 2,
        "outstanding": 1,
    }
    assert s["by_processor"]["Janet Morrison"] == {
        "applications": 1,
        "outstanding": 2,
    }


def test_pipeline_summary_empty():
    s = pipeline_summary([], TODAY)
    assert s["total_applications"] == 0
    assert s["by_processor"] == {}
