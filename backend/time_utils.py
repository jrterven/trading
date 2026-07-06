from __future__ import annotations

from datetime import UTC, datetime, time


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def parse_datetime(value: str | datetime | None, default: datetime | None = None) -> datetime:
    if value is None:
        if default is None:
            raise ValueError("datetime value is required")
        return ensure_utc(default)
    if isinstance(value, datetime):
        return ensure_utc(value)

    text = value.strip()
    if len(text) == 10:
        parsed = datetime.combine(datetime.fromisoformat(text).date(), time.min, tzinfo=UTC)
    else:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return ensure_utc(parsed)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def isoformat_utc(value: datetime) -> str:
    return ensure_utc(value).isoformat().replace("+00:00", "Z")

