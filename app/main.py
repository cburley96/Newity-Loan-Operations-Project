from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, selectinload

from app.database import Base, SessionLocal, engine, get_db
from app.logic import rank_applications
from app.models import Application
from app.seed import seed_if_empty

APP_DIR = Path(__file__).resolve().parent

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
        },
    )
