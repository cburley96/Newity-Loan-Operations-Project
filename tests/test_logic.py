from datetime import date, timedelta
from types import SimpleNamespace

from app.logic import (
    DOCUMENT_TYPES,
    PRIORITY_DOCUMENT_TYPES,
    STALLED_DAYS,
    STALLED_WEIGHT,
    activity_label,
    days_since_activity,
    is_complete,
    is_stalled,
    next_application_id,
    EXPIRING_SOON_DAYS,
    application_summary,
    attention_documents,
    days_until_expiration,
    document_severity,
    is_outstanding,
    pipeline_summary,
    rank_applications,
    top_applications,
)

TODAY = date(2026, 1, 1)


def doc(status="Approved", expiration=None, doc_type="Lease Agreement"):
    return SimpleNamespace(
        document_type=doc_type, document_status=status, expiration_date=expiration
    )


def app(processor="Aisha Patel", documents=(), application_id="A", last_activity=TODAY):
    return SimpleNamespace(
        application_id=application_id,
        business_name=f"Business {application_id}",
        assigned_processor=processor,
        documents=list(documents),
        last_activity=last_activity,
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
        "is_stalled": False,
        "is_complete": True,
        "days_since_activity": 0,
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
        "stalled": 0,
    }
    assert s["by_processor"]["Janet Morrison"] == {
        "applications": 1,
        "outstanding": 2,
        "stalled": 0,
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


# ---- stalled tracking ------------------------------------------------------

LONG_AGO = TODAY - timedelta(days=STALLED_DAYS)


def test_days_since_activity():
    assert days_since_activity(None, TODAY) is None
    assert days_since_activity(TODAY, TODAY) == 0
    assert days_since_activity(date(2025, 12, 18), TODAY) == 14


def test_stalled_at_threshold_but_not_before():
    docs = [doc("Pending")]
    assert is_stalled(app(documents=docs, last_activity=LONG_AGO), TODAY) is True
    just_inside = TODAY - timedelta(days=STALLED_DAYS - 1)
    assert is_stalled(app(documents=docs, last_activity=just_inside), TODAY) is False


def test_complete_application_is_never_stalled():
    docs = [doc("Approved"), doc("Not Required")]
    a = app(documents=docs, last_activity=date(2020, 1, 1))
    assert is_complete(a) is True
    assert is_stalled(a, TODAY) is False


def test_received_and_under_review_are_not_complete():
    for status in ("Received", "Under Review", "Pending", "Expired"):
        assert is_complete(app(documents=[doc("Approved"), doc(status)])) is False


def test_unknown_last_activity_is_not_stalled():
    assert is_stalled(app(documents=[doc("Pending")], last_activity=None), TODAY) is False


def test_stalled_adds_to_severity():
    docs = [doc("Pending")]
    fresh = application_summary(app(documents=docs), TODAY)
    stalled = application_summary(app(documents=docs, last_activity=LONG_AGO), TODAY)
    assert stalled["is_stalled"] is True
    assert stalled["severity_score"] == fresh["severity_score"] + STALLED_WEIGHT


def test_stalled_application_outranks_equal_fresh_one():
    docs = [doc("Pending")]
    fresh = app(documents=docs, application_id="A-1")
    stalled = app(documents=docs, application_id="A-2", last_activity=LONG_AGO)
    ranked = [a.application_id for a, _ in rank_applications([fresh, stalled], TODAY)]
    assert ranked == ["A-2", "A-1"]


def test_pipeline_counts_complete_stalled_in_progress():
    apps = [
        app(documents=[doc("Approved")]),
        app(documents=[doc("Pending")], last_activity=LONG_AGO),
        app(documents=[doc("Pending")]),
        app(documents=[doc("Under Review")]),
    ]
    s = pipeline_summary(apps, TODAY)
    assert s["applications_complete"] == 1
    assert s["applications_stalled"] == 1
    assert s["applications_in_progress"] == 2
    assert s["total_applications"] == 4


def test_activity_label():
    assert activity_label(None) == "No activity recorded"
    assert activity_label(0) == "Today"
    assert activity_label(1) == "1 day ago"
    assert activity_label(20) == "20 days ago"


# ---- dashboard -------------------------------------------------------------


def test_pipeline_counts_expiration_documents_across_applications():
    apps = [
        app(documents=[doc("Expired"), doc("Approved", expiration=date(2026, 1, 10))]),
        app(documents=[doc("Approved", expiration=date(2025, 12, 1)), doc("Pending")]),
    ]
    s = pipeline_summary(apps, TODAY)
    assert s["expired_documents"] == 2
    assert s["expiring_soon_documents"] == 1


def test_pipeline_by_processor_counts_stalled():
    apps = [
        app("Aisha Patel", [doc("Pending")], last_activity=LONG_AGO),
        app("Aisha Patel", [doc("Pending")]),
    ]
    assert pipeline_summary(apps, TODAY)["by_processor"]["Aisha Patel"]["stalled"] == 1


def test_ring_segments_percentages_and_offsets():
    from app.logic import ring_segments

    segments = ring_segments(complete=1, in_progress=1, stalled=2)
    assert [s["key"] for s in segments] == ["complete", "in-progress", "stalled"]
    assert [s["percent"] for s in segments] == [25.0, 25.0, 50.0]
    assert [s["start"] for s in segments] == [0.0, 25.0, 50.0]
    assert sum(s["percent"] for s in segments) == 100.0


def test_ring_segments_empty_pipeline_has_no_division_error():
    from app.logic import ring_segments

    assert all(s["percent"] == 0.0 for s in ring_segments(0, 0, 0))


def test_next_application_id_continues_the_year_sequence():
    ids = ["APP-2026-1001", "APP-2026-1060", "APP-2025-9999", "custom-id"]
    assert next_application_id(ids, date(2026, 5, 1)) == "APP-2026-1061"


def test_next_application_id_starts_at_1001_for_a_new_year_or_empty_db():
    assert next_application_id([], date(2026, 5, 1)) == "APP-2026-1001"
    assert next_application_id(["APP-2026-1060"], date(2027, 1, 2)) == "APP-2027-1001"


def test_standard_document_types_are_unique_and_include_priority_types():
    assert len(DOCUMENT_TYPES) == len(set(DOCUMENT_TYPES)) == 12
    assert PRIORITY_DOCUMENT_TYPES <= set(DOCUMENT_TYPES)


def test_top_applications_ranks_limits_and_skips_healthy():
    apps = [app(documents=[doc("Pending")], application_id=f"P{i:02d}") for i in range(12)]
    apps.append(app(documents=[doc("Expired")], application_id="WORST"))
    apps.append(app(documents=[doc("Approved")], application_id="CLEAN"))
    top = top_applications(apps, TODAY)
    ids = [a.application_id for a, _ in top]
    assert len(top) == 10
    assert ids[0] == "WORST"
    assert "CLEAN" not in ids
    assert ids[1:] == [f"P{i:02d}" for i in range(9)]


def test_top_applications_empty_when_nothing_is_wrong():
    assert top_applications([app(documents=[doc("Approved")])], TODAY) == []
    assert top_applications([], TODAY) == []


def test_attention_documents_lists_expired_and_expiring_most_overdue_first():
    a = app(
        application_id="A",
        documents=[
            doc("Approved", expiration=date(2026, 1, 20), doc_type="Debt Schedule"),
            doc("Approved", expiration=date(2025, 12, 25), doc_type="Lease Agreement"),
            doc("Pending", doc_type="SBA Form 912"),
            doc("Approved", expiration=date(2027, 1, 1), doc_type="SBA Form 1919"),
            doc("Not Required", expiration=date(2025, 1, 1), doc_type="Insurance Verification"),
        ],
    )
    rows = attention_documents([a], TODAY)
    assert [(r["document_type"], r["state"], r["days"]) for r in rows] == [
        ("Lease Agreement", "expired", -7),
        ("Debt Schedule", "expiring_soon", 19),
    ]
    assert rows[0]["label"] == "Expired 7 days ago"
    assert rows[0]["business_name"] == "Business A"
    assert rows[1]["label"] == "Expires in 19 days"


def test_attention_documents_expired_without_date_comes_after_dated_ones():
    a = app(
        documents=[
            doc("Expired", doc_type="Debt Schedule"),
            doc("Approved", expiration=date(2025, 12, 1), doc_type="Lease Agreement"),
        ]
    )
    rows = attention_documents([a], TODAY)
    assert [r["document_type"] for r in rows] == ["Lease Agreement", "Debt Schedule"]
    assert rows[1]["days"] is None
    assert rows[1]["label"] == "Marked expired"


def test_attention_documents_status_expired_with_future_date_is_labelled_marked_expired():
    a = app(documents=[doc("Expired", expiration=date(2029, 1, 1))])
    (row,) = attention_documents([a], TODAY)
    assert row["state"] == "expired"
    assert row["label"] == "Marked expired"


def test_attention_documents_expired_come_before_expiring_soon():
    a = app(
        documents=[
            doc("Approved", expiration=date(2026, 1, 2), doc_type="Debt Schedule"),
            doc("Expired", doc_type="Lease Agreement"),
        ]
    )
    rows = attention_documents([a], TODAY)
    assert [r["state"] for r in rows] == ["expired", "expiring_soon"]


def test_attention_documents_ties_break_by_application_id():
    d = date(2025, 12, 25)
    rows = attention_documents(
        [
            app(application_id="B", documents=[doc("Approved", expiration=d)]),
            app(application_id="A", documents=[doc("Approved", expiration=d)]),
        ],
        TODAY,
    )
    assert [r["application_id"] for r in rows] == ["A", "B"]
