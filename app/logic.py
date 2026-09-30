from datetime import date, timedelta

OUTSTANDING_STATUSES = {"Pending", "Expired"}
EXPIRING_SOON_DAYS = 30

EXPIRED_WEIGHT = 10
EXPIRING_SOON_WEIGHT = 5
PENDING_WEIGHT = 3
PRIORITY_MULTIPLIER = 2
STALLED_DAYS = 14
STALLED_WEIGHT = 5
COMPLETE_STATUSES = {"Approved", "Not Required"}
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


BANK_STATEMENT_TYPE = "Bank Statements (90 day)"
TAX_RETURN_TYPES = {"Business Tax Returns (3yr)", "Personal Tax Returns (3yr)"}
BANK_STATEMENT_VALID_DAYS = 90
TAX_RETURN_VALID_YEARS = 3


def suggest_expiration(document_type: str, received_date: date | None) -> date | None:
    if received_date is None:
        return None
    if document_type == BANK_STATEMENT_TYPE:
        return received_date + timedelta(days=BANK_STATEMENT_VALID_DAYS)
    if document_type in TAX_RETURN_TYPES:
        try:
            return received_date.replace(year=received_date.year + TAX_RETURN_VALID_YEARS)
        except ValueError:
            return received_date.replace(
                year=received_date.year + TAX_RETURN_VALID_YEARS, day=28
            )
    return None


def document_state(document, today: date) -> str | None:
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
    }.get(document_state(document, today), 0)
    if document.document_type in PRIORITY_DOCUMENT_TYPES:
        weight *= PRIORITY_MULTIPLIER
    return weight


def days_since_activity(last_activity: date | None, today: date) -> int | None:
    if last_activity is None:
        return None
    return (today - last_activity).days


def is_complete(application) -> bool:
    return all(d.document_status in COMPLETE_STATUSES for d in application.documents)


def is_stalled(application, today: date) -> bool:
    days = days_since_activity(application.last_activity, today)
    return days is not None and days >= STALLED_DAYS and not is_complete(application)


def activity_label(days: int | None) -> str:
    if days is None:
        return "No activity recorded"
    if days <= 0:
        return "Today"
    return f"{days} day{'' if days == 1 else 's'} ago"


def application_summary(application, today: date) -> dict:
    outstanding = expired = expiring_soon = severity = 0
    for document in application.documents:
        if is_outstanding(document.document_status):
            outstanding += 1
        state = document_state(document, today)
        if state == "expired":
            expired += 1
        elif state == "expiring_soon":
            expiring_soon += 1
        severity += document_severity(document, today)
    stalled = is_stalled(application, today)
    if stalled:
        severity += STALLED_WEIGHT
    return {
        "outstanding_count": outstanding,
        "expired_count": expired,
        "expiring_soon_count": expiring_soon,
        "has_expiration_issue": (expired + expiring_soon) > 0,
        "severity_score": severity,
        "is_stalled": stalled,
        "is_complete": is_complete(application),
        "days_since_activity": days_since_activity(application.last_activity, today),
    }


def rank_applications(applications, today: date) -> list:
    """Return (application, summary) pairs, most severe first."""
    pairs = [(a, application_summary(a, today)) for a in applications]
    pairs.sort(key=lambda p: (-p[1]["severity_score"], p[0].application_id))
    return pairs


TOP_APPLICATIONS_LIMIT = 10
ATTENTION_DOCUMENTS_LIMIT = 15


def top_applications(applications, today: date, limit: int = TOP_APPLICATIONS_LIMIT) -> list:
    """Most severe applications first; applications with nothing wrong are left out."""
    ranked = [pair for pair in rank_applications(applications, today) if pair[1]["severity_score"] > 0]
    return ranked[:limit]


def attention_documents(applications, today: date) -> list[dict]:
    """Expired and expiring-soon documents across the pipeline, expired first, most overdue first."""
    rows = []
    for application in applications:
        for document in application.documents:
            state = document_state(document, today)
            if state not in ("expired", "expiring_soon"):
                continue
            days = days_until_expiration(document.expiration_date, today)
            label = document_expiration_text(state, days)
            rows.append(
                {
                    "application_id": application.application_id,
                    "business_name": application.business_name,
                    "assigned_processor": application.assigned_processor,
                    "document_type": document.document_type,
                    "state": state,
                    "expiration_date": document.expiration_date,
                    "days": days,
                    "label": label,
                }
            )
    rows.sort(
        key=lambda r: (
            r["state"] != "expired",
            r["days"] is None,
            r["days"] if r["days"] is not None else 0,
            r["application_id"],
            r["document_type"],
        )
    )
    return rows


def pipeline_summary(applications, today: date) -> dict:
    total_outstanding = 0
    with_outstanding = 0
    with_expiration_issue = 0
    complete = stalled = 0
    expired_documents = expiring_soon_documents = 0
    by_processor: dict[str, dict] = {}

    for application in applications:
        summary = application_summary(application, today)
        total_outstanding += summary["outstanding_count"]
        with_outstanding += summary["outstanding_count"] > 0
        with_expiration_issue += summary["has_expiration_issue"]
        complete += summary["is_complete"]
        stalled += summary["is_stalled"]
        expired_documents += summary["expired_count"]
        expiring_soon_documents += summary["expiring_soon_count"]
        bucket = by_processor.setdefault(
            application.assigned_processor,
            {"applications": 0, "outstanding": 0, "stalled": 0},
        )
        bucket["applications"] += 1
        bucket["outstanding"] += summary["outstanding_count"]
        bucket["stalled"] += summary["is_stalled"]

    return {
        "total_applications": len(applications),
        "total_outstanding": total_outstanding,
        "applications_with_outstanding": with_outstanding,
        "applications_with_expiration_issue": with_expiration_issue,
        "applications_complete": complete,
        "applications_stalled": stalled,
        "applications_in_progress": len(applications) - complete - stalled,
        "expired_documents": expired_documents,
        "expiring_soon_documents": expiring_soon_documents,
        "by_processor": by_processor,
    }


def ring_segments(complete: int, in_progress: int, stalled: int) -> list[dict]:
    """Segments for a 100-unit-circumference SVG ring: percent and start offset per slice."""
    total = complete + in_progress + stalled
    segments = []
    start = 0.0
    for key, label, count in (
        ("complete", "Complete", complete),
        ("in-progress", "In progress", in_progress),
        ("stalled", "Stalled", stalled),
    ):
        percent = count / total * 100 if total else 0.0
        segments.append(
            {"key": key, "label": label, "count": count, "percent": percent, "start": start}
        )
        start += percent
    return segments


DOCUMENT_STATUSES = [
    "Pending",
    "Received",
    "Under Review",
    "Approved",
    "Expired",
    "Not Required",
]


DOCUMENT_TYPES = [
    "Articles of Incorporation",
    "Bank Statements (90 day)",
    "Business Financial Statements",
    "Business Licenses & Permits",
    "Business Tax Returns (3yr)",
    "Debt Schedule",
    "Insurance Verification",
    "Lease Agreement",
    "Ownership Verification",
    "Personal Tax Returns (3yr)",
    "SBA Form 1919",
    "SBA Form 912",
]

DEFAULT_PROCESSORS = ["Aisha Patel", "Janet Morrison", "Ricardo Fuentes"]


def next_application_id(existing_ids, today: date) -> str:
    prefix = f"APP-{today.year}-"
    numbers = []
    for application_id in existing_ids:
        if application_id.startswith(prefix) and application_id[len(prefix):].isdigit():
            numbers.append(int(application_id[len(prefix):]))
    return f"{prefix}{max(numbers, default=1000) + 1}"


def expiration_label(days: int | None) -> str:
    if days is None:
        return ""
    if days < 0:
        n = abs(days)
        return f"Expired {n} day{'' if n == 1 else 's'} ago"
    if days == 0:
        return "Expires today"
    return f"Expires in {days} day{'' if days == 1 else 's'}"


def document_expiration_text(state: str | None, days: int | None) -> str:
    """Like expiration_label, but a document marked Expired is never described as still valid."""
    if state == "expired" and days is None:
        return "Marked expired"
    if state == "expired" and days >= 0:
        return "Marked expired, but date on file is in the future"
    return expiration_label(days)
