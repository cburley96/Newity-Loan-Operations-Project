from fastapi import FastAPI

from app.database import Base, SessionLocal, engine
from app.seed import seed_if_empty

app = FastAPI(title="NEWITY Document Checklist Tool")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
