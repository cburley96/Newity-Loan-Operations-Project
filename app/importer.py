import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.logic import DOCUMENT_STATUSES
from app.models import Application, Document
from app.seed import derive_last_activity

REQUIRED_COLUMNS = [
    "application_id",
    "business_name",
    "borrower_name",
    "loan_amount",
    "application_date",
    "assigned_processor",
    "document_type",
    "document_status",
    "date_received",
    "expiration_date",
    "notes",
]


class ImportFileError(Exception):
    """The file as a whole cannot be imported."""


@dataclass
class ImportResult:
    total_rows: int = 0
    new_applications: int = 0
    added_documents: int = 0
    duplicates: list[dict] = field(default_factory=list)
    invalid: list[dict] = field(default_factory=list)


def _parse_date(value: str, label: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError:
        raise ValueError(f"{label} '{value}' is not a valid date (use M/D/YYYY)")


def _validate_row(row: dict) -> dict:
    """Return the cleaned row, or raise ValueError with a plain-English reason."""
    for column in ("application_id", "business_name", "borrower_name",
                   "assigned_processor", "document_type"):
        if not row[column]:
            raise ValueError(f"{column} is missing")
    if row["document_status"] not in DOCUMENT_STATUSES:
        raise ValueError(f"Unknown document_status '{row['document_status']}'")
    try:
        loan_amount = float(row["loan_amount"].replace(",", "").replace("$", ""))
    except ValueError:
        raise ValueError(f"loan_amount '{row['loan_amount']}' is not a number")
    if loan_amount < 0:
        raise ValueError("loan_amount cannot be negative")
    return {
        **row,
        "loan_amount": loan_amount,
        "application_date": _parse_date(row["application_date"], "application_date"),
        "date_received": _parse_date(row["date_received"], "date_received"),
        "expiration_date": _parse_date(row["expiration_date"], "expiration_date"),
        "notes": row["notes"] or None,
    }


def import_csv(db: Session, content: bytes) -> ImportResult:
    """Add new applications/documents from CSV bytes. A row whose
    (application_id, document_type) already exists, in the database or earlier
    in the file, is skipped as a duplicate. Invalid rows are skipped and listed."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportFileError("The file is not a readable CSV (expected UTF-8 text).")

    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise ImportFileError("Missing column(s): " + ", ".join(missing))

    seen = {
        (application_id, document_type)
        for application_id, document_type in db.query(
            Document.application_id, Document.document_type
        )
    }
    known_applications = {a.application_id: a for a in db.query(Application)}
    created: dict[str, Application] = {}
    result = ImportResult()

    for row_number, raw in enumerate(reader, start=2):
        row = {c: (raw.get(c) or "").strip() for c in REQUIRED_COLUMNS}
        if not any(row.values()):
            continue
        result.total_rows += 1
        try:
            row = _validate_row(row)
        except ValueError as error:
            result.invalid.append({"row": row_number, "application_id": row["application_id"],
                                   "reason": str(error)})
            continue

        key = (row["application_id"], row["document_type"])
        if key in seen:
            result.duplicates.append({"row": row_number, "application_id": key[0],
                                      "document_type": key[1]})
            continue
        seen.add(key)

        if row["application_id"] not in known_applications:
            application = Application(
                application_id=row["application_id"],
                business_name=row["business_name"],
                borrower_name=row["borrower_name"],
                loan_amount=row["loan_amount"],
                application_date=row["application_date"],
                assigned_processor=row["assigned_processor"],
            )
            db.add(application)
            known_applications[row["application_id"]] = application
            created[row["application_id"]] = application
            result.new_applications += 1

        db.add(Document(
            application_id=row["application_id"],
            document_type=row["document_type"],
            document_status=row["document_status"],
            date_received=row["date_received"],
            expiration_date=row["expiration_date"],
            notes=row["notes"],
        ))
        result.added_documents += 1

    db.flush()
    for application in created.values():
        db.refresh(application)
        application.last_activity = derive_last_activity(application)
    db.commit()
    return result
