"""vainapi Instagram client — no session cookies required.

Fetches public reels/posts via third-party download APIs that return
playable CDN URLs (primarily instasave). Optional i.instagram.com
endpoints are only used when they work without auth.
"""

from __future__ import annotations

import base64
import json
import re
from asyncio import Semaphore, sleep
from io import BytesIO
from pathlib import Path
from random import uniform
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

from .exceptions import Error
from .http import State
from .models import (
  InstagramComment,
  InstagramFollowerUser,
  InstagramHighlight,
  InstagramMedia,
  InstagramStory,
  InstagramUser,
)

INSTAGRAM_REGEX = re.compile(
  r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv|reels)/(?P<code>[A-Za-z0-9_-]+)",
  re.I,
)

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_IG_APP_ID = "936619743392459"
_UA_WEB = (
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_UA_APP = (
  "Instagram 192.0.0.37.107 Android (33/13; 420dpi; 1080x2400; "
  "Google/google; Pixel 7; panther; panther; en_US; 301484483)"
)
_BASE = "https://i.instagram.com/api/v1"


def shortcode_from_url(url: str) -> Optional[str]:
  match = INSTAGRAM_REGEX.search(url or "")
  if match:
    return match.group("code")
  try:
    parts = [p for p in urlparse(url).path.split("/") if p]
    for i, part in enumerate(parts):
      if part in {"p", "reel", "tv", "reels"} and i + 1 < len(parts):
        return parts[i + 1]
  except Exception:
    pass
  return None


def shortcode_to_media_id(code: str) -> int:
  media_id = 0
  for ch in code:
    media_id = media_id * 64 + _ALPHABET.index(ch)
  return media_id


def _as_dict(obj: Any) -> dict:
  if obj is None:
    return {}
  if isinstance(obj, dict):
    return obj
  try:
    return dict(obj)
  except Exception:
    return getattr(obj, "__dict__", {}) or {}


def _decode_jwt_payload(token: str) -> dict:
  parts = (token or "").split(".")
  if len(parts) < 2:
    return {}
  pad = parts[1] + "=" * (-len(parts[1]) % 4)
  try:
    raw = base64.urlsafe_b64decode(pad.encode())
    return json.loads(raw.decode("utf-8", "replace"))
  except Exception:
    return {}


def _looks_like_video(url: str) -> bool:
  lu = (url or "").lower()
  return any(
    t in lu
    for t in (".mp4", "video", "/v/t2/", "/v/t16/", "/v/t50/", "mime_type=video")
  )


def _looks_like_image(url: str) -> bool:
  lu = (url or "").lower().split("?")[0]
  return any(lu.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp"))


class Instagram:
  """vainapi Instagram wrapper — public download APIs, no login cookies."""

  def __init__(
    self: "Instagram",
    csrf: str | None = None,
    session_id: str | None = None,
    proxy: str | None = None,
    *,
    ds_user_id: str | None = None,
  ):
    # csrf/session_id/ds_user_id kept for signature compatibility but unused
    self.session = State()
    self.proxy = proxy
    self.csrf = None
    self.session_id = None
    self.ds_user_id = None
    self._user_cache: Dict[str, InstagramUser] = {}

  def _web_headers(self: "Instagram", *, origin: str | None = None) -> dict[str, str]:
    headers = {
      "User-Agent": _UA_WEB,
      "Accept": "*/*",
      "Accept-Language": "en-US,en;q=0.9",
    }
    if origin:
      headers["Origin"] = origin
      headers["Referer"] = origin.rstrip("/") + "/"
    return headers

  def _app_headers(self: "Instagram") -> dict[str, str]:
    return {
      "User-Agent": _UA_APP,
      "Accept": "*/*",
      "Accept-Language": "en-US",
      "X-IG-App-ID": _IG_APP_ID,
      "X-IG-Capabilities": "3brTvw==",
      "X-IG-Connection-Type": "WIFI",
      "Referer": "https://www.instagram.com/",
    }

  async def _request(
    self: "Instagram",
    method: str,
    url: str,
    max_concurrent: int = 3,
    max_retries: int = 2,
    **kwargs: Any,
  ) -> Any:
    async with Semaphore(max_concurrent):
      last_err: Exception | None = None
      for _ in range(max_retries):
        try:
          await sleep(uniform(0.05, 0.25))
          kwargs.setdefault("headers", self._web_headers())
          if self.proxy:
            kwargs.setdefault("proxy", self.proxy)
          return await self.session.request(method, url, **kwargs)
        except Error:
          raise
        except Exception as exc:
          last_err = exc
          await sleep(uniform(0.2, 0.6))
      raise Error(f"instagram request failed: {last_err}")

  # ── Public media resolution (no cookies) ──────────────────────────

  async def resolve_media(self: "Instagram", url: str) -> dict[str, Any]:
    """Resolve a post/reel URL into media URLs + light metadata.

    Returns
    -------
    dict with keys: code, video_urls, image_urls, author_name, title, source
    """
    code = shortcode_from_url(url)
    if not code:
      raise Error("This is not a valid instagram post url.")

    clean = url if url.startswith("http") else f"https://www.instagram.com/reel/{code}/"
    if "/p/" not in clean and "/reel" not in clean:
      clean = f"https://www.instagram.com/reel/{code}/"

    # Prefer public download APIs (no login) — await one source at a time
    result: dict[str, Any] | None = None
    for name, factory in (
      ("instasave", lambda: self._from_instasave(clean)),
      ("oembed+instasave", lambda: self._from_oembed_then_instasave(clean, code)),
    ):
      try:
        candidate = await factory()
      except Exception:
        candidate = None
      if candidate and (candidate.get("video_urls") or candidate.get("image_urls")):
        candidate.setdefault("code", code)
        candidate.setdefault("source", name)
        result = candidate
        break

    if not result:
      raise Error("Could not resolve Instagram media for that URL.")

    # Best-effort public oembed for author/caption (never blocks media)
    if not result.get("author_name") or not result.get("title"):
      try:
        meta = await self._oembed_meta(clean)
        if meta.get("author_name") and not result.get("author_name"):
          result["author_name"] = meta["author_name"]
        if meta.get("title") and not result.get("title"):
          result["title"] = meta["title"]
      except Exception:
        pass
    return result

  async def _oembed_meta(self: "Instagram", url: str) -> dict[str, Any]:
    data = await self._request(
      "GET",
      f"https://www.instagram.com/api/v1/oembed/?url={url}",
      headers={**self._web_headers(), "X-IG-App-ID": _IG_APP_ID},
    )
    d = _as_dict(data) if not isinstance(data, str) else {}
    return {
      "author_name": d.get("author_name"),
      "title": d.get("title"),
      "media_id": d.get("media_id"),
    }

  async def _from_instasave(self: "Instagram", url: str) -> Optional[dict[str, Any]]:
    """Primary: api.instasave.website — returns JWT-wrapped CDN links."""
    data = await self._request(
      "POST",
      "https://api.instasave.website/media",
      headers=self._web_headers(origin="https://instasave.website"),
      json={"url": url},
    )
    # State may return str (text/plain or html-ish) or munch
    text = data if isinstance(data, str) else str(data)
    if not text or len(text) < 20:
      return None

    video_urls: list[str] = []
    image_urls: list[str] = []

    # JWT tokens embed the real CDN url
    for tok in re.findall(r"token=([A-Za-z0-9_\-\.]+)", text):
      payload = _decode_jwt_payload(tok)
      media_url = payload.get("url")
      if not isinstance(media_url, str) or not media_url.startswith("http"):
        continue
      media_url = unquote(media_url)
      if _looks_like_video(media_url) or str(payload.get("filename", "")).endswith(".mp4"):
        if media_url not in video_urls:
          video_urls.append(media_url)
      elif media_url not in image_urls:
        image_urls.append(media_url)

    # Direct mp4/scontent links in body
    unescaped = (
      text.replace("\\/", "/")
      .replace("\\u0026", "&")
      .replace("\\x22", '"')
    )
    for m in re.findall(r"https?://[^\"'\\s<>]+\.mp4[^\"'\\s<>]*", unescaped, re.I):
      u = unquote(m.strip("\\\"'"))
      if u not in video_urls:
        video_urls.append(u)

    if not video_urls and not image_urls:
      return None
    return {
      "video_urls": video_urls,
      "image_urls": image_urls,
      "author_name": None,
      "title": None,
      "source": "instasave",
    }

  async def _from_oembed_then_instasave(
    self: "Instagram",
    url: str,
    code: str,
  ) -> Optional[dict[str, Any]]:
    """Retry instasave after a short delay (used as secondary source)."""
    await sleep(0.4)
    media = await self._from_instasave(url)
    if not media:
      return None
    media["code"] = code
    return media

  async def get_video_url(self: "Instagram", url: str) -> Optional[str]:
    """Best playable video URL for a post/reel."""
    resolved = await self.resolve_media(url)
    videos = resolved.get("video_urls") or []
    return videos[0] if videos else None

  async def get_post(
    self: "Instagram",
    url: str,
    amount: Optional[int] = None,
  ) -> List[InstagramMedia]:
    """Fetch post/reel media (public APIs, no cookies)."""
    code = shortcode_from_url(url)
    if not code:
      raise Error("This is not a valid instagram post url.")

    resolved = await self.resolve_media(url)
    video_urls: list[str] = list(resolved.get("video_urls") or [])
    image_urls: list[str] = list(resolved.get("image_urls") or [])
    if amount:
      image_urls = image_urls[:amount]

    author = resolved.get("author_name") or "unknown"
    title = resolved.get("title") or ""
    media_type = 2 if video_urls else 1

    media = InstagramMedia.model_validate(
      {
        "pk": shortcode_to_media_id(code),
        "id": shortcode_to_media_id(code),
        "code": code,
        "media_type": media_type,
        "taken_at": 0,
        "like_count": 0,
        "comment_count": 0,
        "title": title,
        "user": {"pk": 0, "username": str(author).lstrip("@"), "full_name": str(author)},
        "image_urls": image_urls or None,
        "thumbnail_url": image_urls[0] if image_urls else None,
        "video_url": video_urls[0] if video_urls else None,
        "video_duration": 0.0,
      }
    )
    # attach extra videos on a synthetic list via image_urls if multiple
    if len(video_urls) > 1:
      media.image_urls = list(video_urls[1:]) + list(image_urls or [])
    return [media]

  async def download_media(
    self: "Instagram",
    media_url: str,
    path: str | Path | None = None,
  ) -> Path | BytesIO:
    """Download a CDN media URL."""
    if not media_url:
      raise Error("no media url to download")
    data = await self.session.request(
      "GET",
      media_url,
      headers=self._web_headers(origin="https://www.instagram.com"),
      proxy=self.proxy,
    )
    if not isinstance(data, (bytes, bytearray)):
      raise Error("expected binary media response")
    if path:
      save = Path(path)
      save.write_bytes(data)
      return save
    return BytesIO(data)

  # ── Optional profile helpers (best-effort, may fail without login) ─

  async def get_user(self: "Instagram", username: str) -> InstagramUser:
    username = (username or "").strip().lstrip("@")
    if not username:
      raise Error("provide a username")
    if username in self._user_cache:
      return self._user_cache[username]

    # oembed-style public profile page scrape is unreliable; try web_profile_info
    try:
      data = await self._request(
        "GET",
        f"{_BASE}/users/web_profile_info/?username={username}",
        headers=self._app_headers(),
      )
      user = None
      if getattr(data, "data", None) is not None:
        user = getattr(data.data, "user", None)
      if user is None:
        user = getattr(data, "user", None)
      if user:
        raw = _as_dict(user)
        if "follower_count" not in raw and "edge_followed_by" in raw:
          edge = raw.get("edge_followed_by") or {}
          raw["follower_count"] = edge.get("count", 0) if isinstance(edge, dict) else 0
        if "following_count" not in raw and "edge_follow" in raw:
          edge = raw.get("edge_follow") or {}
          raw["following_count"] = edge.get("count", 0) if isinstance(edge, dict) else 0
        if "media_count" not in raw and "edge_owner_to_timeline_media" in raw:
          edge = raw.get("edge_owner_to_timeline_media") or {}
          raw["media_count"] = edge.get("count", 0) if isinstance(edge, dict) else 0
        raw.setdefault("is_business", bool(raw.get("is_business_account")))
        raw.setdefault("pk", raw.get("id") or raw.get("pk") or 0)
        obj = InstagramUser.model_validate(raw)
        self._user_cache[username] = obj
        return obj
    except Exception:
      pass

    # minimal stub from username alone
    obj = InstagramUser.model_validate(
      {
        "pk": 0,
        "username": username,
        "full_name": username,
        "is_private": False,
        "is_verified": False,
        "media_count": 0,
        "follower_count": 0,
        "following_count": 0,
        "is_business": False,
      }
    )
    self._user_cache[username] = obj
    return obj

  async def get_story(self: "Instagram", username: str, amount: Optional[int] = None) -> List[InstagramStory]:
    raise Error("stories require authentication; not supported in cookie-free mode")

  async def get_highlights(self: "Instagram", username: str, amount: Optional[int] = None) -> List[InstagramHighlight]:
    raise Error("highlights require authentication; not supported in cookie-free mode")

  async def get_comments(self: "Instagram", url: str, amount: Optional[int] = None) -> List[InstagramComment]:
    raise Error("comments require authentication; not supported in cookie-free mode")

  async def get_followers(self: "Instagram", username: str, amount: Optional[int] = None) -> List[InstagramFollowerUser]:
    raise Error("followers require authentication; not supported in cookie-free mode")

  async def get_following(self: "Instagram", username: str, amount: Optional[int] = None) -> List[InstagramFollowerUser]:
    raise Error("following require authentication; not supported in cookie-free mode")
