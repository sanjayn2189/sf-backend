from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import inspect, text

from app.crud import get_contact
from app.database import Base, SessionLocal, engine, init_db, run_migrations
from app.models import AddressType


def _setup_legacy_schema():
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS schema_migrations"))
        conn.execute(text("DROP TABLE IF EXISTS addresses"))
        conn.execute(text("DROP TABLE IF EXISTS contacts"))
        conn.execute(
            text(
                """
                CREATE TABLE contacts (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    first_name VARCHAR(100) NOT NULL,
                    last_name VARCHAR(100) NOT NULL,
                    email VARCHAR(320) NOT NULL UNIQUE,
                    phone VARCHAR(40),
                    company VARCHAR(200),
                    job_title VARCHAR(200),
                    address VARCHAR(300),
                    city VARCHAR(120),
                    state VARCHAR(120),
                    postal_code VARCHAR(20),
                    country VARCHAR(120),
                    notes TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO contacts (first_name, last_name, email, company, address, city, state, postal_code)
                VALUES ('Ada', 'Lovelace', 'ada@example.com', 'Analytical Engines', '1 Market St, Suite 400', 'San Francisco', 'CA', '94105')
                """
            )
        )


def test_schema_upgrade_adds_photo_column_and_preserves_legacy_addresses():
    _setup_legacy_schema()

    # Verify column, table, and migration version do NOT exist before migration
    inspector = inspect(engine)
    columns_before = [col["name"] for col in inspector.get_columns("contacts")]
    assert "photo" not in columns_before
    assert "addresses" not in inspector.get_table_names()

    # Run run_migrations directly (simulating deployments upgrading via run_migrations)
    run_migrations(bind=engine)

    # Verify column and table exist after migration
    inspector_after = inspect(engine)
    columns_after = [col["name"] for col in inspector_after.get_columns("contacts")]
    assert "photo" in columns_after
    assert "addresses" in inspector_after.get_table_names()
    assert "schema_migrations" in inspector_after.get_table_names()

    # Verify migration table tracked versions
    with engine.connect() as conn:
        versions = conn.execute(text("SELECT version FROM schema_migrations ORDER BY version")).scalars().all()
        assert "001_add_photo_column" in versions
        assert "002_create_addresses_table_and_migrate_data" in versions

    # Verify ORM can load the existing contact with preserved address data
    with SessionLocal() as db:
        contact = get_contact(db, 1)
        assert contact is not None
        assert contact.email == "ada@example.com"
        assert contact.photo is None
        assert len(contact.addresses) == 1
        addr = contact.addresses[0]
        assert addr.street == "1 Market St, Suite 400"
        assert addr.city == "San Francisco"
        assert addr.state == "CA"
        assert addr.zip == "94105"
        assert addr.type == AddressType.HOME

        # Verify we can update photo on existing record with valid base64 data URL
        valid_photo = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        contact.photo = valid_photo
        db.commit()
        db.refresh(contact)
        assert contact.photo == valid_photo


def test_concurrent_migrations_do_not_fail():
    _setup_legacy_schema()

    # Run init_db across 10 concurrent worker threads simultaneously
    def run_worker():
        init_db(bind=engine)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(run_worker) for _ in range(10)]
        for future in futures:
            future.result()  # Will raise if any thread encountered an unhandled exception

    inspector = inspect(engine)
    columns = [col["name"] for col in inspector.get_columns("contacts")]
    assert "photo" in columns
    assert "addresses" in inspector.get_table_names()
    assert "schema_migrations" in inspector.get_table_names()

    with SessionLocal() as db:
        contact = get_contact(db, 1)
        assert contact is not None
        assert len(contact.addresses) == 1
        assert contact.addresses[0].street == "1 Market St, Suite 400"


def test_migration_skips_recording_version_when_prerequisites_missing():
    # Drop everything so contacts table does not exist
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS schema_migrations"))
        conn.execute(text("DROP TABLE IF EXISTS addresses"))
        conn.execute(text("DROP TABLE IF EXISTS contacts"))

    # Running migrations on empty DB without contacts table should skip without recording versions
    run_migrations(bind=engine)

    with engine.connect() as conn:
        versions = conn.execute(text("SELECT version FROM schema_migrations")).scalars().all()
        assert len(versions) == 0

    # Now create contacts table (e.g. legacy schema setup)
    _setup_legacy_schema()

    # Running migrations should now apply and record versions
    run_migrations(bind=engine)

    with engine.connect() as conn:
        versions = conn.execute(text("SELECT version FROM schema_migrations ORDER BY version")).scalars().all()
        assert "001_add_photo_column" in versions
        assert "002_create_addresses_table_and_migrate_data" in versions
