from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import get_settings


def get_engine():
    settings = get_settings()
    url = settings.database_url
    # Railway provides postgres:// but SQLAlchemy 2 needs postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(
        url,
        pool_pre_ping=True,
        # 5 connections held per worker, 5 overflow burst capacity.
        # With 4 gunicorn workers: max 40 simultaneous DB connections,
        # well within Railway Postgres limits.
        pool_size=5,
        max_overflow=5,
    )


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
