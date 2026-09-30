import math
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.database import Base, SessionLocal, engine, get_db
from app.importer import ImportFileError, import_csv
from app.logic import (
    DEFAULT_PROCESSORS,
    ATTENTION_DOCUMENTS_LIMIT,
    DOCUMENT_STATUSES,
    DOCUMENT_TYPES,
    activity_label,
    application_summary,
    attention_documents,
    days_until_expiration,
    document_severity,
    document_state,
    expiration_label,
    next_application_id,
    pipeline_summary,
    rank_applications,
    ring_segments,
    suggest_expiration,
    top_applications,
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
    as_of = os.environ.get("ASOF_DATE")
    return date.fromisoformat(as_of) if as_of else date.today()


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


@app.get("/dashboard")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    today: date = Depends(get_today),
):
    applications = db.query(Application).options(selectinload(Application.documents)).all()
    summary = pipeline_summary(applications, today)
    attention = attention_documents(applications, today)
    processors = sorted(
        summary["by_processor"].items(),
        key=lambda item: (-item[1]["outstanding"], item[0]),
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "summary": summary,
            "processors": processors,
            "top_applications": top_applications(applications, today),
            "attention_documents": attention[:ATTENTION_DOCUMENTS_LIMIT],
            "attention_total": len(attention),
            "segments": ring_segments(
                summary["applications_complete"],
                summary["applications_in_progress"],
                summary["applications_stalled"],
            ),
        },
    )


@app.get("/import")
def import_form(request: Request):
    return templates.TemplateResponse(request, "import.html", {"result": None, "error": None})


@app.post("/import")
async def import_upload(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    content = await file.read()
    try:
        result = import_csv(db, content)
    except ImportFileError as error:
        return templates.TemplateResponse(
            request, "import.html", {"result": None, "error": str(error)}, status_code=400
        )
    return templates.TemplateResponse(request, "import.html", {"result": result, "error": None})


APPLICATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _processor_choices(db: Session) -> list[str]:
    known = {p for (p,) in db.query(Application.assigned_processor).distinct()}
    return sorted(known | set(DEFAULT_PROCESSORS))


def _clean_application_fields(
    business_name: str,
    borrower_name: str,
    assigned_processor: str,
    loan_amount: str,
    application_date: str,
    processors: list[str],
) -> tuple[dict, dict]:
    errors: dict[str, str] = {}
    values: dict = {}

    values["business_name"] = business_name.strip()
    if not values["business_name"]:
        errors["business_name"] = "Business name is required."
    values["borrower_name"] = borrower_name.strip()
    if not values["borrower_name"]:
        errors["borrower_name"] = "Borrower name is required."

    values["assigned_processor"] = assigned_processor.strip()
    if values["assigned_processor"] not in processors:
        errors["assigned_processor"] = "Choose a processor from the list."

    raw_amount = loan_amount.replace(",", "").replace("$", "").strip()
    try:
        amount = float(raw_amount)
        if not math.isfinite(amount) or amount < 0:
            raise ValueError
        values["loan_amount"] = amount
    except ValueError:
        errors["loan_amount"] = (
            "Loan amount is required." if not raw_amount
            else "Enter the loan amount as a positive number, e.g. 250000."
        )

    raw_date = application_date.strip()
    if raw_date:
        try:
            values["application_date"] = date.fromisoformat(raw_date)
        except ValueError:
            errors["application_date"] = "Enter the application date as a valid date."
    else:
        values["application_date"] = None
    return values, errors


def _render_application_form(
    request: Request,
    db: Session,
    *,
    heading: str,
    action: str,
    cancel_url: str,
    id_editable: bool,
    form: dict,
    errors: dict,
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request,
        "application_form.html",
        {
            "heading": heading,
            "action": action,
            "cancel_url": cancel_url,
            "id_editable": id_editable,
            "form": form,
            "errors": errors,
            "processors": _processor_choices(db),
        },
        status_code=status_code,
    )


@app.get("/applications/new")
def new_application_form(
    request: Request,
    db: Session = Depends(get_db),
    today: date = Depends(get_today),
):
    ids = [i for (i,) in db.query(Application.application_id)]
    form = {
        "application_id": next_application_id(ids, today),
        "business_name": "",
        "borrower_name": "",
        "assigned_processor": "",
        "loan_amount": "",
        "application_date": today.isoformat(),
    }
    return _render_application_form(
        request, db, heading="New application", action="/applications", cancel_url="/",
        id_editable=True, form=form, errors={},
    )


@app.post("/applications")
def create_application(
    request: Request,
    application_id: str = Form(""),
    business_name: str = Form(""),
    borrower_name: str = Form(""),
    assigned_processor: str = Form(""),
    loan_amount: str = Form(""),
    application_date: str = Form(""),
    db: Session = Depends(get_db),
    today: date = Depends(get_today),
):
    values, errors = _clean_application_fields(
        business_name, borrower_name, assigned_processor, loan_amount,
        application_date, _processor_choices(db),
    )
    application_id = application_id.strip()
    if not application_id:
        errors["application_id"] = "Application ID is required."
    elif not APPLICATION_ID_PATTERN.match(application_id):
        errors["application_id"] = "Use only letters, numbers, dashes, dots and underscores."
    elif (
        db.query(Application)
        .filter(func.lower(Application.application_id) == application_id.lower())
        .first()
    ):
        errors["application_id"] = "An application with this ID already exists."

    if errors:
        form = {
            "application_id": application_id,
            "business_name": business_name,
            "borrower_name": borrower_name,
            "assigned_processor": assigned_processor,
            "loan_amount": loan_amount,
            "application_date": application_date,
        }
        return _render_application_form(
            request, db, heading="New application", action="/applications", cancel_url="/",
            id_editable=True, form=form, errors=errors, status_code=400,
        )

    application = Application(application_id=application_id, last_activity=today, **values)
    application.documents = [
        Document(document_type=t, document_status="Pending") for t in DOCUMENT_TYPES
    ]
    db.add(application)
    db.commit()
    return RedirectResponse(f"/applications/{application_id}", status_code=303)


def _get_application_or_404(db: Session, application_id: str) -> Application:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@app.get("/applications/{application_id}/edit")
def edit_application_form(
    request: Request,
    application_id: str,
    db: Session = Depends(get_db),
):
    application = _get_application_or_404(db, application_id)
    form = {
        "application_id": application.application_id,
        "business_name": application.business_name,
        "borrower_name": application.borrower_name,
        "assigned_processor": application.assigned_processor,
        "loan_amount": f"{application.loan_amount:.0f}"
        if application.loan_amount == int(application.loan_amount)
        else str(application.loan_amount),
        "application_date": application.application_date.isoformat()
        if application.application_date
        else "",
    }
    return _render_application_form(
        request, db, heading=f"Edit {application.application_id}",
        action=f"/applications/{application_id}/edit",
        cancel_url=f"/applications/{application_id}",
        id_editable=False, form=form, errors={},
    )


@app.post("/applications/{application_id}/edit")
def edit_application(
    request: Request,
    application_id: str,
    business_name: str = Form(""),
    borrower_name: str = Form(""),
    assigned_processor: str = Form(""),
    loan_amount: str = Form(""),
    application_date: str = Form(""),
    db: Session = Depends(get_db),
    today: date = Depends(get_today),
):
    application = _get_application_or_404(db, application_id)
    processors = _processor_choices(db)
    values, errors = _clean_application_fields(
        business_name, borrower_name, assigned_processor, loan_amount,
        application_date, processors,
    )
    if errors:
        form = {
            "application_id": application_id,
            "business_name": business_name,
            "borrower_name": borrower_name,
            "assigned_processor": assigned_processor,
            "loan_amount": loan_amount,
            "application_date": application_date,
        }
        return _render_application_form(
            request, db, heading=f"Edit {application_id}",
            action=f"/applications/{application_id}/edit",
            cancel_url=f"/applications/{application_id}",
            id_editable=False, form=form, errors=errors, status_code=400,
        )
    for field, value in values.items():
        setattr(application, field, value)
    application.last_activity = today
    db.commit()
    return RedirectResponse(f"/applications/{application_id}", status_code=303)


@app.post("/applications/{application_id}/documents")
def add_document(
    application_id: str,
    document_type: str = Form(""),
    db: Session = Depends(get_db),
    today: date = Depends(get_today),
):
    application = _get_application_or_404(db, application_id)
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=422, detail="Unknown document type")
    if document_type not in {d.document_type for d in application.documents}:
        application.documents.append(
            Document(document_type=document_type, document_status="Pending")
        )
        application.last_activity = today
        db.commit()
    return RedirectResponse(f"/applications/{application_id}", status_code=303)


@app.post("/applications/{application_id}/documents/{document_id}/delete")
def remove_document(
    application_id: str,
    document_id: int,
    db: Session = Depends(get_db),
    today: date = Depends(get_today),
):
    application = _get_application_or_404(db, application_id)
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.application_id == application_id)
        .first()
    )
    if document is not None:
        application.documents.remove(document)
        application.last_activity = today
        db.commit()
    return RedirectResponse(f"/applications/{application_id}", status_code=303)


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
    present_types = {d.document_type for d in application.documents}
    return templates.TemplateResponse(
        request,
        "application_detail.html",
        {
            "application": application,
            "summary": summary,
            "activity_text": activity_label(summary["days_since_activity"]),
            "documents": documents,
            "statuses": DOCUMENT_STATUSES,
            "addable_types": [t for t in DOCUMENT_TYPES if t not in present_types],
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
