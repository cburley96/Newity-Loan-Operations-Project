from sqlalchemy import Column, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Application(Base):
    __tablename__ = "applications"

    application_id = Column(String, primary_key=True)
    business_name = Column(String, nullable=False)
    borrower_name = Column(String, nullable=False)
    loan_amount = Column(Float, nullable=False)
    application_date = Column(Date, nullable=True)
    assigned_processor = Column(String, nullable=False)

    documents = relationship(
        "Document", back_populates="application", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(String, ForeignKey("applications.application_id"), nullable=False)
    document_type = Column(String, nullable=False)
    document_status = Column(String, nullable=False)
    date_received = Column(Date, nullable=True)
    expiration_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)

    application = relationship("Application", back_populates="documents")
