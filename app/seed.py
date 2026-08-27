from app.crud import count_contacts, create_contact
from app.database import SessionLocal
from app.schemas import AddressCreate, AddressType, ContactCreate

SAMPLE_CONTACTS = [
    ContactCreate(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        phone="+1-415-555-0101",
        company="Analytical Engines",
        job_title="Mathematician",
        notes="First programmer.",
        addresses=[
            AddressCreate(
                type=AddressType.WORK,
                street="1 Market St, Suite 400",
                city="San Francisco",
                state="CA",
                zip="94105",
            ),
            AddressCreate(
                type=AddressType.HOME,
                street="10 Ockham Park",
                city="Surrey",
                state="England",
                zip="GU23 6NP",
            ),
        ],
    ),
    ContactCreate(
        first_name="Grace",
        last_name="Hopper",
        email="grace@example.com",
        phone="+1-415-555-0102",
        company="US Navy",
        job_title="Rear Admiral",
        addresses=[
            AddressCreate(
                type=AddressType.WORK,
                street="Pentagon, Room 3E",
                city="Arlington",
                state="VA",
                zip="20301",
            )
        ],
    ),
    ContactCreate(
        first_name="Alan",
        last_name="Turing",
        email="alan@example.com",
        phone="+44-20-5555-0103",
        company="Bletchley Park",
        job_title="Cryptanalyst",
        addresses=[
            AddressCreate(
                type=AddressType.OTHER,
                street="Hut 8, Bletchley Park",
                city="Milton Keynes",
                state="Buckinghamshire",
                zip="MK3 6EB",
            )
        ],
    ),
]


def seed_if_empty() -> int:
    """Insert sample contacts when the database has none. Returns rows added."""
    with SessionLocal() as db:
        if count_contacts(db) > 0:
            return 0
        for contact in SAMPLE_CONTACTS:
            create_contact(db, contact)
        return len(SAMPLE_CONTACTS)
