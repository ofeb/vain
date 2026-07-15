"""Instagram public client — reels/posts metadata + media.

Uses i.instagram.com when cookies are available, plus oembed + embed-page
scraping for creator info when logged-out. Never treats the oembed poster
thumbnail as the video or as the creator avatar.
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


def _looks_like_video(url: str) -> bool:
    lu = (url or "").lower()
    return any(
        t in lu
        for t in (".mp4", "video", "play_video", "mime_type=video", "/v/t16/", "/v/t50/")
    )


def _looks_like_image(url: str) -> bool:
    lu = (url or "").lower().split("?")[0]
    return any(lu.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp"))


def _unescape_ig_url(raw: str) -> str:
    return (
        (raw or "")
        .replace("\\/", "/")
        .replace("\\\\/", "/")
        .replace("\\u0026", "&")
        .replace("\\u003d", "=")
        .replace("\\u00253D", "=")
        .replace("\\u00253d", "=")
    )


class Instagram:
    """Instagram client for public/cookie-backed post + profile fetch."""

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
                timeout=aiohttp.ClientTimeout(total=15),
            )
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def post(self, url: str) -> Optional[SocialPost]:
        """Fetch post/reel metadata. Prefer real video URL over poster image."""
        code = shortcode_from_url(url)
        if not code:
            return None
        is_reel = "/reel" in (url or "").lower() or "/reels/" in (url or "").lower()
        clean = (
            f"https://www.instagram.com/reel/{code}/"
            if is_reel
            else f"https://www.instagram.com/p/{code}/"
        )

        # Run sources; merge carefully so thumbnail never replaces video
        parts: list[SocialPost] = []
        for coro in (
            self._from_media_info(code, clean),
            self._from_embed_page(code, clean),
            self._from_oembed(clean, code),
            self._from_ytdlp(clean, code),
        ):
            try:
                result = await coro
            except Exception as exc:
                log.debug("ig source failed: %s", exc)
                result = None
            if result:
                parts.append(result)

        if not parts:
            return None

        post = parts[0]
        for extra in parts[1:]:
            post = self._merge(post, extra)

        # Creator avatar: never use the reel poster frame as PFP
        if post.username and post.username != "unknown":
            avatar = post.avatar_url or ""
            needs_pfp = (
                not avatar
                or "t51.71878" in avatar  # reel cover frame path, not profile
                or "stp=dst-jpegr" in avatar
                or (post.media_urls and avatar == post.media_urls[0])
            )
            if needs_pfp:
                pfp = await self._fetch_profile_pic(post.username)
                if pfp:
                    post.avatar_url = pfp

        # Reels without a video URL are incomplete — mark as video for downloader
        if is_reel or post.is_video:
            post.is_video = True
            # Drop image-only media_urls so callers don't treat poster as the video
            videos = [u for u in post.media_urls if _looks_like_video(u)]
            if videos:
                post.media_urls = videos
            else:
                # keep empty so upper layer downloads via yt-dlp instead of attaching jpg
                post.media_urls = []

        post.url = post.url or clean
        if not post.display_name:
            post.display_name = post.username
        return post

    async def profile(self, username: str) -> Optional[dict]:
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
                return (data.get("data") or {}).get("user")
        except Exception as exc:
            log.debug("ig profile failed: %s", exc)
            return None

    async def _fetch_profile_pic(self, username: str) -> str | None:
        user = await self.profile(username)
        if isinstance(user, dict):
            return (
                user.get("profile_pic_url_hd")
                or user.get("profile_pic_url")
                or None
            )
        # Fallback: scrape profile HTML for profile pic
        session = await self._get_session()
        try:
            async with session.get(
                f"https://www.instagram.com/{username}/",
                headers={**self._headers(), "Accept": "text/html"},
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            m = re.search(r'\\"profile_pic_url\\":\\"(https:[^"]+?)\\"', html)
            if m:
                return _unescape_ig_url(m.group(1))
            m = re.search(r'"profile_pic_url"\s*:\s*"(https:[^"]+)"', html)
            if m:
                return _unescape_ig_url(m.group(1))
        except Exception as exc:
            log.debug("ig profile html scrape failed: %s", exc)
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
            best = sorted(versions, key=lambda v: (v.get("width") or 0) * (v.get("height") or 0), reverse=True)
            if best and best[0].get("url"):
                media.append(best[0]["url"])

        for res in item.get("carousel_media") or []:
            vv = res.get("video_versions") or []
            if vv:
                media.append(vv[0]["url"])
                is_video = True
            else:
                imgs = (res.get("image_versions2") or {}).get("candidates") or []
                if imgs and imgs[0].get("url"):
                    media.append(imgs[0]["url"])

        if not media and not is_video:
            candidates = (item.get("image_versions2") or {}).get("candidates") or []
            if candidates and candidates[0].get("url"):
                media.append(candidates[0]["url"])

        return SocialPost(
            platform="instagram",
            url=url or f"https://www.instagram.com/p/{code}/",
            username=str(user.get("username") or "unknown"),
            display_name=str(user.get("full_name") or user.get("username") or ""),
            avatar_url=user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
            caption=caption[:2000],
            media_urls=[u for u in media if u],
            is_video=is_video or bool(item.get("media_type") == 2),
            like_count=int(item.get("like_count") or 0),
            comment_count=int(item.get("comment_count") or 0),
            share_count=int(item.get("share_count") or item.get("reshare_count") or 0),
            save_count=int(
                item.get("fb_like_count")
                or (item.get("ig_play_count") and 0)
                or item.get("save_count")
                or 0
            ),
            raw=item,
        )

    async def _from_embed_page(self, code: str, url: str) -> Optional[SocialPost]:
        """Scrape embed page for is_video, poster, owner pfp (no video CDN when logged out)."""
        session = await self._get_session()
        embed_url = f"https://www.instagram.com/reel/{code}/embed/captioned/"
        try:
            async with session.get(
                embed_url,
                headers={**self._headers(), "Accept": "text/html"},
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
        except Exception as exc:
            log.debug("ig embed page failed: %s", exc)
            return None

        is_video = '"is_video":true' in html or '\\"is_video\\":true' in html or "GraphVideo" in html
        username = None
        for pat in (
            r'\\"username\\":\\"([^\\"]+)\\"',
            r'"username"\s*:\s*"([^"]+)"',
        ):
            m = re.search(pat, html)
            if m:
                username = m.group(1)
                break

        avatar = None
        for pat in (
            r'\\"profile_pic_url\\":\\"(https:[^"]+?)\\"',
            r'"profile_pic_url"\s*:\s*"(https:[^"]+)"',
        ):
            m = re.search(pat, html)
            if m:
                avatar = _unescape_ig_url(m.group(1))
                break

        # Real mp4 if present (rare when logged out)
        media: list[str] = []
        for pat in (
            r'\\"video_url\\":\\"(https:[^"]+?)\\"',
            r'"video_url"\s*:\s*"(https:[^"]+)"',
            r'(https://[^"\\]+\.mp4[^"\\]*)',
        ):
            for m in re.finditer(pat, html):
                u = _unescape_ig_url(m.group(1))
                if _looks_like_video(u):
                    media.append(u)
                    is_video = True
            if media:
                break

        caption = ""
        m = re.search(r'\\"edge_media_to_caption\\".*?\\"text\\":\\"(.*?)\\"', html)
        if m:
            caption = _unescape_ig_url(m.group(1))[:2000]

        if not username and not media and not avatar:
            return None

        return SocialPost(
            platform="instagram",
            url=url,
            username=username or "unknown",
            display_name=username or "unknown",
            avatar_url=avatar,
            caption=caption,
            media_urls=media,
            is_video=is_video,
            raw={"source": "embed_page", "is_video": is_video},
        )

    async def _from_oembed(self, url: str, code: str) -> Optional[SocialPost]:
        """Author + caption only. Never use thumbnail as video or as avatar."""
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
        title = data.get("title") or ""
        # thumbnail is the VIDEO POSTER — not creator pfp, not playable video
        return SocialPost(
            platform="instagram",
            url=url,
            username=str(author).lstrip("@"),
            display_name=str(author),
            avatar_url=None,
            caption=str(title)[:2000],
            media_urls=[],  # never treat oembed thumb as media
            is_video="/reel" in url.lower(),
            raw={"source": "oembed", "thumbnail_url": data.get("thumbnail_url")},
        )

    async def _from_ytdlp(self, url: str, code: str) -> Optional[SocialPost]:
        def _extract() -> dict[str, Any]:
            import yt_dlp

            opts: dict[str, Any] = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "socket_timeout": 15,
            }
            # Optional cookies from values for authenticated extract
            try:
                from core.managers.values import api as api_cfg

                cookie = api_cfg.instagram.cookie_header()
                if cookie:
                    # yt-dlp wants a cookie file; pass via http_headers instead
                    opts["http_headers"] = {"Cookie": cookie, "User-Agent": _UA}
            except Exception:
                pass
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False) or {}

        try:
            info = await asyncio.wait_for(asyncio.to_thread(_extract), timeout=18)
        except Exception as exc:
            log.debug("ytdlp ig failed: %s", exc)
            return None
        if not info:
            return None

        media: list[str] = []
        if info.get("url") and _looks_like_video(str(info["url"])):
            media.append(str(info["url"]))
        for fmt in info.get("formats") or []:
            u = fmt.get("url")
            if not u:
                continue
            vcodec = fmt.get("vcodec")
            if vcodec and vcodec != "none":
                media.append(str(u))
                break
        if not media:
            for fmt in sorted(
                info.get("formats") or [],
                key=lambda f: f.get("height") or 0,
                reverse=True,
            ):
                u = fmt.get("url")
                if u and _looks_like_video(str(u)):
                    media.append(str(u))
                    break

        username = (
            info.get("uploader_id")
            or info.get("channel")
            or info.get("uploader")
            or "unknown"
        )
        return SocialPost(
            platform="instagram",
            url=str(info.get("webpage_url") or url),
            username=str(username).lstrip("@"),
            display_name=str(info.get("uploader") or username),
            avatar_url=None,  # ytdlp thumb is usually poster, not pfp
            caption=str(info.get("description") or info.get("title") or "")[:2000],
            media_urls=media,
            is_video=bool(media),
            like_count=int(info.get("like_count") or 0),
            comment_count=int(info.get("comment_count") or 0),
            raw={"source": "ytdlp"},
        )

    @staticmethod
    def _merge(base: SocialPost, extra: SocialPost) -> SocialPost:
        def video_score(urls: list[str]) -> int:
            return sum(10 if _looks_like_video(u) else 1 for u in urls)

        # Prefer real video media over images
        if video_score(extra.media_urls) > video_score(base.media_urls):
            base.media_urls = list(extra.media_urls)
            base.is_video = extra.is_video or base.is_video
        elif not base.media_urls and extra.media_urls:
            # only take non-poster images if we still have nothing and not a video post
            if not base.is_video:
                base.media_urls = list(extra.media_urls)

        if base.username in ("", "unknown") and extra.username not in ("", "unknown"):
            base.username = extra.username
            base.display_name = extra.display_name or base.display_name

        # Prefer real profile pics over missing/poster
        if extra.avatar_url and (
            not base.avatar_url
            or "t51.71878" in (base.avatar_url or "")
            or "profile" in (extra.avatar_url or "").lower()
            or "t51.82787" in (extra.avatar_url or "")  # common profile path
        ):
            if "t51.71878" not in (extra.avatar_url or ""):
                base.avatar_url = extra.avatar_url

        if len(extra.caption or "") > len(base.caption or ""):
            base.caption = extra.caption
        for attr in ("like_count", "comment_count", "share_count", "save_count"):
            if not getattr(base, attr) and getattr(extra, attr):
                setattr(base, attr, getattr(extra, attr))
        if extra.is_video:
            base.is_video = True
        return base
