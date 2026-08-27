from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import inspect, text

from app.crud import get_contact
from app.database import Base, SessionLocal, engine, init_db, run_migrations


def _setup_legacy_schema():
    Base.metadata.drop_all(bind=engine)
    with engine.connect() as conn:
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
                INSERT INTO contacts (first_name, last_name, email, company)
                VALUES ('Ada', 'Lovelace', 'ada@example.com', 'Analytical Engines')
                """
            )
        )
        conn.commit()


def test_schema_upgrade_adds_photo_column_and_addresses_table():
    _setup_legacy_schema()

    # Verify column and table do NOT exist before migration
    inspector = inspect(engine)
    columns_before = [col["name"] for col in inspector.get_columns("contacts")]
    assert "photo" not in columns_before
    assert "addresses" not in inspector.get_table_names()

    # Run run_migrations directly (simulating deployments that call run_migrations)
    run_migrations(bind=engine)

    # Verify column and table exist after migration
    inspector_after = inspect(engine)
    columns_after = [col["name"] for col in inspector_after.get_columns("contacts")]
    assert "photo" in columns_after
    assert "addresses" in inspector_after.get_table_names()

    # Verify ORM can load the existing contact and photo is None
    with SessionLocal() as db:
        contact = get_contact(db, 1)
        assert contact is not None
        assert contact.email == "ada@example.com"
        assert contact.photo is None
        assert contact.addresses == []

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
