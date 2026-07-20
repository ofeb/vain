"""TikTok client — vain.rest primary, public scrapers as fallback.

Primary: ``GET /tiktok/video/{username}/{post_id}`` and ``/tiktok/profile/{username}``
Docs: https://vain.rest/docs
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional
from urllib.parse import quote, unquote, urlparse

import aiohttp

from .models import SocialPost

log = logging.getLogger("vain.social.tiktok")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_TT_HOSTS = re.compile(
    r"(?:https?://)?(?:(?:www|m|vm|vt)\.)?(?:tiktok\.com|tiktokv\.com)",
    re.I,
)
_VIDEO_ID_RE = re.compile(r"/video/(\d+)")
_PHOTO_ID_RE = re.compile(r"/photo/(\d+)")
_USER_RE = re.compile(r"tiktok\.com/@([^/?#]+)", re.I)
_SHORT_HOSTS = ("vm.tiktok.com", "vt.tiktok.com", "www.vm.tiktok.com", "www.vt.tiktok.com")


def is_tiktok_url(url: str) -> bool:
    return bool(_TT_HOSTS.search(url or ""))


class TikTok:
    """TikTok wrapper: resolve short links, fetch post/user info, get media URL."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._owns_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": _UA, "Accept": "application/json, text/plain, */*"},
                timeout=aiohttp.ClientTimeout(total=12),
            )
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def resolve_url(self, url: str) -> str:
        """Follow short-link redirects to a canonical tiktok.com URL."""
        url = (url or "").strip()
        if not url:
            return url
        if not url.startswith("http"):
            url = "https://" + url
        try:
            host = urlparse(url).netloc.lower()
        except Exception:
            return url
        if host not in _SHORT_HOSTS and "vm.tiktok.com" not in host and "vt.tiktok.com" not in host:
            return url
        session = await self._get_session()
        try:
            async with session.get(url, allow_redirects=True, max_redirects=8) as resp:
                return str(resp.url)
        except Exception as exc:
            log.debug("tiktok resolve failed: %s", exc)
            return url

    def parse_ids(self, url: str) -> dict[str, str | None]:
        video_id = None
        m = _VIDEO_ID_RE.search(url) or _PHOTO_ID_RE.search(url)
        if m:
            video_id = m.group(1)
        username = None
        um = _USER_RE.search(url)
        if um:
            username = unquote(um.group(1))
        return {"video_id": video_id, "username": username}

    async def post(self, url: str) -> Optional[SocialPost]:
        """Fetch full post metadata + media URL for a TikTok share link.

        Order: **vain.rest** → tikwm / yt-dlp / tikmate (parallel fallbacks).
        """
        resolved = await self.resolve_url(url)
        ids = self.parse_ids(resolved)

        
        primary = await self._from_vain_rest(resolved, ids)
        if primary and primary.media_urls:
            if ids.get("username") and primary.username == "unknown":
                primary.username = ids["username"] or primary.username
            if not primary.display_name:
                primary.display_name = primary.username
            primary.url = primary.url or resolved
            return primary

        
        tasks = [
            asyncio.create_task(self._from_tikwm(resolved)),
            asyncio.create_task(self._from_ytdlp(resolved)),
            asyncio.create_task(self._from_tikmate(resolved)),
        ]
        post: SocialPost | None = primary
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

                if post.media_urls and post.username and post.username != "unknown":
                    break
        except asyncio.TimeoutError:
            pass
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()

        if post is None and ids.get("video_id"):
            post = SocialPost(
                platform="tiktok",
                url=resolved,
                username=ids.get("username") or "unknown",
            )
        if post is None:
            return None

        post.url = post.url or resolved
        if ids.get("username") and post.username == "unknown":
            post.username = ids["username"] or post.username
        if not post.display_name:
            post.display_name = post.username
        return post

    async def _from_vain_rest(
        self,
        resolved: str,
        ids: dict[str, str | None],
    ) -> Optional[SocialPost]:
        """Primary path: GET /tiktok/video/{username}/{post_id}."""
        username = ids.get("username")
        post_id = ids.get("video_id")
        if not username or not post_id:
            return None
        try:
            from core.api import VainRest

            client = VainRest()
            video = await client.tiktok_video(username, post_id)
        except Exception as exc:
            log.debug("vain.rest tiktok video failed: %s", exc)
            return None

        author = video.author if isinstance(video.author, dict) else {}
        author_user = (
            str(author.get("username") or author.get("unique_id") or username).lstrip("@")
        )
        author_nick = (
            author.get("nickname")
            or author.get("nickName")
            or author.get("display_name")
            or author_user
        )
        avatar = (
            author.get("avatar_url")
            or author.get("avatar")
            or author.get("avatarLarger")
            or author.get("avatarThumb")
        )
        
        if (not avatar or author_nick == author_user) and author_user:
            try:
                from core.api import VainRest

                profile = await VainRest().tiktok_profile(author_user)
                if profile:
                    author_nick = profile.nickname or author_nick
                    if profile.avatar_url:
                        avatar = str(profile.avatar_url)
            except Exception as exc:
                log.debug("vain.rest tiktok profile enrich failed: %s", exc)

        media: list[str] = []
        if video.video_url:
            media.append(str(video.video_url))
        
        if not media and video.thumbnail_url:
            media.append(str(video.thumbnail_url))

        source = f"https://www.tiktok.com/@{author_user}/video/{post_id}"
        return SocialPost(
            platform="tiktok",
            url=source or resolved,
            username=author_user,
            display_name=str(author_nick),
            avatar_url=str(avatar) if avatar else None,
            caption=str(video.description or ""),
            media_urls=media,
            is_video=bool(video.video_url),
            like_count=int(video.likes_count or 0),
            comment_count=int(video.comments_count or 0),
            share_count=int(video.shares_count or 0),
            play_count=int(video.play_count or 0),
            raw={
                "source": "vain.rest",
                "id": video.id,
                "thumbnail_url": video.thumbnail_url,
                "create_time": video.create_time,
                "author": author,
            },
        )

    async def info(self, url: str) -> Optional[dict]:
        """Legacy dict interface."""
        post = await self.post(url)
        return post.raw if post and post.raw else (post.__dict__ if post else None)

    async def user(self, username: str) -> Optional[dict]:
        """Best-effort public profile lookup — vain.rest first."""
        username = (username or "").strip().lstrip("@")
        if not username:
            return None

        try:
            from core.api import VainRest

            profile = await VainRest().tiktok_profile(username)
            return {
                "uniqueId": profile.username,
                "nickname": profile.nickname or profile.username,
                "avatarLarger": str(profile.avatar_url) if profile.avatar_url else "",
                "avatar": str(profile.avatar_url) if profile.avatar_url else "",
                "signature": profile.bio,
                "followerCount": profile.followers_count,
                "followingCount": profile.following_count,
                "heartCount": profile.likes_count,
                "videoCount": profile.videos_count,
                "verified": profile.is_verified,
                "id": profile.id,
                "source": "vain.rest",
            }
        except Exception as exc:
            log.debug("vain.rest tiktok profile failed: %s", exc)

        session = await self._get_session()
        try:
            async with session.get(
                "https://www.tikwm.com/api/user/info",
                params={"unique_id": username},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if isinstance(data, dict) and data.get("code") == 0:
                        user = (data.get("data") or {}).get("user") or data.get("data") or {}
                        if user:
                            return user
        except Exception as exc:
            log.debug("tikwm user failed: %s", exc)

        try:
            async with session.get(f"https://www.tiktok.com/@{quote(username)}") as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
                nick = re.search(r'"nickname":"([^"]+)"', html)
                av = re.search(r'"avatarLarger":"([^"]+)"', html)
                return {
                    "uniqueId": username,
                    "nickname": nick.group(1) if nick else username,
                    "avatarLarger": (av.group(1).encode().decode("unicode_escape") if av else ""),
                }
        except Exception:
            return None

    async def _from_tikwm(self, url: str) -> Optional[SocialPost]:
        session = await self._get_session()
        try:
            async with session.post(
                "https://www.tikwm.com/api/",
                data={"url": url, "hd": "1"},
                headers={
                    "User-Agent": _UA,
                    "Referer": "https://www.tikwm.com/",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            ) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json(content_type=None)
        except Exception as exc:
            log.debug("tikwm failed: %s", exc)
            return None

        if not isinstance(payload, dict):
            return None
        
        if payload.get("code") not in (0, "0"):
            return None
        data = payload.get("data") or {}
        if not isinstance(data, dict) or not data:
            return None

        author = data.get("author") or {}
        music = data.get("music_info") or data.get("music") or {}
        media: list[str] = []
        for key in ("hdplay", "play", "wmplay", "download"):
            val = data.get(key)
            if isinstance(val, str) and val.startswith("http"):
                media.append(val)
                break
        images = data.get("images")
        if isinstance(images, list):
            media.extend(u for u in images if isinstance(u, str) and u.startswith("http"))

        if not media and not author:
            return None

        username = (
            author.get("unique_id")
            or author.get("uniqueId")
            or data.get("author_unique_id")
            or "unknown"
        )
        display = author.get("nickname") or author.get("nickName") or username
        avatar = (
            author.get("avatar")
            or author.get("avatarThumb")
            or author.get("avatarMedium")
            or None
        )
        music_title = music.get("title") or data.get("music")
        music_author = music.get("author") or music.get("authorName")
        mid = music.get("id") or music.get("mid")
        music_url = f"https://www.tiktok.com/music/original-sound-{mid}" if mid else None

        return SocialPost(
            platform="tiktok",
            url=data.get("play_url") or url,
            username=str(username).lstrip("@"),
            display_name=str(display),
            avatar_url=avatar,
            caption=str(data.get("title") or data.get("desc") or ""),
            media_urls=media,
            is_video=not bool(images),
            like_count=int(data.get("digg_count") or data.get("diggCount") or 0),
            comment_count=int(data.get("comment_count") or data.get("commentCount") or 0),
            share_count=int(data.get("share_count") or data.get("shareCount") or 0),
            save_count=int(data.get("collect_count") or data.get("collectCount") or 0),
            play_count=int(data.get("play_count") or data.get("playCount") or 0),
            music_title=str(music_title) if music_title else None,
            music_author=str(music_author) if music_author else None,
            music_url=music_url,
            region=data.get("region") or data.get("location_created"),
            raw=data if isinstance(data, dict) else {},
        )

    async def _from_tikmate(self, url: str) -> Optional[SocialPost]:
        session = await self._get_session()
        try:
            async with session.post(
                "https://api.tikmate.app/api/lookup",
                data={"url": url},
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
        except Exception as exc:
            log.debug("tikmate failed: %s", exc)
            return None
        if not isinstance(data, dict) or data.get("success") is False:
            return None
        token = data.get("token")
        vid = data.get("id")
        media: list[str] = []
        if token and vid:
            media.append(f"https://tikmate.app/download/{token}/{vid}.mp4")
        return SocialPost(
            platform="tiktok",
            url=url,
            username=str(data.get("author_id") or data.get("author") or "unknown").lstrip("@"),
            display_name=str(data.get("author_name") or data.get("author_id") or ""),
            avatar_url=data.get("author_avatar"),
            caption=str(data.get("desc") or data.get("title") or ""),
            media_urls=media,
            is_video=True,
            like_count=int(data.get("like_count") or 0),
            comment_count=int(data.get("comment_count") or 0),
            share_count=int(data.get("share_count") or 0),
            raw=data,
        )

    async def _from_ytdlp(self, url: str) -> Optional[SocialPost]:
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
            log.debug("ytdlp tiktok failed: %s", exc)
            return None
        if not info:
            return None

        media: list[str] = []
        if info.get("url"):
            media.append(str(info["url"]))
        for fmt in info.get("formats") or []:
            u = fmt.get("url")
            if u and "http" in u and fmt.get("vcodec") not in (None, "none"):
                media.append(u)
                break

        username = (
            info.get("uploader_id")
            or info.get("channel_id")
            or info.get("creator")
            or info.get("uploader")
            or "unknown"
        )
        if isinstance(username, str):
            username = username.lstrip("@")

        thumbs = info.get("thumbnails") or []
        avatar = None
        if thumbs:
            avatar = thumbs[-1].get("url")
        thumb = info.get("thumbnail")

        return SocialPost(
            platform="tiktok",
            url=str(info.get("webpage_url") or url),
            username=str(username),
            display_name=str(info.get("uploader") or info.get("creator") or username),
            avatar_url=avatar or thumb,
            caption=str(info.get("description") or info.get("title") or ""),
            media_urls=media,
            is_video=True,
            like_count=int(info.get("like_count") or 0),
            comment_count=int(info.get("comment_count") or 0),
            share_count=int(info.get("repost_count") or 0),
            play_count=int(info.get("view_count") or 0),
            music_title=info.get("track") or info.get("alt_title"),
            music_author=info.get("artist") or info.get("creator"),
            raw=info,
        )

    @staticmethod
    def _merge(base: SocialPost, extra: SocialPost) -> SocialPost:
        if not base.media_urls and extra.media_urls:
            base.media_urls = extra.media_urls
        if base.username in ("", "unknown") and extra.username not in ("", "unknown"):
            base.username = extra.username
            base.display_name = extra.display_name or base.display_name
        if not base.avatar_url and extra.avatar_url:
            base.avatar_url = extra.avatar_url
        if not base.caption and extra.caption:
            base.caption = extra.caption
        for attr in ("like_count", "comment_count", "share_count", "save_count", "play_count"):
            if not getattr(base, attr) and getattr(extra, attr):
                setattr(base, attr, getattr(extra, attr))
        if not base.music_title and extra.music_title:
            base.music_title = extra.music_title
            base.music_author = extra.music_author
            base.music_url = extra.music_url
        if not base.region and extra.region:
            base.region = extra.region
        return base
