"""Parse raw queue messages into validated events.

Every message becomes exactly one of: Upsert, StruckOff or Rejected(reason).
Nothing raises, so one bad message can never stop the consumer.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MYT = timezone(timedelta(hours=8))  # assumption: naive timestamps are Malaysia time


@dataclass(frozen=True)
class Upsert:
    registration_number: str
    updated_at: datetime
    company_name: str
    nature_of_business: str | None  # None = not provided in this event
    state: str | None
    industry: str | None


@dataclass(frozen=True)
class StruckOff:
    registration_number: str
    updated_at: datetime


@dataclass(frozen=True)
class Rejected:
    reason: str


Event = Upsert | StruckOff | Rejected


def parse_timestamp(value) -> datetime | None:
    """Accept ISO-8601 (with or without offset) or epoch seconds/milliseconds."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value  # > 1e11 means milliseconds
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=MYT)
    return None


def _text(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def parse_event(body: bytes | str) -> Event:
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return Rejected("invalid_json")
    if not isinstance(obj, dict):
        return Rejected("not_an_object")

    reg = _text(obj.get("registrationNumber"))
    if reg is None:
        return Rejected("missing_registration_number")
    updated_at = parse_timestamp(obj.get("updatedAt"))
    if updated_at is None:
        return Rejected("invalid_updated_at")

    event_type = obj.get("type")
    if event_type == "company-struck-off":
        return StruckOff(reg, updated_at)
    if event_type != "company-upserted":
        return Rejected("unknown_type")

    data = obj.get("data")
    if not isinstance(data, dict):
        return Rejected("data_not_an_object")
    name = _text(data.get("companyName"))
    if name is None:
        return Rejected("missing_company_name")  # a card cannot be drawn without a name
    state = _text(data.get("state"))
    return Upsert(
        registration_number=reg,
        updated_at=updated_at,
        company_name=name,
        nature_of_business=_text(data.get("natureOfBusiness")),
        state=state.title() if state else None,
        industry=_text(data.get("industry")),
    )


def embedding_text(nature_of_business: str | None, company_name: str, industry: str | None) -> tuple[str, str]:
    """Text to embed, and which source it came from.

    Prefer the business description; fall back to name + industry so that
    companies with no description are still searchable, not lost.
    """
    if nature_of_business:
        return nature_of_business, "nature_of_business"
    return (f"{company_name} ({industry})" if industry else company_name), "fallback_name_industry"
