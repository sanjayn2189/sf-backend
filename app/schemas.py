import base64
from enum import Enum
import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from app.models import AddressType



class AddressBase(BaseModel):
    """Fields common to address creation, replacement, and response."""

    type: AddressType = Field(
        default=AddressType.HOME,
        description="Type/category of the address.",
        examples=["Home"],
    )
    street: str | None = Field(
        default=None,
        max_length=300,
        description="Street address, including unit or suite.",
        examples=["1 Market St, Suite 400"],
    )
    city: str | None = Field(
        default=None,
        max_length=120,
        description="City or locality.",
        examples=["San Francisco"],
    )
    state: str | None = Field(
        default=None,
        max_length=120,
        description="State, province, or region.",
        examples=["CA"],
    )
    zip: str | None = Field(
        default=None,
        max_length=20,
        description="Postal or ZIP code.",
        examples=["94105"],
    )


class AddressCreate(AddressBase):
    """Address payload on contact creation/update."""


class AddressRead(AddressBase):
    """Stored address with server-assigned id and foreign key."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Server-assigned identifier for this address.", examples=[1])
    contact_id: int = Field(description="Associated contact identifier.", examples=[1])


PHOTO_DATA_URL_PATTERN = re.compile(
    r"^data:(image\/(?:jpeg|png|gif|webp));base64,([A-Za-z0-9+/=]+)$",
    re.IGNORECASE,
)
MAX_PHOTO_LENGTH = 3_000_000
MAX_DECODED_BYTES = 2 * 1024 * 1024


def _validate_photo(value: str | None) -> str | None:
    if value is None:
        return None
    val = value.strip()
    if not val:
        return None
    if len(val) > MAX_PHOTO_LENGTH:
        raise ValueError(f"Photo data URL must not exceed {MAX_PHOTO_LENGTH} characters.")
    match = PHOTO_DATA_URL_PATTERN.match(val)
    if not match:
        raise ValueError(
            "Photo must be a valid base64 data URL with a supported image MIME type (jpeg, png, gif, webp)."
        )
    encoded_data = match.group(2)
    try:
        decoded = base64.b64decode(encoded_data, validate=True)
    except Exception as exc:
        raise ValueError("Photo contains invalid base64 encoding.") from exc
    if len(decoded) > MAX_DECODED_BYTES:
        raise ValueError(f"Decoded photo image size must not exceed {MAX_DECODED_BYTES} bytes.")
    return val


class ContactBase(BaseModel):
    """Fields shared by every contact request and response."""

    first_name: str = Field(
        min_length=1,
        max_length=100,
        description="Given name. Required, must not be blank.",
        examples=["Ada"],
    )
    last_name: str = Field(
        min_length=1,
        max_length=100,
        description="Family name. Required, must not be blank.",
        examples=["Lovelace"],
    )
    email: EmailStr = Field(
        max_length=320,
        description=(
            "Primary email address. Required and unique across all contacts; "
            "compared case-insensitively and stored lowercased."
        ),
        examples=["ada@example.com"],
    )
    phone: str | None = Field(
        default=None,
        max_length=40,
        description="Phone number. Stored verbatim — any format is accepted.",
        examples=["+1-415-555-0101"],
    )
    company: str | None = Field(
        default=None,
        max_length=200,
        description="Employer or organisation name.",
        examples=["Analytical Engines"],
    )
    job_title: str | None = Field(
        default=None,
        max_length=200,
        description="Role held at the company.",
        examples=["Mathematician"],
    )
    notes: str | None = Field(
        default=None,
        description="Free-form notes about the contact. No length limit.",
        examples=["Met at the SF hackathon."],
    )
    photo: str | None = Field(
        default=None,
        max_length=MAX_PHOTO_LENGTH,
        description="Base64 data URL for the contact's avatar photo.",
        examples=["data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="],
    )
    addresses: list[AddressCreate] = Field(
        default_factory=list,
        description="List of postal addresses associated with this contact.",
    )

    @field_validator("photo")
    @classmethod
    def validate_photo(cls, value: str | None) -> str | None:
        return _validate_photo(value)


_FULL_EXAMPLE = {
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada@example.com",
    "phone": "+1-415-555-0101",
    "company": "Analytical Engines",
    "job_title": "Mathematician",
    "notes": "Met at the SF hackathon.",
    "photo": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "addresses": [
        {
            "type": "Work",
            "street": "1 Market St, Suite 400",
            "city": "San Francisco",
            "state": "CA",
            "zip": "94105",
        }
    ],
}
_MINIMAL_EXAMPLE = {"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"}


class ContactCreate(ContactBase):
    """Body of `POST /api/v1/contacts`. Only the two names and email are required."""

    model_config = ConfigDict(json_schema_extra={"examples": [_FULL_EXAMPLE, _MINIMAL_EXAMPLE]})


class ContactReplace(ContactBase):
    """
    Body of `PUT /api/v1/contacts/{contact_id}`.

    This is a full replacement: any optional field you omit is set back to `null`.
    Use `PATCH` if you only want to change some fields.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [_FULL_EXAMPLE]})

    addresses: list[AddressCreate] = Field(
        description="Full replacement list of postal addresses. Pass empty list [] to clear all addresses.",
    )



class ContactUpdate(BaseModel):
    """
    Body of `PATCH /api/v1/contacts/{contact_id}`.

    Every field is optional. Only the fields actually present in the request are
    written; omitted fields keep their current value. Sending an explicit `null`
    clears that field.
    """

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"phone": "+1-415-555-0199", "job_title": "Chief Engineer"}]}
    )

    first_name: str | None = Field(default=None, min_length=1, max_length=100, description="New given name.")
    last_name: str | None = Field(default=None, min_length=1, max_length=100, description="New family name.")
    email: EmailStr | None = Field(
        default=None,
        max_length=320,
        description="New email address. Must not belong to another contact.",
    )
    phone: str | None = Field(default=None, max_length=40, description="New phone number.")
    company: str | None = Field(default=None, max_length=200, description="New company.")
    job_title: str | None = Field(default=None, max_length=200, description="New job title.")
    notes: str | None = Field(default=None, description="New notes; replaces the existing text.")
    photo: str | None = Field(default=None, max_length=MAX_PHOTO_LENGTH, description="New photo as a base64 data URL.")
    addresses: list[AddressCreate] | None = Field(
        default=None,
        description="New list of addresses. Pass null or [] to clear all addresses; omit to keep existing.",
    )

    @field_validator("photo")
    @classmethod
    def validate_photo(cls, value: str | None) -> str | None:
        return _validate_photo(value)


class ContactRead(ContactBase):
    """A stored contact, as returned by every contact endpoint."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    **_FULL_EXAMPLE,
                    "id": 1,
                    "full_name": "Ada Lovelace",
                    "created_at": "2026-08-19T16:22:58.189507Z",
                    "updated_at": "2026-08-19T16:22:58.189511Z",
                }
            ]
        },
    )

    id: int = Field(description="Server-assigned identifier.", examples=[1])
    addresses: list[AddressRead] = Field(
        default_factory=list,
        description="List of stored addresses for this contact.",
    )
    created_at: datetime = Field(
        description="UTC timestamp of when the contact was created.",
        examples=["2026-08-19T16:22:58.189507Z"],
    )
    updated_at: datetime = Field(
        description="UTC timestamp of the last modification.",
        examples=["2026-08-19T16:22:58.189511Z"],
    )

    @field_validator("created_at", "updated_at")
    @classmethod
    def _as_utc(cls, value: datetime) -> datetime:
        # SQLite discards tzinfo on write; the stored values are UTC, so label
        # them as such rather than emitting an ambiguous naive timestamp.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @computed_field(description="Convenience concatenation of first and last name.", examples=["Ada Lovelace"])
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class ContactPage(BaseModel):
    """One page of contacts plus the totals a client needs to paginate."""

    items: list[ContactRead] = Field(description="Contacts on this page, ordered by the requested sort.")
    total: int = Field(
        description="Total contacts matching the query, ignoring `limit` and `offset`.",
        examples=[42],
    )
    limit: int = Field(description="Page size that was applied.", examples=[50])
    offset: int = Field(description="Number of records skipped.", examples=[0])


class HealthResponse(BaseModel):
    """Result of the liveness probe."""

    status: str = Field(description="Always `ok` when the service can serve traffic.", examples=["ok"])
    database: str = Field(description="Active SQLAlchemy dialect.", examples=["sqlite"])
    contacts: int = Field(description="Number of contacts currently stored.", examples=[3])


class RootResponse(BaseModel):
    """Discovery document listing the API's entry points."""

    name: str = Field(description="Human-readable service name.", examples=["Contacts API"])
    version: str = Field(description="Service version.", examples=["0.1.0"])
    docs: str = Field(description="Path to the Swagger UI.", examples=["/docs"])
    redoc: str = Field(description="Path to the ReDoc UI.", examples=["/redoc"])
    openapi: str = Field(description="Path to the OpenAPI 3.1 document.", examples=["/openapi.json"])
    contacts: str = Field(description="Base path of the contacts collection.", examples=["/api/v1/contacts"])
    health: str = Field(description="Path to the liveness probe.", examples=["/health"])


class ErrorResponse(BaseModel):
    """Shape of every non-validation error returned by the API."""

    detail: str = Field(
        description="Human-readable explanation of the failure.",
        examples=["Contact 42 not found"],
    )
