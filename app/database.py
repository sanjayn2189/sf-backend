from collections.abc import Generator
import logging
from sqlite3 import Connection as SQLite3Connection
import threading

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings

logger = logging.getLogger("contacts.database")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _engine_kwargs(database_url: str) -> dict:
    if not database_url.startswith("sqlite"):
        return {}

    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in database_url or "mode=memory" in database_url:
        # A plain in-memory SQLite database lives and dies with its connection.
        # StaticPool keeps a single connection alive so every request — and every
        # thread FastAPI hands work to — sees the same data for the process's lifetime.
        kwargs["poolclass"] = StaticPool
    return kwargs


settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    **_engine_kwargs(settings.database_url),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Ensure SQLite foreign key constraints and ON DELETE CASCADE are strictly enforced."""
    if isinstance(dbapi_connection, SQLite3Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def run_migrations(bind=None) -> None:
    """Apply schema migrations to existing databases safely and idempotently."""
    from app import models  # noqa: F401

    target_engine = bind if bind is not None else engine
    inspector = inspect(target_engine)
    existing_tables = inspector.get_table_names()

    # 1. Create missing addresses table if contacts table already exists
    if "contacts" in existing_tables and "addresses" not in existing_tables:
        try:
            models.Address.__table__.create(bind=target_engine, checkfirst=True)
        except (OperationalError, ProgrammingError) as exc:
            # Re-inspect to confirm table exists (e.g. created by another concurrent worker process)
            if "addresses" in inspect(target_engine).get_table_names():
                logger.debug("Table 'addresses' was created concurrently by another process.")
            else:
                logger.error("Failed to create 'addresses' table during migration: %s", exc)
                raise

    # 2. Add photo column to contacts table if missing
    if "contacts" in existing_tables:
        columns = [col["name"] for col in inspector.get_columns("contacts")]
        if "photo" not in columns:
            try:
                with target_engine.connect() as conn:
                    if target_engine.dialect.name == "postgresql":
                        conn.execute(text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS photo TEXT"))
                    else:
                        conn.execute(text("ALTER TABLE contacts ADD COLUMN photo TEXT"))
                    conn.commit()
            except (OperationalError, ProgrammingError) as exc:
                # Re-inspect to confirm column was added by another concurrent worker process
                columns_after = [col["name"] for col in inspect(target_engine).get_columns("contacts")]
                if "photo" in columns_after:
                    logger.debug("Column 'photo' on 'contacts' was added concurrently by another process.")
                else:
                    logger.error("Failed to add 'photo' column to 'contacts' table: %s", exc)
                    raise


_init_db_lock = threading.Lock()


def init_db(bind=None) -> None:
    """Create tables and apply migrations. Called on startup; safe to call repeatedly."""
    from app import models  # noqa: F401  (register models on Base.metadata)

    target_engine = bind if bind is not None else engine
    with _init_db_lock:
        Base.metadata.create_all(bind=target_engine, checkfirst=True)
        run_migrations(bind=target_engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
