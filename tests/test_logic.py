from datetime import date
from types import SimpleNamespace

from app.logic import (
    EXPIRING_SOON_DAYS,
    application_summary,
    days_until_expiration,
    document_severity,
    is_outstanding,
    pipeline_summary,
    rank_applications,
)

TODAY = date(2026, 1, 1)


def doc(status="Approved", expiration=None, doc_type="Lease Agreement"):
    return SimpleNamespace(
        document_type=doc_type, document_status=status, expiration_date=expiration
    )


def app(processor="Aisha Patel", documents=(), application_id="A"):
    return SimpleNamespace(
        application_id=application_id,
        assigned_processor=processor,
        documents=list(documents),
    )


def test_expired_status_without_date_counts_as_expired():
    s = application_summary(app(documents=[doc("Expired")]), TODAY)
    assert s["expired_count"] == 1
    assert s["has_expiration_issue"] is True


def test_expired_status_and_past_date_not_double_counted():
    d = doc("Expired", expiration=date(2025, 1, 1))
    assert application_summary(app(documents=[d]), TODAY)["expired_count"] == 1


def test_document_severity_ordering_expired_over_expiring_over_pending():
    expired = document_severity(doc("Expired"), TODAY)
    expiring = document_severity(doc("Approved", expiration=date(2026, 1, 10)), TODAY)
    pending = document_severity(doc("Pending"), TODAY)
    assert expired > expiring > pending > 0


def test_document_severity_zero_for_healthy_and_not_required():
    assert document_severity(doc("Approved"), TODAY) == 0
    assert document_severity(doc("Received"), TODAY) == 0
    assert document_severity(doc("Under Review"), TODAY) == 0
    assert document_severity(doc("Not Required"), TODAY) == 0


def test_priority_document_types_weigh_more():
    normal = document_severity(doc("Pending"), TODAY)
    for doc_type in (
        "Business Tax Returns (3yr)",
        "Personal Tax Returns (3yr)",
        "Bank Statements (90 day)",
    ):
        assert document_severity(doc("Pending", doc_type=doc_type), TODAY) > normal


def test_application_summary_includes_severity_score_sum():
    a = app(documents=[doc("Pending"), doc("Expired")])
    expected = document_severity(doc("Pending"), TODAY) + document_severity(
        doc("Expired"), TODAY
    )
    assert application_summary(a, TODAY)["severity_score"] == expected


def test_rank_applications_most_severe_first():
    mild = app(documents=[doc("Pending")], application_id="mild")
    worst = app(documents=[doc("Expired")], application_id="worst")
    clean = app(documents=[doc("Approved")], application_id="clean")
    ranked = rank_applications([mild, clean, worst], TODAY)
    assert [a.application_id for a, _ in ranked] == ["worst", "mild", "clean"]


def test_rank_applications_ties_break_by_application_id():
    b = app(documents=[doc("Pending")], application_id="B")
    a = app(documents=[doc("Pending")], application_id="A")
    ranked = rank_applications([b, a], TODAY)
    assert [x.application_id for x, _ in ranked] == ["A", "B"]


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
        "severity_score": 0,
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
    assert s["applications_with_expiration_issue"] == 2
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


def test_suggest_expiration_bank_statement_is_90_days():
    from app.logic import suggest_expiration

    assert suggest_expiration("Bank Statements (90 day)", date(2026, 1, 1)) == date(2026, 4, 1)


def test_suggest_expiration_tax_returns_are_3_years():
    from app.logic import suggest_expiration

    for doc_type in ("Business Tax Returns (3yr)", "Personal Tax Returns (3yr)"):
        assert suggest_expiration(doc_type, date(2026, 1, 1)) == date(2029, 1, 1)


def test_suggest_expiration_leap_day_falls_back_to_feb_28():
    from app.logic import suggest_expiration

    assert suggest_expiration("Business Tax Returns (3yr)", date(2024, 2, 29)) == date(2027, 2, 28)


def test_suggest_expiration_none_for_other_types_or_no_date():
    from app.logic import suggest_expiration

    assert suggest_expiration("Lease Agreement", date(2026, 1, 1)) is None
    assert suggest_expiration("Bank Statements (90 day)", None) is None


def test_document_state_is_public_and_labels_documents():
    from app.logic import document_state

    assert document_state(doc("Expired"), TODAY) == "expired"
    assert document_state(doc("Approved", expiration=date(2026, 1, 10)), TODAY) == "expiring_soon"
    assert document_state(doc("Pending"), TODAY) == "pending"
    assert document_state(doc("Approved"), TODAY) is None


def test_expiration_label_wording():
    from app.logic import expiration_label

    assert expiration_label(None) == ""
    assert expiration_label(12) == "Expires in 12 days"
    assert expiration_label(1) == "Expires in 1 day"
    assert expiration_label(0) == "Expires today"
    assert expiration_label(-1) == "Expired 1 day ago"
    assert expiration_label(-5) == "Expired 5 days ago"
