from collections.abc import Generator
import logging
from sqlite3 import Connection as SQLite3Connection
import threading

from sqlalchemy import (
    MetaData,
    Table,
    and_,
    create_engine,
    event,
    func,
    inspect,
    literal,
    or_,
    select,
    text,
)
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
    """Apply schema migrations to existing databases safely, transactionally, and idempotently."""
    from app import models  # noqa: F401

    target_engine = bind if bind is not None else engine

    # 0. Ensure schema_migrations version table exists
    with target_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(100) PRIMARY KEY,
                    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    def is_migration_applied(version: str) -> bool:
        with target_engine.connect() as conn:
            result = conn.execute(
                text("SELECT 1 FROM schema_migrations WHERE version = :version"),
                {"version": version},
            ).scalar()
            return bool(result)

    insert_version_sql = (
        "INSERT OR IGNORE INTO schema_migrations (version) VALUES (:version)"
        if target_engine.dialect.name == "sqlite"
        else "INSERT INTO schema_migrations (version) VALUES (:version) ON CONFLICT (version) DO NOTHING"
    )

    inspector = inspect(target_engine)
    existing_tables = set(inspector.get_table_names())

    # 1. Migration 001: Add photo column to contacts table
    migration_001 = "001_add_photo_column"
    if not is_migration_applied(migration_001):
        if "contacts" in existing_tables:
            columns = {col["name"] for col in inspector.get_columns("contacts")}
            with target_engine.begin() as conn:
                if "photo" not in columns:
                    if target_engine.dialect.name == "postgresql":
                        conn.execute(text("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS photo TEXT"))
                    else:
                        conn.execute(text("ALTER TABLE contacts ADD COLUMN photo TEXT"))
                conn.execute(text(insert_version_sql), {"version": migration_001})
        else:
            logger.warning(
                "Prerequisite table 'contacts' missing; skipping migration %s without marking as applied.",
                migration_001,
            )

    # 2. Migration 002: Create addresses table and migrate legacy address data via SQLAlchemy Core
    migration_002 = "002_create_addresses_table_and_migrate_data"
    if not is_migration_applied(migration_002):
        if "contacts" in existing_tables:
            with target_engine.begin() as conn:
                if "addresses" not in existing_tables:
                    models.Address.__table__.create(bind=conn, checkfirst=True)
                    existing_tables.add("addresses")

                # Reflect contacts table to safely build dialect-agnostic Core expressions
                contacts_table = Table("contacts", MetaData(), autoload_with=conn)
                addresses_table = models.Address.__table__
                col_names = set(contacts_table.columns.keys())
                legacy_address_fields = {"address", "city", "state", "postal_code"}

                if legacy_address_fields.intersection(col_names):
                    street_col = contacts_table.c.address if "address" in col_names else literal(None)
                    city_col = contacts_table.c.city if "city" in col_names else literal(None)
                    state_col = contacts_table.c.state if "state" in col_names else literal(None)
                    zip_col = contacts_table.c.postal_code if "postal_code" in col_names else literal(None)

                    where_conditions = [
                        and_(contacts_table.c[field].is_not(None), func.trim(contacts_table.c[field]) != "")
                        for field in ("address", "city", "state", "postal_code")
                        if field in col_names
                    ]

                    if where_conditions:
                        not_already_migrated = ~select(1).where(
                            addresses_table.c.contact_id == contacts_table.c.id
                        ).exists()

                        select_stmt = select(
                            contacts_table.c.id.label("contact_id"),
                            literal(models.AddressType.HOME.value).label("type"),
                            street_col.label("street"),
                            city_col.label("city"),
                            state_col.label("state"),
                            zip_col.label("zip"),
                        ).where(
                            and_(
                                or_(*where_conditions),
                                not_already_migrated,
                            )
                        )

                        insert_stmt = addresses_table.insert().from_select(
                            [
                                addresses_table.c.contact_id,
                                addresses_table.c.type,
                                addresses_table.c.street,
                                addresses_table.c.city,
                                addresses_table.c.state,
                                addresses_table.c.zip,
                            ],
                            select_stmt,
                        )
                        conn.execute(insert_stmt)

                conn.execute(text(insert_version_sql), {"version": migration_002})
        else:
            logger.warning(
                "Prerequisite table 'contacts' missing; skipping migration %s without marking as applied.",
                migration_002,
            )


_init_db_lock = threading.Lock()


def init_db(bind=None) -> None:
    """Create tables and apply migrations. Called on startup; safe to call repeatedly across processes."""
    from app import models  # noqa: F401  (register models on Base.metadata)

    target_engine = bind if bind is not None else engine
    with _init_db_lock:
        try:
            Base.metadata.create_all(bind=target_engine, checkfirst=True)
        except (OperationalError, ProgrammingError) as exc:
            # Multi-process concurrency: verify all registered Base.metadata tables exist
            inspector = inspect(target_engine)
            existing_tables = set(inspector.get_table_names())
            expected_tables = set(Base.metadata.tables.keys())
            if expected_tables.issubset(existing_tables):
                logger.debug(
                    "All required tables %s were created concurrently by another process.",
                    expected_tables,
                )
            else:
                missing = expected_tables - existing_tables
                logger.error(
                    "Failed to create tables during startup. Missing required tables: %s. Error: %s",
                    missing,
                    exc,
                )
                raise
        run_migrations(bind=target_engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
