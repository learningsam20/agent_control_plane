import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

settings = get_settings()

os.makedirs(os.path.dirname(settings.database_url.replace("sqlite:///", "")) or ".", exist_ok=True)


class Base(DeclarativeBase):
    pass


_connect_args = {"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    future=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  ensure models are registered

    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate() -> None:
    """Idempotent, additive-only migrations for tables created before a column
    existed. create_all() does not alter existing tables, so new nullable
    columns are added here explicitly."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "datahub_experiments" in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns("datahub_experiments")}
        if "name" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE datahub_experiments ADD COLUMN name VARCHAR(255) NOT NULL DEFAULT ''"))
