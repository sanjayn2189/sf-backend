from sqlalchemy import func, select

from app.database import SessionLocal, engine

BASE = "/api/v1/contacts"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"


def test_create_contact(client, payload):
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["email"] == "ada@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["created_at"] and body["updated_at"]
    assert len(body["addresses"]) == 1
    addr = body["addresses"][0]
    assert addr["type"] == "Home"
    assert addr["street"] == "1 Market St, Suite 400"
    assert addr["city"] == "San Francisco"
    assert addr["state"] == "CA"
    assert addr["zip"] == "94105"
    assert addr["contact_id"] == body["id"]


def test_create_requires_valid_email(client, payload):
    response = client.post(BASE, json={**payload, "email": "not-an-email"})
    assert response.status_code == 422


def test_create_requires_names(client, payload):
    response = client.post(BASE, json={**payload, "first_name": ""})
    assert response.status_code == 422


def test_duplicate_email_conflicts(client, payload):
    assert client.post(BASE, json=payload).status_code == 201
    response = client.post(BASE, json={**payload, "email": "ADA@example.com"})
    assert response.status_code == 409


def test_get_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.get(f"{BASE}/{contact_id}")
    assert response.status_code == 200
    assert response.json()["id"] == contact_id
    assert len(response.json()["addresses"]) == 1


def test_get_missing_contact_returns_404(client):
    assert client.get(f"{BASE}/9999").status_code == 404


def test_list_pagination_and_total(client, payload):
    for index in range(5):
        client.post(BASE, json={**payload, "email": f"user{index}@example.com"})

    response = client.get(BASE, params={"limit": 2, "offset": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2 and body["offset"] == 2


def test_list_search(client, payload):
    client.post(BASE, json=payload)
    client.post(
        BASE,
        json={**payload, "first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com", "company": "US Navy"},
    )

    hits = client.get(BASE, params={"search": "hopper"}).json()
    assert hits["total"] == 1
    assert hits["items"][0]["last_name"] == "Hopper"

    by_company = client.get(BASE, params={"search": "navy"}).json()
    assert by_company["total"] == 1

    misses = client.get(BASE, params={"search": "nobody"}).json()
    assert misses["total"] == 0


def test_list_sorting(client, payload):
    client.post(BASE, json={**payload, "last_name": "Zhang", "email": "z@example.com"})
    client.post(BASE, json={**payload, "last_name": "Adams", "email": "a@example.com"})

    names = [
        item["last_name"]
        for item in client.get(BASE, params={"sort_by": "last_name", "order": "asc"}).json()["items"]
    ]
    assert names == ["Adams", "Zhang"]


def test_list_rejects_bad_sort_field(client):
    assert client.get(BASE, params={"sort_by": "; DROP TABLE contacts"}).status_code == 422


def test_patch_updates_only_sent_fields(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "+1-000-000-0000"
    assert body["first_name"] == "Ada"
    assert body["company"] == "Analytical Engines"
    assert len(body["addresses"]) == 1


def test_patch_duplicate_email_conflicts(client, payload):
    first = client.post(BASE, json=payload).json()["id"]
    client.post(BASE, json={**payload, "email": "grace@example.com"})
    response = client.patch(f"{BASE}/{first}", json={"email": "grace@example.com"})
    assert response.status_code == 409


def test_patch_same_email_is_allowed(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"email": payload["email"]})
    assert response.status_code == 200


def test_put_replaces_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com", "addresses": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Grace Hopper"
    assert body["company"] is None  # omitted fields are cleared by PUT
    assert body["addresses"] == []  # omitted addresses cleared on PUT replacement


def test_put_requires_addresses(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    )
    assert response.status_code == 422


def test_put_missing_contact_returns_404(client):
    response = client.put(
        f"{BASE}/9999",
        json={"first_name": "A", "last_name": "B", "email": "ab@example.com", "addresses": []},
    )
    assert response.status_code == 404


def test_delete_contact_cascades_addresses(client, payload):
    from app.models import Address

    contact_id = client.post(BASE, json=payload).json()["id"]

    # Verify address exists in DB
    with SessionLocal() as db:
        addr_count = db.execute(select(func.count()).select_from(Address).where(Address.contact_id == contact_id)).scalar_one()
        assert addr_count == 1

    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    assert client.get(f"{BASE}/{contact_id}").status_code == 404

    # Verify address was cascade deleted
    with SessionLocal() as db:
        addr_count_after = db.execute(select(func.count()).select_from(Address).where(Address.contact_id == contact_id)).scalar_one()
        assert addr_count_after == 0


def test_root_lists_entrypoints(client):
    body = client.get("/").json()
    assert body["contacts"] == BASE


def test_contact_photo_create_and_retrieve(client, payload):
    sample_base64_photo = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    response = client.post(BASE, json={**payload, "photo": sample_base64_photo})
    assert response.status_code == 201
    created = response.json()
    assert created["photo"] == sample_base64_photo

    contact_id = created["id"]
    get_response = client.get(f"{BASE}/{contact_id}")
    assert get_response.status_code == 200
    assert get_response.json()["photo"] == sample_base64_photo


def test_contact_photo_put_and_patch(client, payload):
    sample_photo = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    updated_photo = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
    contact_id = client.post(BASE, json={**payload, "photo": sample_photo}).json()["id"]

    # Test PATCH update photo
    patch_res = client.patch(f"{BASE}/{contact_id}", json={"photo": updated_photo})
    assert patch_res.status_code == 200
    assert patch_res.json()["photo"] == updated_photo

    # Test PUT replacement with photo preserved
    put_res = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com", "photo": updated_photo, "addresses": []},
    )
    assert put_res.status_code == 200
    assert put_res.json()["photo"] == updated_photo

    # Test PUT without photo clears photo to None
    put_clear = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com", "addresses": []},
    )
    assert put_clear.status_code == 200
    assert put_clear.json()["photo"] is None



def test_contact_photo_rejects_malformed_data_urls(client, payload):
    # Missing data: prefix
    assert client.post(BASE, json={**payload, "photo": "image/png;base64,abc="}).status_code == 422

    # Unsupported MIME type
    assert client.post(
        BASE,
        json={**payload, "photo": "data:application/pdf;base64,JVBERi0xLg=="},
    ).status_code == 422

    # Malformed base64
    assert client.post(
        BASE,
        json={**payload, "photo": "data:image/png;base64,not_valid_base64!!!"},
    ).status_code == 422


def test_contact_photo_rejects_malformed_on_patch_and_put(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]

    # PATCH invalid
    assert client.patch(f"{BASE}/{contact_id}", json={"photo": "invalid-url"}).status_code == 422

    # PUT invalid
    assert client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com", "photo": "invalid-url"},
    ).status_code == 422


def test_multiple_typed_addresses_crud(client, payload):
    addresses = [
        {
            "type": "Home",
            "street": "123 Main St",
            "city": "San Francisco",
            "state": "CA",
            "zip": "94105",
        },
        {
            "type": "Work",
            "street": "500 Howard St",
            "city": "San Francisco",
            "state": "CA",
            "zip": "94105",
        },
        {
            "type": "Other",
            "street": "P.O. Box 777",
            "city": "Oakland",
            "state": "CA",
            "zip": "94601",
        },
    ]
    res = client.post(BASE, json={**payload, "addresses": addresses})
    assert res.status_code == 201
    created = res.json()
    assert len(created["addresses"]) == 3
    types = [a["type"] for a in created["addresses"]]
    assert types == ["Home", "Work", "Other"]

    contact_id = created["id"]

    # Replace via PUT with a single address
    put_addresses = [
        {
            "type": "Work",
            "street": "100 California St",
            "city": "San Francisco",
            "state": "CA",
            "zip": "94111",
        }
    ]
    put_res = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com", "addresses": put_addresses},
    )
    assert put_res.status_code == 200
    assert len(put_res.json()["addresses"]) == 1
    assert put_res.json()["addresses"][0]["street"] == "100 California St"

    # Reject invalid address type
    invalid_res = client.post(
        BASE,
        json={**payload, "email": "unique@example.com", "addresses": [{"type": "InvalidType", "street": "Test"}]},
    )
    assert invalid_res.status_code == 422


def test_sqlite_foreign_keys_and_cascade_on_raw_delete(client, payload):
    from sqlalchemy import text
    from app.models import Address

    contact_id = client.post(BASE, json=payload).json()["id"]

    # Verify foreign_keys pragma is enabled on the SQLite connection
    with engine.connect() as conn:
        fk_status = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert fk_status == 1

        # Direct SQL delete on contacts table triggers DB-level ON DELETE CASCADE
        conn.execute(text("DELETE FROM contacts WHERE id = :id"), {"id": contact_id})
        conn.commit()

        # Check that Address was cascade deleted by SQLite foreign key constraint
        addr_count = conn.execute(
            select(func.count()).select_from(Address).where(Address.contact_id == contact_id)
        ).scalar_one()
        assert addr_count == 0


def test_db_level_address_type_constraint(client, payload):
    import pytest
    from sqlalchemy.exc import IntegrityError, StatementError
    from app.models import Address

    contact_id = client.post(BASE, json=payload).json()["id"]

    # Direct DB write with an invalid type string violates CHECK constraint / Enum
    with pytest.raises((IntegrityError, StatementError)):
        with SessionLocal() as db:
            invalid_addr = Address(contact_id=contact_id, type="InvalidType", street="123 Test")
            db.add(invalid_addr)
            db.commit()

