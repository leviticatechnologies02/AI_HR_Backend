# core/database.py

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlmodel import SQLModel, Session
from core.config import settings


DATABASE_URL = settings.DATABASE_URL


engine = create_engine(
    DATABASE_URL,
    echo=settings.SQL_ECHO,
    pool_pre_ping=True,
)


class Base(DeclarativeBase):
     metadata = SQLModel.metadata


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    class_=Session,   # ✅ SQLAlchemy Session
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
