import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class PageCursor(BaseModel):
    model_config = ConfigDict(frozen=True)

    published_at: datetime
    article_id: UUID
    score_key: int | None = None

    @field_validator("published_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cursor timestamp must include a timezone")
        return value


def encode_cursor(cursor: PageCursor) -> str:
    payload = cursor.model_dump_json().encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(value: str) -> PageCursor:
    try:
        padding = "=" * (-len(value) % 4)
        payload = base64.urlsafe_b64decode(value + padding)
        parsed = json.loads(payload)
        return PageCursor.model_validate(parsed)
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise ValueError("invalid pagination cursor") from exc
