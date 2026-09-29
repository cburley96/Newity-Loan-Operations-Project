import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Application, Document

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = BASE_DIR / "data" / "document_checklist.csv"


def _parse_date(value: str):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%m/%d/%Y").date()


def seed_if_empty(db: Session) -> None:
    if db.query(Application).first() is not None:
        return

    applications: dict[str, Application] = {}

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            app_id = row["application_id"]
            if app_id not in applications:
                application = Application(
                    application_id=app_id,
                    business_name=row["business_name"],
                    borrower_name=row["borrower_name"],
                    loan_amount=float(row["loan_amount"]),
                    application_date=_parse_date(row["application_date"]),
                    assigned_processor=row["assigned_processor"],
                )
                applications[app_id] = application
                db.add(application)

            document = Document(
                application_id=app_id,
                document_type=row["document_type"],
                document_status=row["document_status"],
                date_received=_parse_date(row["date_received"]),
                expiration_date=_parse_date(row["expiration_date"]),
                notes=row["notes"] or None,
            )
            db.add(document)

    db.commit()
