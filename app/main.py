from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from app.database import Base, SessionLocal, engine, get_db
from app.logic import (
    DOCUMENT_STATUSES,
    activity_label,
    application_summary,
    days_until_expiration,
    document_severity,
    document_state,
    expiration_label,
    rank_applications,
    suggest_expiration,
)
from app.models import Application, Document
from app.seed import seed_if_empty, upgrade_schema

APP_DIR = Path(__file__).resolve().parent

STATE_LABELS = {
    "expired": "Expired",
    "expiring_soon": "Expiring soon",
    "pending": "Pending",
}

app = FastAPI(title="NEWITY Document Checklist Tool")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


def get_today() -> date:
    return date.today()


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        upgrade_schema(db)
        seed_if_empty(db)
    finally:
        db.close()


@app.get("/")
def applications_list(
    request: Request,
    processor: str = "",
    db: Session = Depends(get_db),
    today: date = Depends(get_today),
):
    query = db.query(Application).options(selectinload(Application.documents))
    if processor:
        query = query.filter(Application.assigned_processor == processor)
    ranked = rank_applications(query.all(), today)
    processors = [
        p for (p,) in db.query(Application.assigned_processor).distinct().order_by(
            Application.assigned_processor
        )
    ]
    return templates.TemplateResponse(
        request,
        "applications_list.html",
        {
            "rows": ranked,
            "processors": processors,
            "selected_processor": processor,
            "query_string": _list_link(processor),
        },
    )


class DocumentUpdate(BaseModel):
    document_status: str | None = None
    date_received: date | None = None
    expiration_date: date | None = None
    notes: str | None = None


def document_view(document: Document, today: date) -> dict:
    state = document_state(document, today)
    days = days_until_expiration(document.expiration_date, today)
    return {
        "id": document.id,
        "document_type": document.document_type,
        "document_status": document.document_status,
        "date_received": document.date_received.isoformat() if document.date_received else "",
        "expiration_date": document.expiration_date.isoformat() if document.expiration_date else "",
        "notes": document.notes or "",
        "state": state or "",
        "state_label": STATE_LABELS.get(state, ""),
        "expiration_text": expiration_label(days),
        "severity": document_severity(document, today),
    }


def _list_link(processor: str) -> str:
    return "?" + urlencode({"processor": processor}) if processor else ""


@app.get("/applications/{application_id}")
def application_detail(
    request: Request,
    application_id: str,
    processor: str = "",
    db: Session = Depends(get_db),
    today: date = Depends(get_today),
):
    application = (
        db.query(Application)
        .options(selectinload(Application.documents))
        .filter(Application.application_id == application_id)
        .first()
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    query = db.query(Application).options(selectinload(Application.documents))
    if processor:
        query = query.filter(Application.assigned_processor == processor)
    ids = [a.application_id for a, _ in rank_applications(query.all(), today)]
    previous_id = next_id = None
    if application_id in ids:
        index = ids.index(application_id)
        previous_id = ids[index - 1] if index > 0 else None
        next_id = ids[index + 1] if index < len(ids) - 1 else None

    documents = sorted(
        (document_view(d, today) for d in application.documents),
        key=lambda d: (-d["severity"], d["document_type"]),
    )
    summary = application_summary(application, today)
    return templates.TemplateResponse(
        request,
        "application_detail.html",
        {
            "application": application,
            "summary": summary,
            "activity_text": activity_label(summary["days_since_activity"]),
            "documents": documents,
            "statuses": DOCUMENT_STATUSES,
            "query_string": _list_link(processor),
            "previous_id": previous_id,
            "next_id": next_id,
        },
    )


@app.post("/applications/{application_id}/documents/{document_id}")
def update_document(
    application_id: str,
    document_id: int,
    update: DocumentUpdate,
    db: Session = Depends(get_db),
    today: date = Depends(get_today),
):
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.application_id == application_id)
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    fields = update.model_fields_set
    if "document_status" in fields:
        if update.document_status not in DOCUMENT_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown document status")
        newly_received = (
            update.document_status == "Received" and document.document_status != "Received"
        )
        document.document_status = update.document_status
    else:
        newly_received = False

    if "date_received" in fields:
        document.date_received = update.date_received
    if "expiration_date" in fields:
        document.expiration_date = update.expiration_date
    if "notes" in fields:
        document.notes = (update.notes or "").strip() or None

    if newly_received:
        if document.date_received is None and "date_received" not in fields:
            document.date_received = today
        if document.expiration_date is None and "expiration_date" not in fields:
            document.expiration_date = suggest_expiration(
                document.document_type, document.date_received
            )

    document.application.last_activity = today
    db.commit()
    db.refresh(document)
    application = (
        db.query(Application)
        .options(selectinload(Application.documents))
        .filter(Application.application_id == application_id)
        .one()
    )
    return {
        "document": document_view(document, today),
        "summary": application_summary(application, today),
        "last_activity": application.last_activity.isoformat(),
        "activity_text": activity_label(0),
    }
