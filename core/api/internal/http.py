"""HTTP helpers for vainapi clients."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientSession

from .exceptions import Error


class _Munch(dict):
  """Minimal attribute-access dict (replaces munch.DefaultMunch dependency)."""

  def __getattr__(self, item: str) -> Any:
    try:
      return self[item]
    except KeyError:
      return None

  def __setattr__(self, key: str, value: Any) -> None:
    self[key] = value

  def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
    return super().get(key, default)


def _munchify(data: Any) -> Any:
  if isinstance(data, dict):
    return _Munch({k: _munchify(v) for k, v in data.items()})
  if isinstance(data, list):
    return [_munchify(v) for v in data]
  return data


class State:
  """Shared aiohttp request helper used by vainapi clients."""

  async def request(self: "State", method: str, url: str, **kwargs: Any) -> Any:
    async with ClientSession() as cs:
      response = await cs.request(
        method=method,
        url=url,
        **kwargs,
      )

      ctype = (response.content_type or "").lower()

      if ctype.startswith(("image/", "video/", "audio/")):
        return await response.read()

      # Always buffer body once
      body = await response.read()

      if ctype.startswith("text/html") or ctype.startswith("text/plain"):
        return body.decode("utf-8", "replace")

      # JSON-ish
      if (
        "json" in ctype
        or ctype in ("application/octet-stream", "text/javascript", "application/javascript")
        or not ctype
      ):
        text = body.decode("utf-8", "replace")
        stripped = text.lstrip()
        if stripped.startswith(("{", "[")):
          try:
            import json

            return _munchify(json.loads(text))
          except Exception as e:
            # some download APIs return JS/HTML with a json content-type
            if "json" in ctype:
              return text
            raise Error(f"Could not parse JSON -> {e}") from e
        # non-json body (e.g. instasave returns JS snippet)
        return text

      # fallback: try decode as text
      try:
        return body.decode("utf-8", "replace")
      except Exception:
        return body
