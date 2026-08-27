from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


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
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def run_migrations(bind=None) -> None:
    """Apply schema migrations to existing databases safely and idempotently."""
    target_engine = bind if bind is not None else engine
    inspector = inspect(target_engine)
    if "contacts" in inspector.get_table_names():
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
                err_msg = str(exc).lower()
                if "duplicate column" in err_msg or "already exists" in err_msg:
                    # Another concurrent worker already added the column
                    pass
                else:
                    raise


def init_db(bind=None) -> None:
    """Create tables and apply migrations. Called on startup; safe to call repeatedly."""
    from app import models  # noqa: F401  (register models on Base.metadata)

    target_engine = bind if bind is not None else engine
    Base.metadata.create_all(bind=target_engine)
    run_migrations(bind=target_engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
