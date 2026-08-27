from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.crud import get_contact
from app.database import Base, engine, run_migrations


def test_schema_upgrade_adds_photo_column():
    # 1. Drop all tables to start clean
    Base.metadata.drop_all(bind=engine)

    # 2. Create contacts table with PREVIOUS schema (without photo column)
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
                INSERT INTO contacts (first_name, last_name, email, company)
                VALUES ('Ada', 'Lovelace', 'ada@example.com', 'Analytical Engines')
                """
            )
        )
        conn.commit()

    # Verify column does NOT exist before migration
    inspector = inspect(engine)
    columns_before = [col["name"] for col in inspector.get_columns("contacts")]
    assert "photo" not in columns_before

    # 3. Run migration
    run_migrations(bind=engine)

    # 4. Verify column exists after migration
    inspector_after = inspect(engine)
    columns_after = [col["name"] for col in inspector_after.get_columns("contacts")]
    assert "photo" in columns_after

    # 5. Verify ORM can load the existing contact and photo is None
    with Session(engine) as db:
        contact = get_contact(db, 1)
        assert contact is not None
        assert contact.email == "ada@example.com"
        assert contact.photo is None

        # Verify we can update photo on existing record
        contact.photo = "data:image/png;base64,upgradedphoto"
        db.commit()
        db.refresh(contact)
        assert contact.photo == "data:image/png;base64,upgradedphoto"
