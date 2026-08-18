"""format durations and timestamps for humans.
converts raw seconds ms or datetime into readable strings.
use duration timedelta or when functions"""

from __future__ import annotations

import datetime
import re
from typing import Union
from dateutil.relativedelta import relativedelta

from .text import ordinal


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:[T\s]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_dt(value) -> datetime.datetime | None:
    """Parse datetime / unix / ISO-ish strings into an aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    if isinstance(value, (int, float)):
        ts = float(value)
        
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw or raw.lower() in {"unknown", "none", "null", "n/a"}:
            return None
        if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
            return parse_dt(int(raw))
        try:
            return parse_dt(float(raw))
        except ValueError:
            pass
        cleaned = raw.replace("Z", "+00:00")
        
        if " " in cleaned and "T" not in cleaned[:11]:
            cleaned = cleaned.replace(" ", "T", 1)
        try:
            return parse_dt(datetime.datetime.fromisoformat(cleaned))
        except ValueError:
            for fmt in (
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d",
                "%m/%d/%Y",
                "%m/%d/%y",
            ):
                try:
                    return parse_dt(datetime.datetime.strptime(raw.replace("Z", ""), fmt))
                except ValueError:
                    continue
    return None


def human_date(value, *, fallback: str = "Unknown") -> str:
    """Format a date like ``19th of April, 2024``."""
    dt = parse_dt(value)
    if dt is None:
        if isinstance(value, str) and value.strip() and not _ISO_RE.match(value.strip()):
            return value.strip()
        return fallback
    return f"{ordinal(dt.day)} of {dt.strftime('%B')}, {dt.year}"


def discord_ts(value, style: str = "R") -> str:
    """Discord timestamp markdown, or human_date as a fallback."""
    dt = parse_dt(value)
    if dt is None:
        return human_date(value)
    return f"<t:{int(dt.timestamp())}:{style}>"


def discord_footer_date(value, *, fallback: str = "Unknown") -> str:
    """Format a timestamp like Discord message headers in the *viewer's* local time.

    Uses Discord timestamp markdown so each client renders the correct local clock
    (fixes footers showing UTC and appearing an hour behind in BST, etc.).

    - Same calendar day (UTC day used only for Today/Yesterday label choice):
      ``Today at <t:UNIX:t>``
    - Previous day: ``Yesterday at <t:UNIX:t>``
    - Older: ``<t:UNIX:f>``
    """
    dt = parse_dt(value)
    if dt is None:
        if isinstance(value, str) and value.strip() and not _ISO_RE.match(value.strip()):
            return value.strip()
        return fallback
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    unix = int(dt.timestamp())
    
    
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    day = dt.date()
    today = now.date()
    if day == today:
        return f"Today at <t:{unix}:t>"
    if day == today - datetime.timedelta(days=1):
        return f"Yesterday at <t:{unix}:t>"
    return f"<t:{unix}:f>"


def duration(value: int, ms: bool = True) -> str:
    """convert seconds or ms into HH:MM:SS string"""
    if ms:
        h = int((value / (1000 * 60 * 60)) % 24)
        m = int((value / (1000 * 60)) % 60)
        s = int((value / 1000) % 60)
    else:
        h = int((value / 3600) % 24)
        m = int((value / 60) % 60)
        s = int(value % 60)
    return f"{h:02}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"


def timedelta(
    dt1: datetime.datetime, dt2: datetime.datetime | None = None
) -> str:
    """human readable relative time between two datetimes"""
    if dt2 is None:
        dt2 = datetime.datetime.now(tz=datetime.timezone.utc)
    if dt1.tzinfo is None:
        dt1 = dt1.replace(tzinfo=datetime.timezone.utc)
    delta = relativedelta(dt2, dt1)
    parts = []
    if delta.years:
        parts.append(f"{delta.years} year{'s' if delta.years != 1 else ''}")
    if delta.months:
        parts.append(f"{delta.months} month{'s' if delta.months != 1 else ''}")
    if delta.days:
        parts.append(f"{delta.days} day{'s' if delta.days != 1 else ''}")
    if delta.hours:
        parts.append(f"{delta.hours} hour{'s' if delta.hours != 1 else ''}")
    if delta.minutes:
        parts.append(f"{delta.minutes} minute{'s' if delta.minutes != 1 else ''}")
    if not parts:
        parts.append(f"{delta.seconds} second{'s' if delta.seconds != 1 else ''}")
    return ", ".join(parts[:2])


def when(dt: datetime.datetime) -> str:
    """how long ago or from now a datetime is"""
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    diff = (now - dt).total_seconds()
    ago = diff >= 0
    diff = abs(diff)
    if diff < 60:
        s = f"{int(diff)} second{'s' if int(diff) != 1 else ''}"
    elif diff < 3600:
        m = int(diff / 60)
        s = f"{m} minute{'s' if m != 1 else ''}"
    elif diff < 86400:
        h = int(diff / 3600)
        s = f"{h} hour{'s' if h != 1 else ''}"
    else:
        d = int(diff / 86400)
        s = f"{d} day{'s' if d != 1 else ''}"
    return f"{s} ago" if ago else f"in {s}"
