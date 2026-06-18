"""format durations and timestamps for humans.
converts raw seconds ms or datetime into readable strings.
use duration timedelta or when functions"""

import datetime
from typing import Union
from dateutil.relativedelta import relativedelta


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


def timedelta(dt1: datetime.datetime, dt2: datetime.datetime = None) -> str:
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
