"""Shared HTTP session helpers for API clients."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from aiohttp import ClientSession, ClientTimeout

from .exceptions import Error


def _munchify(data: Any) -> Any:
    """Recursively convert dicts to attribute-access namespaces (munch-like)."""
    if isinstance(data, dict):
        ns = SimpleNamespace(**{k: _munchify(v) for k, v in data.items()})
        # allow .get for drop-in munch compatibility
        ns.get = lambda key, default=None, _d=data: _munchify(_d[key]) if key in _d else default  # type: ignore
        return ns
    if isinstance(data, list):
        return [_munchify(v) for v in data]
    return data


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class State:
    """Thin aiohttp wrapper that returns text, bytes, or attribute-access JSON."""

    def __init__(self, *, timeout: float = 15.0) -> None:
        self.timeout = ClientTimeout(total=timeout)

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        timeout = kwargs.pop("timeout", self.timeout)
        async with ClientSession(timeout=timeout) as session:
            async with session.request(method=method, url=url, **kwargs) as response:
                ctype = (response.content_type or "").lower()

                if ctype in {"text/plain", "text/html"}:
                    return await response.text()

                if ctype.startswith(("image/", "video/", "audio/")):
                    return await response.read()

                if (
                    ctype in {
                        "application/json",
                        "application/octet-stream",
                        "text/javascript",
                    }
                    or "json" in ctype
                ):
                    try:
                        data = await response.json(content_type=None)
                    except Exception as exc:
                        raise Error(f"Could not parse JSON -> {exc}") from exc
                    return _munchify(data)

                try:
                    data = await response.json(content_type=None)
                    return _munchify(data)
                except Exception:
                    return await response.text()
