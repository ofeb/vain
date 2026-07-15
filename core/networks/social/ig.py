"""Instagram public client using i.instagram.com + oembed (no login).

Fetches profile / post metadata and direct media URLs for reposts.
Optional session cookies from values.api.instagram are used when present.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp

from .models import SocialPost

log = logging.getLogger("vain.social.instagram")

_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
    "Instagram 192.0.0.37.107"
)
_APP_ID = "936619743392459"
_SHORT_RE = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv|reels)/(?P<code>[\w-]+)",
    re.I,
)
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def is_instagram_url(url: str) -> bool:
    u = (url or "").lower()
    return "instagram.com" in u or "instagr.am" in u


def shortcode_from_url(url: str) -> str | None:
    m = _SHORT_RE.search(url or "")
    if m:
        return m.group("code")
    
    try:
        path = urlparse(url).path.strip("/").split("/")
        for i, part in enumerate(path):
            if part in {"p", "reel", "tv", "reels"} and i + 1 < len(path):
                return path[i + 1]
    except Exception:
        pass
    return None


def shortcode_to_media_id(shortcode: str) -> int:
    media_id = 0
    for ch in shortcode:
        media_id = media_id * 64 + _ALPHABET.index(ch)
    return media_id


class Instagram:
    """Instagram unofficial API wrapper (public endpoints, no login required for oembed)."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._owns_session = session is None

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": _UA,
            "Accept": "*/*",
            "Accept-Language": "en-US",
            "X-IG-App-ID": _APP_ID,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.instagram.com/",
        }
        try:
            from core.managers.values import api as api_cfg

            cookie = api_cfg.instagram.cookie_header()
            if cookie:
                headers["Cookie"] = cookie
        except Exception:
            pass
        return headers

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=12),
            )
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def post(self, url: str) -> Optional[SocialPost]:
        """Rich metadata + media URL for a post/reel."""
        code = shortcode_from_url(url)
        if not code:
            return None
        clean = f"https://www.instagram.com/reel/{code}/"

        tasks = [
            asyncio.create_task(self._from_media_info(code, clean)),
            asyncio.create_task(self._from_oembed(clean, code)),
            asyncio.create_task(self._from_ytdlp(clean, code)),
        ]
        post: SocialPost | None = None
        try:
            for fut in asyncio.as_completed(tasks, timeout=14):
                try:
                    result = await fut
                except Exception:
                    continue
                if not result:
                    continue
                if not post:
                    post = result
                else:
                    post = self._merge(post, result)
                if post.media_urls and post.username not in ("", "unknown"):
                    break
        except asyncio.TimeoutError:
            pass
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()

        if post is None:
            return None
        post.url = post.url or clean
        if not post.display_name:
            post.display_name = post.username
        return post

    async def profile(self, username: str) -> Optional[dict]:
        """Public profile via i.instagram.com web_profile_info."""
        username = (username or "").strip().lstrip("@")
        if not username:
            return None
        session = await self._get_session()
        endpoint = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
        try:
            async with session.get(endpoint, headers=self._headers()) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                user = (data.get("data") or {}).get("user")
                return user
        except Exception as exc:
            log.debug("ig profile failed: %s", exc)
            return None

    async def _from_media_info(self, code: str, url: str) -> Optional[SocialPost]:
        session = await self._get_session()
        media_id = shortcode_to_media_id(code)
        endpoints = [
            f"https://i.instagram.com/api/v1/media/{media_id}/info/",
            f"https://www.instagram.com/api/v1/media/{media_id}/info/",
        ]
        for endpoint in endpoints:
            try:
                async with session.get(endpoint, headers=self._headers()) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
            except Exception as exc:
                log.debug("ig media info failed: %s", exc)
                continue
            item = (data.get("items") or [None])[0]
            if not item:
                continue
            return self._item_to_post(item, code, url)
        return None

    def _item_to_post(self, item: dict[str, Any], code: str, url: str) -> SocialPost:
        user = item.get("user") or item.get("owner") or {}
        caption_obj = item.get("caption") or {}
        if isinstance(caption_obj, dict):
            caption = caption_obj.get("text") or ""
        else:
            caption = str(caption_obj or "")

        media: list[str] = []
        is_video = False
        versions = item.get("video_versions") or []
        if versions:
            is_video = True
            
            best = sorted(versions, key=lambda v: v.get("width") or 0, reverse=True)
            if best and best[0].get("url"):
                media.append(best[0]["url"])
        candidates = (item.get("image_versions2") or {}).get("candidates") or []
        if candidates and not media:
            media.append(candidates[0].get("url"))
        elif candidates and is_video:
            
            pass

        
        for res in item.get("carousel_media") or []:
            vv = res.get("video_versions") or []
            if vv:
                media.append(vv[0]["url"])
                is_video = True
            else:
                imgs = (res.get("image_versions2") or {}).get("candidates") or []
                if imgs:
                    media.append(imgs[0]["url"])

        return SocialPost(
            platform="instagram",
            url=url or f"https://www.instagram.com/p/{code}/",
            username=str(user.get("username") or "unknown"),
            display_name=str(user.get("full_name") or user.get("username") or ""),
            avatar_url=user.get("profile_pic_url") or user.get("profile_pic_url_hd"),
            caption=caption[:2000],
            media_urls=[u for u in media if u],
            is_video=is_video,
            like_count=int(item.get("like_count") or 0),
            comment_count=int(item.get("comment_count") or 0),
            share_count=int(item.get("share_count") or 0),
            save_count=int(item.get("fb_like_count") or 0),
            raw=item,
        )

    async def _from_oembed(self, url: str, code: str) -> Optional[SocialPost]:
        session = await self._get_session()
        endpoints = [
            f"https://www.instagram.com/api/v1/oembed/?url={url}",
            f"https://api.instagram.com/oembed?url={url}",
        ]
        data = None
        for endpoint in endpoints:
            try:
                async with session.get(endpoint, headers=self._headers()) as resp:
                    if resp.status != 200:
                        continue
                    ctype = resp.headers.get("Content-Type", "")
                    if "json" not in ctype and "javascript" not in ctype:
                        
                        text = await resp.text()
                        if text.lstrip().startswith("{"):
                            import json as _json

                            data = _json.loads(text)
                        else:
                            continue
                    else:
                        data = await resp.json(content_type=None)
                    if isinstance(data, dict) and data.get("author_name"):
                        break
            except Exception as exc:
                log.debug("ig oembed failed: %s", exc)
                data = None
        if not isinstance(data, dict):
            return None

        author = data.get("author_name") or "unknown"
        author_url = data.get("author_url") or f"https://www.instagram.com/{author}/"
        
        thumb = data.get("thumbnail_url")
        title = data.get("title") or ""
        return SocialPost(
            platform="instagram",
            url=url,
            username=str(author).lstrip("@"),
            display_name=str(author),
            avatar_url=thumb,
            caption=str(title)[:2000],
            media_urls=[thumb] if thumb else [],
            is_video=False,
            raw=data,
        )

    async def _from_ytdlp(self, url: str, code: str) -> Optional[SocialPost]:
        def _extract() -> dict[str, Any]:
            import yt_dlp

            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "socket_timeout": 12,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False) or {}

        try:
            info = await asyncio.wait_for(asyncio.to_thread(_extract), timeout=14)
        except Exception as exc:
            log.debug("ytdlp ig failed: %s", exc)
            return None
        if not info:
            return None

        media: list[str] = []
        if info.get("url"):
            media.append(str(info["url"]))
        for fmt in info.get("formats") or []:
            u = fmt.get("url")
            if not u:
                continue
            vcodec = fmt.get("vcodec")
            if vcodec and vcodec != "none":
                media.append(u)
                break
        if not media:
            for fmt in info.get("formats") or []:
                if fmt.get("url"):
                    media.append(fmt["url"])
                    break

        username = info.get("uploader_id") or info.get("channel") or info.get("uploader") or "unknown"
        return SocialPost(
            platform="instagram",
            url=str(info.get("webpage_url") or url),
            username=str(username).lstrip("@"),
            display_name=str(info.get("uploader") or username),
            avatar_url=info.get("thumbnail"),
            caption=str(info.get("description") or info.get("title") or ""),
            media_urls=media,
            is_video=True,
            like_count=int(info.get("like_count") or 0),
            comment_count=int(info.get("comment_count") or 0),
            raw=info,
        )

    @staticmethod
    def _merge(base: SocialPost, extra: SocialPost) -> SocialPost:
        
        def _score(urls: list[str]) -> int:
            score = 0
            for u in urls:
                lu = u.lower()
                if ".mp4" in lu or "video" in lu:
                    score += 10
                elif u.startswith("http"):
                    score += 1
            return score

        if _score(extra.media_urls) > _score(base.media_urls):
            base.media_urls = extra.media_urls
            base.is_video = extra.is_video
        if base.username in ("", "unknown") and extra.username not in ("", "unknown"):
            base.username = extra.username
            base.display_name = extra.display_name or base.display_name
        if (not base.avatar_url or "s150x150" in (base.avatar_url or "")) and extra.avatar_url:
            
            if "cdninstagram" in (extra.avatar_url or "") or not base.avatar_url:
                if "s150x150" not in (extra.avatar_url or "") or not base.avatar_url:
                    base.avatar_url = extra.avatar_url
        if len(extra.caption or "") > len(base.caption or ""):
            base.caption = extra.caption
        for attr in ("like_count", "comment_count", "share_count", "save_count"):
            if not getattr(base, attr) and getattr(extra, attr):
                setattr(base, attr, getattr(extra, attr))
        return base
