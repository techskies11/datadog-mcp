"""Shared time-value parsing for tools that accept flexible time inputs.

Datadog's Logs and Spans v2 search/aggregate APIs accept ISO 8601 strings,
relative date-math expressions (`"now-1h"`), and millisecond timestamps
natively, server-side - those tools just pass `from_time`/`to_time` through
unmodified. The Metrics v1 API, in contrast, requires Unix-second integers
on the wire. `parse_time_value` gives metrics tools the same flexible input
format as the rest of the server, resolving date math and ISO 8601 on the
client side into the integer the API actually expects.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

_RELATIVE_PATTERN = re.compile(r"^now(?:([+-])(\d+)([smhdw]))?$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_MILLISECOND_THRESHOLD = 10_000_000_000  # ~2286-11-20 as a Unix second timestamp

# Shared docstring fragment for tools whose from_time/to_time accept Datadog's
# native flexible formats (logs and spans search/aggregate). Keeping the
# wording in one place means every such tool documents the same three
# formats consistently instead of each author re-describing them by hand.
FLEXIBLE_TIME_DOC = (
    'ISO 8601 (e.g. "2024-01-28T10:00:00Z"), relative date math '
    '(e.g. "now-1h", "now", "now+2d"), or a millisecond timestamp'
)


def parse_time_value(value: str | int, *, now: datetime | None = None) -> int:
    """Resolve a flexible time value to a Unix timestamp in whole seconds.

    Accepts, in order of precedence:
    - An `int`, assumed to already be Unix seconds and returned unchanged.
    - Relative date math: `"now"`, `"now-1h"`, `"now-15m"`, `"now-7d"`, and
      the future-facing equivalents `"now+1h"`, `"now+2d"` (useful for
      scheduling things like downtime end times, as opposed to the
      backward-looking windows most log/metric queries use).
    - A numeric string, treated as Unix seconds or milliseconds (any value
      after 2286 is assumed to be milliseconds).
    - An ISO 8601 datetime string, e.g. `"2024-01-28T10:00:00Z"`.

    Args:
        value: The time value to resolve.
        now: Reference "current time" for relative expressions; defaults to
            the real current UTC time. Exposed for deterministic tests.

    Raises:
        ValueError: If `value` doesn't match any of the accepted formats.
    """
    if isinstance(value, int):
        return value

    text = value.strip()

    relative_match = _RELATIVE_PATTERN.match(text)
    if relative_match:
        reference = now or datetime.now(timezone.utc)
        sign, amount, unit = relative_match.groups()
        if amount is None:
            return int(reference.timestamp())
        offset = int(amount) * _UNIT_SECONDS[unit]
        return (
            int(reference.timestamp()) + offset
            if sign == "+"
            else int(reference.timestamp()) - offset
        )

    if text.lstrip("-").isdigit():
        as_int = int(text)
        return as_int // 1000 if abs(as_int) > _MILLISECOND_THRESHOLD else as_int

    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError as exc:
        raise ValueError(
            f"Could not parse time value {value!r}. Expected a Unix timestamp, "
            "date math like 'now-1h', or an ISO 8601 datetime string."
        ) from exc
