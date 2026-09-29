from datetime import date

OUTSTANDING_STATUSES = {"Pending", "Expired"}
EXPIRING_SOON_DAYS = 30


def is_outstanding(status: str) -> bool:
    return status in OUTSTANDING_STATUSES


def days_until_expiration(expiration_date: date | None, today: date) -> int | None:
    if expiration_date is None:
        return None
    return (expiration_date - today).days


def application_summary(application, today: date) -> dict:
    outstanding = expired = expiring_soon = 0
    for document in application.documents:
        if is_outstanding(document.document_status):
            outstanding += 1
        if document.document_status == "Not Required":
            continue
        days = days_until_expiration(document.expiration_date, today)
        if days is None:
            continue
        if days < 0:
            expired += 1
        elif days <= EXPIRING_SOON_DAYS:
            expiring_soon += 1
    return {
        "outstanding_count": outstanding,
        "expired_count": expired,
        "expiring_soon_count": expiring_soon,
        "has_expiration_issue": (expired + expiring_soon) > 0,
    }


def pipeline_summary(applications, today: date) -> dict:
    total_outstanding = 0
    with_outstanding = 0
    with_expiration_issue = 0
    by_processor: dict[str, dict] = {}

    for application in applications:
        summary = application_summary(application, today)
        total_outstanding += summary["outstanding_count"]
        with_outstanding += summary["outstanding_count"] > 0
        with_expiration_issue += summary["has_expiration_issue"]
        bucket = by_processor.setdefault(
            application.assigned_processor, {"applications": 0, "outstanding": 0}
        )
        bucket["applications"] += 1
        bucket["outstanding"] += summary["outstanding_count"]

    return {
        "total_applications": len(applications),
        "total_outstanding": total_outstanding,
        "applications_with_outstanding": with_outstanding,
        "applications_with_expiration_issue": with_expiration_issue,
        "by_processor": by_processor,
    }
