from datetime import date

OUTSTANDING_STATUSES = {"Pending", "Expired"}
EXPIRING_SOON_DAYS = 30

EXPIRED_WEIGHT = 10
EXPIRING_SOON_WEIGHT = 5
PENDING_WEIGHT = 3
PRIORITY_MULTIPLIER = 2
PRIORITY_DOCUMENT_TYPES = {
    "Business Tax Returns (3yr)",
    "Personal Tax Returns (3yr)",
    "Bank Statements (90 day)",
}


def is_outstanding(status: str) -> bool:
    return status in OUTSTANDING_STATUSES


def days_until_expiration(expiration_date: date | None, today: date) -> int | None:
    if expiration_date is None:
        return None
    return (expiration_date - today).days


def _document_state(document, today: date) -> str | None:
    """Return 'expired', 'expiring_soon', 'pending', or None for a healthy document."""
    if document.document_status == "Not Required":
        return None
    days = days_until_expiration(document.expiration_date, today)
    if document.document_status == "Expired" or (days is not None and days < 0):
        return "expired"
    if days is not None and days <= EXPIRING_SOON_DAYS:
        return "expiring_soon"
    if document.document_status == "Pending":
        return "pending"
    return None


def document_severity(document, today: date) -> int:
    weight = {
        "expired": EXPIRED_WEIGHT,
        "expiring_soon": EXPIRING_SOON_WEIGHT,
        "pending": PENDING_WEIGHT,
    }.get(_document_state(document, today), 0)
    if document.document_type in PRIORITY_DOCUMENT_TYPES:
        weight *= PRIORITY_MULTIPLIER
    return weight


def application_summary(application, today: date) -> dict:
    outstanding = expired = expiring_soon = severity = 0
    for document in application.documents:
        if is_outstanding(document.document_status):
            outstanding += 1
        state = _document_state(document, today)
        if state == "expired":
            expired += 1
        elif state == "expiring_soon":
            expiring_soon += 1
        severity += document_severity(document, today)
    return {
        "outstanding_count": outstanding,
        "expired_count": expired,
        "expiring_soon_count": expiring_soon,
        "has_expiration_issue": (expired + expiring_soon) > 0,
        "severity_score": severity,
    }


def rank_applications(applications, today: date) -> list:
    """Return (application, summary) pairs, most severe first."""
    pairs = [(a, application_summary(a, today)) for a in applications]
    pairs.sort(key=lambda p: (-p[1]["severity_score"], p[0].application_id))
    return pairs


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
