"""Parse provider Retry-After delay-seconds and absolute HTTP dates."""
from datetime import datetime
from email.utils import parsedate_to_datetime
import math


def retry_after_seconds(value: str, now: datetime) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        if value.strip().isascii() and value.strip().isdecimal():
            seconds = float(value.strip())
        else:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                return None
            seconds = max(0.0, (when - now).total_seconds())
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None
