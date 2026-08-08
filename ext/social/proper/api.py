"""Social content API client (scl.guilt.bot - socials-main route shape).

Base: https://scl.guilt.bot (override with ``config.api.social_base``).
No API key required. Optional Cloudflare Access service-token headers via
``config.api.social_cf_client_id`` / ``social_cf_client_secret``.

Routes used:
  Instagram, TikTok, Twitter/X, YouTube, Telegram,
  Twitch, Snapchat, Pinterest, Brave, Google
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import quote, urlparse

import aiohttp

from config import api as api_cfg
from core.networks.social.models import SocialPost

log = logging.getLogger("vain.social.api")

_IG_SHORT_RE = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv|reels)/(?P<code>[\w-]+)",
    re.I,
)
_TT_ID_RE = re.compile(r"/(?:video|photo)/(\d+)")
_TT_USER_RE = re.compile(r"tiktok\.com/@([^/?#]+)", re.I)
_X_STATUS_RE = re.compile(
    r"(?:twitter\.com|x\.com)/(?:#!/)?(?:i/web/status|(?:[\w_]+)/status)/(\d+)",
    re.I,
)
_X_USER_RE = re.compile(
    r"(?:twitter\.com|x\.com)/(?:#!/)?@?([A-Za-z0-9_]{1,15})(?:/|$|\?)",
    re.I,
)
_YT_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/|live/)|youtube\.com/v/)([\w-]{11})",
    re.I,
)
_YT_HANDLE_RE = re.compile(r"youtube\.com/@([\w.-]+)", re.I)


def _base() -> str:
    return (getattr(api_cfg, "social_base", None) or getattr(api_cfg, "guilt_base", None) or "https://scl.guilt.bot").rstrip("/")


def _headers() -> dict[str, str]:
    """Match Scalar/OpenAPI client: Accept application/json + optional CF Access.

    Working browser/Scalar requests only need ``Accept: application/json``.
    CF service-token headers are attached when configured (server-to-server).
    """
    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    client_id = (
        getattr(api_cfg, "social_cf_client_id", None)
        or getattr(api_cfg, "cf_access_client_id", None)
        or ""
    ).strip()
    client_secret = (
        getattr(api_cfg, "social_cf_client_secret", None)
        or getattr(api_cfg, "cf_access_client_secret", None)
        or ""
    ).strip()
    if client_id and client_secret:
        
        headers["CF-Access-Client-Id"] = client_id
        headers["CF-Access-Client-Secret"] = client_secret
    return headers


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        raw = value.strip().replace(",", "").replace(" ", "")
        mult = 1
        if raw.lower().endswith("k"):
            mult = 1_000
            raw = raw[:-1]
        elif raw.lower().endswith("m"):
            mult = 1_000_000
            raw = raw[:-1]
        try:
            return int(float(raw) * mult)
        except Exception:
            return 0
    if isinstance(value, dict):
        for k in ("count", "value", "amount"):
            if k in value:
                return _as_int(value.get(k))
    return 0


def _first_present(*values: Any) -> Any:
    """Return the first value that is not None (0 is valid)."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _first_str(*values: Any) -> str:
    for v in values:
        if v is None:
            continue
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
        if isinstance(v, dict):
            nested = _first_str(
                v.get("text"),
                v.get("username"),
                v.get("uniqueId"),
                v.get("unique_id"),
                v.get("screen_name"),
                v.get("name"),
                v.get("url"),
            )
            if nested:
                return nested
        if isinstance(v, list):
            for item in v:
                nested = _first_str(item)
                if nested:
                    return nested
    return ""


def _dict(*values: Any) -> dict:
    for v in values:
        if isinstance(v, dict) and v:
            return v
    return {}


def _unwrap(data: dict, *keys: str) -> dict:
    """Prefer first nested dict under *keys* that looks populated."""
    if not isinstance(data, dict):
        return {}
    for key in keys:
        inner = data.get(key)
        if isinstance(inner, dict) and inner:
            return inner
    return data


def _pick_url(*values: Any) -> str | None:
    for v in values:
        if isinstance(v, str) and v.startswith("http"):
            return v
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str) and item.startswith("http"):
                    return item
                if isinstance(item, dict):
                    u = _pick_url(
                        item.get("url"),
                        item.get("playAddr"),
                        item.get("play_addr"),
                        item.get("downloadAddr"),
                        item.get("download_addr"),
                        item.get("play"),
                        item.get("src"),
                    )
                    if u:
                        return u
        if isinstance(v, dict):
            u = _pick_url(
                v.get("url"),
                v.get("playAddr"),
                v.get("play_addr"),
                v.get("downloadAddr"),
                v.get("download_addr"),
                v.get("play"),
                v.get("hdplay"),
                v.get("urlList"),
                v.get("url_list"),
                v.get("src"),
                v.get("image_url"),
                v.get("profile_pic_url"),
            )
            if u:
                return u
    return None


def _url_list(*values: Any) -> list[str]:
    out: list[str] = []

    def _walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, str) and node.startswith("http"):
            if node not in out:
                out.append(node)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return
        if isinstance(node, dict):
            for key in (
                "url",
                "urls",
                "urlList",
                "playAddr",
                "downloadAddr",
                "play",
                "hdplay",
                "wmplay",
                "display_url",
                "video_url",
                "candidates",
            ):
                if key in node:
                    _walk(node.get(key))
            
            for key in (
                "image_versions2",
                "video_versions",
                "video",
                "imagePostInfo",
                "displayImages",
                "carousel_media",
            ):
                if key in node:
                    _walk(node.get(key))

    for v in values:
        _walk(v)
    return out


async def api_get(
    path: str,
    *,
    params: dict | None = None,
    timeout: float = 25.0,
) -> Any | None:
    """GET JSON from scl.guilt.bot. Returns None on any failure.

    Routes are under ``/api/...`` (OpenAPI). Auth is optional CF Access
    service-token headers when configured; browser/Scalar sessions that already
    hold an Access cookie do not need them.
    """
    url = f"{_base()}{path if path.startswith('/') else '/' + path}"
    try:
        async with aiohttp.ClientSession(headers=_headers()) as session:
            async with session.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
                max_redirects=5,
            ) as resp:
                if resp.status == 401 or resp.status == 403:
                    body = ""
                    try:
                        body = (await resp.text())[:180]
                    except Exception:
                        pass
                    log.debug("social-api %s auth %s %s", path, resp.status, body)
                    return None
                if resp.status != 200:
                    body = ""
                    try:
                        body = (await resp.text())[:180]
                    except Exception:
                        pass
                    log.debug("social-api %s -> %s %s", path, resp.status, body)
                    return None
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "json" in ctype:
                    return await resp.json(content_type=None)

                text = await resp.text()
                text = (text or "").strip()
                if text.startswith(("{", "[")):
                    import json

                    try:
                        return json.loads(text)
                    except Exception:
                        return None
                return None
    except Exception as exc:
        log.debug("social-api error %s: %s", path, exc)
        return None


def _username_from_url(url: str, platform: str) -> str:
    """Best-effort handle extraction from a share URL."""
    u = url or ""
    plat = (platform or "").lower()
    if plat == "tiktok":
        m = _TT_USER_RE.search(u)
        return (m.group(1) if m else "").lstrip("@")
    if plat == "instagram":
        m = re.search(r"instagram\.com/([A-Za-z0-9._]+)/?", u, re.I)
        if m and m.group(1).lower() not in {"p", "reel", "reels", "tv", "stories", "explore"}:
            return m.group(1)
        return ""
    if plat in {"twitter", "x"}:
        m = _X_USER_RE.search(u)
        handle = (m.group(1) if m else "").lstrip("@")
        if handle.lower() in {"i", "intent", "share", "home", "explore", "search"}:
            return ""
        return handle
    if plat == "youtube":
        m = _YT_HANDLE_RE.search(u)
        return (m.group(1) if m else "").lstrip("@")
    if plat == "twitch":
        m = re.search(r"twitch\.tv/([A-Za-z0-9_]+)", u, re.I)
        if m and m.group(1).lower() not in {"videos", "clips", "directory", "downloads"}:
            return m.group(1)
    if plat == "snapchat":
        m = re.search(r"snapchat\.com/add/([A-Za-z0-9._-]+)", u, re.I)
        return m.group(1) if m else ""
    if plat == "pinterest":
        m = re.search(r"pinterest\.[^/]+/([A-Za-z0-9._-]+)/?", u, re.I)
        return m.group(1) if m else ""
    return ""


def enrich_social_post(post: SocialPost | None, *, source_url: str = "") -> SocialPost | None:
    """Backfill username/display from URL / raw when parsers leave gaps."""
    if post is None:
        return None
    plat = (post.platform or "").lower()
    url = source_url or post.url or ""
    if (not post.username or post.username == "unknown") and url:
        derived = _username_from_url(url, plat)
        if derived:
            post.username = derived
    if not post.display_name or post.display_name in {"", "unknown"}:
        post.display_name = post.username if post.username != "unknown" else ""
    raw = post.raw if isinstance(post.raw, dict) else {}
    if (not post.avatar_url) and raw:
        post.avatar_url = _pick_url(
            raw.get("avatar"),
            raw.get("avatar_url"),
            raw.get("profile_pic_url"),
            raw.get("profile_image_url"),
            (raw.get("user") or {}).get("profile_pic_url") if isinstance(raw.get("user"), dict) else None,
            (raw.get("author") or {}).get("avatarLarger") if isinstance(raw.get("author"), dict) else None,
            (raw.get("author") or {}).get("avatar_larger") if isinstance(raw.get("author"), dict) else None,
        )
    return post







async def instagram_user(username: str) -> Optional[dict]:
    data = await api_get(f"/api/instagram/{quote(username.lstrip('@'))}")
    return data if isinstance(data, dict) else None


async def instagram_post(shortcode: str) -> Optional[dict]:
    data = await api_get(f"/api/instagram/p/{quote(shortcode)}")
    return data if isinstance(data, dict) else None


async def instagram_trending(*, count: int = 4, seen: bool = True) -> list[dict]:
    data = await api_get(
        "/api/instagram/trending",
        params={"count": max(1, min(int(count), 12)), "seen": str(bool(seen)).lower()},
    )
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("posts", "items", "data", "results"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


async def instagram_user_posts(username: str, *, count: int = 12) -> list[dict]:
    data = await api_get(
        f"/api/instagram/{quote(username.lstrip('@'))}/posts",
        params={"count": max(1, min(int(count), 24))},
    )
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("posts", "items", "data", "results"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


async def instagram_user_stories(username: str) -> list[dict]:
    data = await api_get(f"/api/instagram/{quote(username.lstrip('@'))}/stories")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


async def instagram_user_highlights(username: str) -> list[dict]:
    data = await api_get(f"/api/instagram/{quote(username.lstrip('@'))}/highlights")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("highlights", "items", "data", "results"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


async def instagram_highlight(highlight_id: str) -> list[dict]:
    data = await api_get(f"/api/instagram/highlights/{quote(str(highlight_id))}")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "stories", "data", "results"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


def instagram_shortcode_from_url(url: str) -> str | None:
    m = _IG_SHORT_RE.search(url or "")
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


def parse_instagram_post(data: dict, *, source_url: str = "") -> SocialPost | None:
    """Normalize guilt / socials-main Instagram post payload → SocialPost."""
    if not isinstance(data, dict) or not data:
        return None

    post = data
    for key in ("post", "item", "media", "data", "result"):
        inner = data.get(key)
        if isinstance(inner, dict) and (
            inner.get("code")
            or inner.get("pk")
            or inner.get("user")
            or inner.get("caption")
            or inner.get("shortcode")
        ):
            post = inner
            break

    user = _dict(
        post.get("user"),
        post.get("owner"),
        post.get("author"),
        data.get("user"),
    )
    username = _first_str(
        user.get("username"),
        user.get("unique_id"),
        post.get("username"),
        post.get("author_name"),
        post.get("owner_username"),
        _username_from_url(source_url, "instagram"),
        "unknown",
    ).lstrip("@")
    display = _first_str(
        user.get("full_name"),
        user.get("fullName"),
        user.get("name"),
        post.get("full_name"),
        username,
    )
    avatar = _pick_url(
        user.get("profile_pic_url"),
        user.get("profile_pic_url_hd"),
        user.get("hd_profile_pic_url_info"),
        user.get("profilePicUrl"),
        user.get("profile_pic_url_info"),
        post.get("avatar"),
    )

    caption_obj = post.get("caption")
    if isinstance(caption_obj, dict):
        caption = _first_str(caption_obj.get("text"), caption_obj.get("caption"))
    else:
        caption = _first_str(
            caption_obj,
            post.get("text"),
            post.get("title"),
            post.get("clean_caption"),
        )

    code = _first_str(post.get("code"), post.get("shortcode"), post.get("id"))
    product = str(post.get("product_type") or "").lower()
    media_type = post.get("media_type")
    is_reel = "reel" in product or "clip" in product or "/reel" in (source_url or "").lower()

    media_urls: list[str] = []
    
    carousel = post.get("carousel_media") or post.get("all_media_urls")
    if isinstance(carousel, list) and carousel:
        if all(isinstance(x, str) for x in carousel):
            media_urls.extend(u for u in carousel if u.startswith("http"))
        else:
            for item in carousel:
                if not isinstance(item, dict):
                    continue
                v = _pick_url(item.get("video_url"), item.get("video_versions"), item.get("video"))
                if v:
                    media_urls.append(v)
                    continue
                img = _pick_url(
                    item.get("display_url"),
                    item.get("image_versions2"),
                    item.get("image"),
                )
                if img:
                    media_urls.append(img)
    
    video_url = _pick_url(
        post.get("video_url"),
        post.get("video_versions"),
        post.get("video"),
    )
    if video_url and video_url not in media_urls:
        media_urls.insert(0, video_url)
    
    image_url = _pick_url(
        post.get("display_url"),
        post.get("image_versions2"),
        post.get("thumbnail_url"),
        post.get("image"),
    )
    if image_url and image_url not in media_urls and not video_url:
        media_urls.append(image_url)
    
    if not media_urls:
        media_urls = _url_list(post)[:12]

    is_video = bool(video_url) or is_reel or media_type in (2, "2", "video")

    if code:
        clean = (
            f"https://www.instagram.com/reel/{code}/"
            if is_reel
            else f"https://www.instagram.com/p/{code}/"
        )
    else:
        clean = source_url or f"https://www.instagram.com/{username}/"

    likes = _as_int(
        post.get("like_count")
        or post.get("likes")
        or post.get("likeCount")
        or (post.get("edge_liked_by") or {}).get("count")
    )
    comments = _as_int(
        post.get("comment_count")
        or post.get("comments")
        or post.get("commentCount")
        or (post.get("edge_media_to_comment") or {}).get("count")
    )

    music_title = None
    music_author = None
    clips = post.get("clips_metadata") or post.get("clipsMetadata") or {}
    if isinstance(clips, dict):
        mi = clips.get("music_info") or clips.get("musicInfo") or {}
        if isinstance(mi, dict):
            music_title = _first_str(mi.get("title"), mi.get("music_title")) or None
            music_author = (
                _first_str(mi.get("artist_name"), mi.get("display_artist"), mi.get("artist"))
                or None
            )
        osi = clips.get("original_sound_info") or {}
        if isinstance(osi, dict) and not music_title:
            music_title = _first_str(osi.get("original_audio_title"), "Original audio") or None

    return enrich_social_post(
        SocialPost(
            platform="instagram",
            url=clean,
            username=username or "unknown",
            display_name=display or username or "unknown",
            avatar_url=avatar,
            caption=caption[:2000],
            media_urls=list(dict.fromkeys(media_urls)),
            is_video=is_video and bool(video_url or is_reel),
            like_count=likes,
            comment_count=comments,
            music_title=music_title,
            music_author=music_author,
            raw={**post, "source": "social-api", "code": code},
        ),
        source_url=source_url or clean,
    )


def parse_instagram_user(data: dict, *, username: str = "") -> dict | None:
    if not isinstance(data, dict):
        return None
    user = _unwrap(data, "user", "data", "result", "profile")
    if not isinstance(user, dict):
        return None
    
    uname = _first_str(
        user.get("username"),
        data.get("username"),
        username,
    ).lstrip("@")
    if not uname:
        return None
    return {
        "username": uname,
        "full_name": _first_str(
            user.get("full_name"),
            user.get("fullName"),
            user.get("name"),
            uname,
        ),
        "bio": _first_str(
            user.get("biography"),
            user.get("bio"),
            user.get("signature"),
            user.get("about"),
        ),
        "followers": _as_int(
            user.get("follower_count")
            or user.get("followers")
            or user.get("followerCount")
            or (user.get("edge_followed_by") or {}).get("count")
        ),
        "following": _as_int(
            user.get("following_count")
            or user.get("following")
            or user.get("followingCount")
            or (user.get("edge_follow") or {}).get("count")
        ),
        "posts": _as_int(
            user.get("media_count")
            or user.get("posts")
            or user.get("mediaCount")
            or (user.get("edge_owner_to_timeline_media") or {}).get("count")
        ),
        "is_private": bool(
            user.get("is_private") or user.get("isPrivate") or user.get("private")
        ),
        "is_verified": bool(
            user.get("is_verified") or user.get("isVerified") or user.get("verified")
        ),
        "avatar": _pick_url(
            user.get("profile_pic_url_hd"),
            user.get("hd_profile_pic_url_info"),
            user.get("profile_pic_url"),
            user.get("profilePicUrl"),
            user.get("avatar"),
            user.get("profile_pic_url_info"),
        )
        or "",
        "pk": _first_str(user.get("pk"), user.get("id"), user.get("user_id")),
    }







async def tiktok_user(username: str) -> Optional[dict]:
    data = await api_get(f"/api/tiktok/{quote(username.lstrip('@'))}")
    return data if isinstance(data, dict) else None


async def tiktok_item(item_id: str) -> Optional[dict]:
    data = await api_get(f"/api/tiktok/p/{quote(str(item_id))}")
    return data if isinstance(data, dict) else None


async def tiktok_shortcode(code: str) -> Optional[dict]:
    data = await api_get(f"/api/tiktok/shortcode/{quote(code)}")
    return data if isinstance(data, dict) else None


async def tiktok_fyp(*, limit: int = 10, region: str | None = None) -> list[dict]:
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 20))}
    if region:
        params["region"] = region[:2].upper()
    data = await api_get("/api/tiktok/fyp", params=params, timeout=40.0)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "posts", "data", "results"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


async def tiktok_user_posts(username: str, *, limit: int = 12) -> list[dict]:
    data = await api_get(
        f"/api/tiktok/{quote(username.lstrip('@'))}/posts",
        params={"limit": max(1, min(int(limit), 20))},
    )
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "posts", "data", "results"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


async def tiktok_user_reposts(username: str, *, limit: int = 12) -> list[dict]:
    data = await api_get(
        f"/api/tiktok/{quote(username.lstrip('@'))}/reposts",
        params={"limit": max(1, min(int(limit), 20))},
    )
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "posts", "data", "results"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


def parse_tiktok_post(data: dict, *, source_url: str = "") -> SocialPost | None:
    """Normalize guilt TikTok Video/Photo/Story payload → SocialPost.

    OpenAPI shapes:
      - Video: { itemInfos, authorInfos, musicInfos, ... }
      - flat: { author: User{unique_id,nickname,avatar_larger}, video, stats, ... }
    """
    if not isinstance(data, dict) or not data:
        return None

    post = data
    for key in ("item", "data", "result", "aweme", "aweme_detail", "post"):
        inner = post.get(key)
        if isinstance(inner, dict) and (
            inner.get("itemInfos")
            or inner.get("authorInfos")
            or inner.get("author")
            or inner.get("id")
            or inner.get("desc")
        ):
            post = inner
            break

    item = _dict(post.get("itemInfos"), post.get("item_infos"))
    author_infos = _dict(post.get("authorInfos"), post.get("author_infos"), post.get("authorMeta"))
    author = _dict(post.get("author"), post.get("authorInfo"), post.get("creator"))
    video_block = _dict(post.get("video"), item.get("video") if item else None)
    stats = _dict(post.get("stats"), post.get("statistics"), post.get("authorStats"))
    music = _dict(post.get("music"), post.get("musicInfo"))
    music_infos = _dict(post.get("musicInfos"), post.get("music_infos"))

    post_id = _first_str(
        item.get("id") if item else None,
        post.get("id"),
        post.get("aweme_id"),
        video_block.get("id"),
    )
    caption = _first_str(
        item.get("text") if item else None,
        post.get("desc"),
        post.get("caption"),
        post.get("title"),
        post.get("text"),
    )
    likes = _as_int(
        (item.get("diggCount") if item else None)
        or (item.get("digg_count") if item else None)
        or stats.get("diggCount")
        or stats.get("digg_count")
        or post.get("digg_count")
        or post.get("like_count")
        or post.get("likes")
    )
    comments = _as_int(
        (item.get("commentCount") if item else None)
        or (item.get("comment_count") if item else None)
        or stats.get("commentCount")
        or post.get("comment_count")
        or post.get("comments")
    )
    shares = _as_int(
        (item.get("shareCount") if item else None)
        or stats.get("shareCount")
        or post.get("share_count")
        or post.get("shares")
    )
    plays = _as_int(
        (item.get("playCount") if item else None)
        or stats.get("playCount")
        or post.get("play_count")
        or post.get("plays")
        or post.get("view_count")
    )
    saves = _as_int(
        stats.get("collectCount")
        or stats.get("collect_count")
        or post.get("collect_count")
        or post.get("saves")
    )

    video_urls = _url_list(
        video_block.get("urls"),
        video_block.get("playAddr"),
        video_block.get("play_addr"),
        video_block.get("downloadAddr"),
        video_block.get("download_addr"),
        post.get("video_url"),
        post.get("download_url"),
        post.get("play"),
        post.get("hdplay"),
        post.get("wmplay"),
        item.get("video") if item else None,
    )
    images = _url_list(
        post.get("imagePostInfo"),
        post.get("image_post_info"),
        post.get("images"),
        post.get("image_urls"),
    )
    media_urls = list(dict.fromkeys([*video_urls, *images]))
    cover = _pick_url(
        video_block.get("cover"),
        video_block.get("originCover"),
        video_block.get("origin_cover"),
        post.get("thumbnail"),
        post.get("cover"),
        post.get("dynamicCover"),
    )
    is_video = bool(video_urls) and not images
    if not media_urls and cover:
        media_urls = [cover]
        is_video = False

    username = _first_str(
        author_infos.get("uniqueId"),
        author_infos.get("unique_id"),
        author.get("uniqueId"),
        author.get("unique_id"),
        author.get("username"),
        author.get("uniqueId"),
        post.get("username"),
        post.get("unique_id"),
        post.get("author_unique_id"),
        _username_from_url(source_url, "tiktok"),
        "unknown",
    ).lstrip("@")
    display = _first_str(
        author_infos.get("nickName"),
        author_infos.get("nickname"),
        author.get("nickname"),
        author.get("nickName"),
        author.get("nick_name"),
        author.get("display_name"),
        post.get("nickname"),
        username,
    )
    avatar = _pick_url(
        author_infos.get("coversLarger"),
        author_infos.get("coversMedium"),
        author_infos.get("covers"),
        author.get("avatarLarger"),
        author.get("avatar_larger"),
        author.get("avatarMedium"),
        author.get("avatar_medium"),
        author.get("avatarThumb"),
        author.get("avatar_thumb"),
        author.get("avatar"),
        author.get("coversLarger"),
        post.get("avatar"),
    )

    music_title = (
        _first_str(
            music_infos.get("musicName"),
            music_infos.get("title"),
            music.get("title"),
            music.get("musicName"),
            music.get("music_name"),
        )
        or None
    )
    music_author = (
        _first_str(
            music_infos.get("authorName"),
            music_infos.get("author"),
            music.get("authorName"),
            music.get("author_name"),
            music.get("author"),
        )
        or None
    )
    mid = _first_str(
        music_infos.get("musicId"),
        music_infos.get("id"),
        music.get("id"),
        music.get("musicId"),
        music.get("mid"),
    )

    kind = "photo" if (not is_video and media_urls) else "video"
    if post_id and username and username != "unknown":
        clean = f"https://www.tiktok.com/@{username}/{kind}/{post_id}"
    else:
        clean = source_url or (f"https://www.tiktok.com/@{username}" if username else "")

    music_url = f"https://www.tiktok.com/music/original-sound-{mid}" if mid else None

    return enrich_social_post(
        SocialPost(
            platform="tiktok",
            url=clean,
            username=username or "unknown",
            display_name=display or username or "unknown",
            avatar_url=avatar,
            caption=caption[:2000],
            media_urls=list(dict.fromkeys(media_urls)),
            is_video=bool(is_video),
            like_count=likes,
            comment_count=comments,
            share_count=shares,
            save_count=saves,
            play_count=plays,
            music_title=music_title,
            music_author=music_author,
            music_url=music_url,
            region=_first_str(post.get("region"), post.get("location_created")) or None,
            raw={**post, "source": "social-api", "id": post_id},
        ),
        source_url=source_url or clean,
    )


def parse_tiktok_user(data: dict, *, username: str = "") -> dict | None:
    """Parse TikTok User schema (unique_id / nickname / avatar_larger).

    Live Scalar shape is flat::
      { id, unique_id, nickname, avatar_larger, followers, following, likes, videos,
        verified, private_account, secret, ... }

    Also accepts nested shapes::
      { userInfo: { user: {...}, stats: {...} } }
      { data: { user: {...}, stats: {...} } }
    """
    if not isinstance(data, dict):
        return None

    def _looks_like_user(obj: Any) -> bool:
        if not isinstance(obj, dict):
            return False
        return bool(
            obj.get("unique_id")
            or obj.get("uniqueId")
            or obj.get("username")
            or obj.get("nickname")
            or obj.get("nickName")
            or obj.get("secUid")
            or obj.get("sec_uid")
        )

    stats_from_parent: dict = {}
    user: dict = data

    
    for key in ("userInfo", "user_info", "data", "result", "author", "user"):
        inner = data.get(key)
        if not isinstance(inner, dict) or not inner:
            continue
        
        nested_user = inner.get("user") if isinstance(inner.get("user"), dict) else None
        if nested_user and _looks_like_user(nested_user):
            stats_from_parent = _dict(
                inner.get("stats"),
                inner.get("statsV2"),
                inner.get("statistics"),
                data.get("stats"),
                data.get("statsV2"),
            )
            user = nested_user
            break
        
        if _looks_like_user(inner):
            stats_from_parent = _dict(
                data.get("stats"),
                data.get("statsV2"),
                inner.get("stats"),
                inner.get("statsV2"),
            )
            user = inner
            break

    
    nested = user.get("user") if isinstance(user.get("user"), dict) else None
    if nested and _looks_like_user(nested):
        stats_from_parent = _dict(
            user.get("stats"),
            user.get("statsV2"),
            stats_from_parent,
            data.get("stats"),
        )
        user = nested

    stats = _dict(
        data.get("stats"),
        data.get("statsV2"),
        user.get("stats"),
        user.get("statsV2"),
        stats_from_parent,
    )

    uname = _first_str(
        user.get("uniqueId"),
        user.get("unique_id"),
        user.get("username"),
        data.get("unique_id"),
        data.get("uniqueId"),
        username,
    ).lstrip("@")
    if not uname:
        return None
    return {
        "uniqueId": uname,
        "nickname": _first_str(
            user.get("nickname"),
            user.get("nickName"),
            user.get("nick_name"),
            data.get("nickname"),
            uname,
        ),
        "avatarLarger": _pick_url(
            user.get("avatarLarger"),
            user.get("avatar_larger"),
            data.get("avatar_larger"),
            user.get("avatarMedium"),
            user.get("avatar_medium"),
            data.get("avatar_medium"),
            user.get("avatarThumb"),
            user.get("avatar_thumb"),
            data.get("avatar_thumb"),
            user.get("avatar"),
            user.get("coversLarger"),
        )
        or "",
        "signature": _first_str(
            user.get("signature"),
            data.get("signature"),
            user.get("bio"),
            user.get("desc"),
        ),
        "followerCount": _as_int(
            _first_present(
                user.get("followerCount"),
                user.get("followers"),
                data.get("followers"),
                data.get("followerCount"),
                user.get("follower_count"),
                stats.get("followerCount"),
                stats.get("follower_count"),
                stats.get("followers"),
            )
        ),
        "followingCount": _as_int(
            _first_present(
                user.get("followingCount"),
                user.get("following"),
                data.get("following"),
                data.get("followingCount"),
                user.get("following_count"),
                stats.get("followingCount"),
                stats.get("following_count"),
                stats.get("following"),
            )
        ),
        "heartCount": _as_int(
            _first_present(
                user.get("heart"),
                user.get("heartCount"),
                user.get("heart_count"),
                data.get("heart_count"),
                data.get("heartCount"),
                user.get("likes"),
                data.get("likes"),
                user.get("digg_count"),
                data.get("digg_count"),
                stats.get("heart"),
                stats.get("heartCount"),
                stats.get("diggCount"),
                stats.get("likes"),
            )
        ),
        "videoCount": _as_int(
            _first_present(
                user.get("videoCount"),
                user.get("videos"),
                data.get("videos"),
                data.get("videoCount"),
                user.get("video_count"),
                stats.get("videoCount"),
                stats.get("video_count"),
                stats.get("videos"),
            )
        ),
        "verified": bool(
            user.get("verified")
            or data.get("verified")
            or user.get("is_verified")
        ),
        "is_private": bool(
            user.get("privateAccount")
            or user.get("private_account")
            or data.get("private_account")
            or user.get("secret")
            or data.get("secret")
            or user.get("isPrivate")
            or user.get("is_private")
            or user.get("private")
        ),
        "id": _first_str(user.get("id"), data.get("id"), user.get("userId"), user.get("user_id")),
        "source": "social-api",
    }







async def twitter_user(username: str) -> Optional[dict]:
    data = await api_get(f"/api/twitter/{quote(username.lstrip('@'))}")
    return data if isinstance(data, dict) else None


async def twitter_user_tweets(username: str) -> list[dict]:
    data = await api_get(f"/api/twitter/{quote(username.lstrip('@'))}/tweets")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("tweets", "items", "data", "results", "timeline"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


async def twitter_status(status_id: str) -> Optional[dict]:
    data = await api_get(f"/api/twitter/status/{quote(str(status_id))}")
    return data if isinstance(data, dict) else None


async def twitter_thread(status_id: str) -> Optional[dict]:
    data = await api_get(f"/api/twitter/thread/{quote(str(status_id))}")
    return data if isinstance(data, dict) else None


def twitter_status_id_from_url(url: str) -> str | None:
    m = _X_STATUS_RE.search(url or "")
    return m.group(1) if m else None


def parse_twitter_user(data: dict, *, username: str = "") -> dict | None:
    if not isinstance(data, dict):
        return None

    user: dict[str, Any] = data
    for key in ("user", "data", "result", "legacy"):
        inner = data.get(key) if isinstance(data.get(key), dict) else None
        if isinstance(inner, dict) and (
            inner.get("screen_name")
            or inner.get("core")
            or (
                isinstance(inner.get("legacy"), dict)
                and (inner.get("legacy") or {}).get("screen_name")
            )
            or inner.get("username")
        ):
            user = inner
            break

    core = _dict(user.get("core"))
    legacy = _dict(user.get("legacy"))
    privacy = _dict(user.get("privacy"))
    verification = _dict(user.get("verification"))
    avatar_block = _dict(user.get("avatar"))

    uname = _first_str(
        core.get("screen_name"),
        legacy.get("screen_name"),
        user.get("screen_name"),
        user.get("username"),
        user.get("userName"),
        username,
    ).lstrip("@")
    if not uname:
        return None

    avatar = _pick_url(
        avatar_block.get("image_url"),
        user.get("profile_image_url_https"),
        user.get("profile_image_url"),
        user.get("avatar"),
        user.get("profileImageUrl"),
        legacy.get("profile_image_url_https"),
    )
    if avatar and "_normal." in avatar:
        avatar = avatar.replace("_normal.", ".")

    return {
        "username": uname,
        "name": _first_str(core.get("name"), legacy.get("name"), user.get("name"), uname),
        "bio": _first_str(legacy.get("description"), user.get("description"), user.get("bio")),
        "followers": _as_int(
            legacy.get("followers_count")
            or user.get("followers_count")
            or user.get("followers")
        ),
        "following": _as_int(
            legacy.get("friends_count")
            or user.get("friends_count")
            or user.get("following")
            or user.get("following_count")
        ),
        "statuses": _as_int(
            legacy.get("statuses_count")
            or user.get("statuses_count")
            or user.get("tweets")
        ),
        "likes": _as_int(
            legacy.get("favourites_count")
            or user.get("favourites_count")
            or user.get("likes")
        ),
        "is_private": bool(
            privacy.get("protected")
            or user.get("protected")
            or user.get("is_private")
        ),
        "is_verified": bool(
            verification.get("verified")
            or user.get("verified")
            or user.get("is_blue_verified")
            or user.get("isBlueVerified")
        ),
        "avatar": avatar or "",
        "banner": _pick_url(
            legacy.get("profile_banner_url"),
            user.get("profile_banner_url"),
            user.get("banner"),
        )
        or "",
        "id": _first_str(user.get("rest_id"), user.get("id_str"), user.get("id")),
        "source": "social-api",
    }


def parse_twitter_status(data: dict, *, source_url: str = "") -> SocialPost | None:
    if not isinstance(data, dict) or not data:
        return None

    status: dict[str, Any] = data
    for key in ("status", "tweet", "data", "result"):
        inner = data.get(key)
        if isinstance(inner, dict) and (
            inner.get("full_text")
            or inner.get("text")
            or inner.get("rest_id")
            or isinstance(inner.get("legacy"), dict)
        ):
            status = inner
            break

    legacy = _dict(status.get("legacy"))
    if not legacy and (status.get("full_text") or status.get("text")):
        legacy = status

    core = _dict(status.get("core"))
    user_results = _dict(core.get("user_results"))
    user_result = _dict(
        user_results.get("result"),
        status.get("user"),
        data.get("user"),
    )

    user_core = _dict(user_result.get("core"))
    user_legacy = _dict(user_result.get("legacy"))
    username = _first_str(
        user_core.get("screen_name"),
        user_legacy.get("screen_name"),
        user_result.get("screen_name"),
        user_result.get("username"),
        status.get("user_screen_name"),
        _username_from_url(source_url, "twitter"),
        "unknown",
    ).lstrip("@")
    display = _first_str(
        user_core.get("name"),
        user_legacy.get("name"),
        user_result.get("name"),
        username,
    )
    avatar_block = _dict(user_result.get("avatar"))
    avatar = _pick_url(
        avatar_block.get("image_url"),
        user_result.get("profile_image_url_https"),
        user_result.get("profile_image_url"),
        user_legacy.get("profile_image_url_https"),
    )
    if avatar and "_normal." in avatar:
        avatar = avatar.replace("_normal.", ".")

    status_id = _first_str(
        status.get("rest_id"),
        legacy.get("id_str"),
        status.get("id_str"),
        status.get("id"),
        twitter_status_id_from_url(source_url),
    )
    text = _first_str(legacy.get("full_text"), legacy.get("text"), status.get("text"))

    media_urls: list[str] = []
    is_video = False
    entities = legacy.get("extended_entities") or status.get("extended_entities") or {}
    media_list: list[Any] = []
    if isinstance(entities, dict):
        media_list = list(entities.get("media") or [])
    if not media_list:
        ents = legacy.get("entities") or status.get("entities") or {}
        if isinstance(ents, dict):
            media_list = list(ents.get("media") or [])
    if not media_list and isinstance(status.get("mediaDetails"), list):
        media_list = list(status["mediaDetails"])
    if not media_list and isinstance(status.get("media"), list):
        media_list = list(status["media"])

    for m in media_list:
        if not isinstance(m, dict):
            continue
        mtype = str(m.get("type") or "").lower()
        if mtype in {"video", "animated_gif"}:
            is_video = True
            vinfo = _dict(m.get("video_info"))
            _variants = vinfo.get("variants")
            variants: list[Any] = list(_variants) if isinstance(_variants, list) else []
            best_url = None
            best_br = -1
            for v in variants:
                if not isinstance(v, dict):
                    continue
                if "video" not in str(v.get("content_type") or ""):
                    continue
                br = _as_int(v.get("bitrate"))
                u = v.get("url")
                if isinstance(u, str) and u.startswith("http") and br >= best_br:
                    best_br = br
                    best_url = u
            if best_url:
                media_urls.append(best_url)
            cover = _pick_url(m.get("media_url_https"), m.get("media_url"))
            if not best_url and cover:
                media_urls.append(cover)
                is_video = False
        else:
            u = _pick_url(m.get("media_url_https"), m.get("media_url"), m.get("url"))
            if u:
                media_urls.append(u)

    views = _dict(status.get("views"))
    play_count = _as_int(views.get("count") or status.get("view_count") or status.get("views"))

    if status_id and username and username != "unknown":
        clean = f"https://x.com/{username}/status/{status_id}"
    else:
        clean = source_url or (f"https://x.com/{username}" if username else "")

    return enrich_social_post(
        SocialPost(
            platform="twitter",
            url=clean,
            username=username or "unknown",
            display_name=display or username or "unknown",
            avatar_url=avatar,
            caption=text[:2000],
            media_urls=list(dict.fromkeys(media_urls)),
            is_video=bool(is_video),
            like_count=_as_int(
                legacy.get("favorite_count")
                or status.get("favorite_count")
                or status.get("likes")
            ),
            comment_count=_as_int(
                legacy.get("reply_count")
                or status.get("reply_count")
                or status.get("replies")
            ),
            share_count=_as_int(
                legacy.get("retweet_count")
                or status.get("retweet_count")
                or status.get("reposts")
            ),
            save_count=_as_int(legacy.get("bookmark_count") or status.get("bookmark_count")),
            play_count=play_count,
            raw={**status, "source": "social-api", "id": status_id},
        ),
        source_url=source_url or clean,
    )


async def fetch_twitter_social_post(url: str) -> SocialPost | None:
    sid = twitter_status_id_from_url(url)
    if not sid:
        return None
    data = await twitter_status(sid)
    if not data:
        return None
    post = parse_twitter_status(data, source_url=url)
    if post and (not post.avatar_url or post.username == "unknown"):
        
        try:
            uname = post.username if post.username != "unknown" else _username_from_url(url, "twitter")
            if uname:
                raw_user = await twitter_user(uname)
                parsed = parse_twitter_user(raw_user or {}, username=uname)
                if parsed:
                    if post.username == "unknown":
                        post.username = parsed["username"]
                    if not post.display_name or post.display_name == "unknown":
                        post.display_name = parsed.get("name") or post.username
                    if not post.avatar_url and parsed.get("avatar"):
                        post.avatar_url = parsed["avatar"]
        except Exception as exc:
            log.debug("twitter profile enrich failed: %s", exc)
    return enrich_social_post(post, source_url=url)







async def youtube_channel(channel: str) -> Optional[dict]:
    data = await api_get(f"/api/youtube/channel/{quote(channel.lstrip('@'))}")
    return data if isinstance(data, dict) else None


async def youtube_channel_videos(channel: str, *, limit: int = 20) -> list[dict]:
    data = await api_get(
        f"/api/youtube/channel/{quote(channel.lstrip('@'))}/videos",
        params={"limit": max(1, min(int(limit), 50))},
    )
    return _list_payload(data, ("videos", "items", "entries", "data", "results"))


async def youtube_channel_shorts(channel: str, *, limit: int = 20) -> list[dict]:
    data = await api_get(
        f"/api/youtube/channel/{quote(channel.lstrip('@'))}/shorts",
        params={"limit": max(1, min(int(limit), 50))},
    )
    return _list_payload(data, ("videos", "items", "entries", "data", "results", "shorts"))


async def youtube_video(video_id_or_url: str, *, formats: bool = True) -> Optional[dict]:
    raw = (video_id_or_url or "").strip()
    if not raw:
        return None
    vid = youtube_video_id_from_url(raw) or (raw if re.fullmatch(r"[\w-]{11}", raw) else None)
    if vid:
        data = await api_get(
            f"/api/youtube/video/{quote(vid)}",
            params={"formats": str(bool(formats)).lower()},
        )
        if isinstance(data, dict):
            return data
    if raw.startswith("http"):
        data = await api_get(
            "/api/youtube/video",
            params={"url": raw, "formats": str(bool(formats)).lower()},
        )
        return data if isinstance(data, dict) else None
    return None


async def youtube_download_info(video_id: str, *, format_id: str | None = None) -> Optional[dict]:
    params: dict[str, Any] = {}
    if format_id:
        params["format_id"] = format_id
    data = await api_get(f"/api/youtube/download/{quote(video_id)}", params=params or None)
    return data if isinstance(data, dict) else None


def youtube_video_id_from_url(url: str) -> str | None:
    m = _YT_ID_RE.search(url or "")
    if m:
        return m.group(1)
    try:
        from urllib.parse import parse_qs

        q = parse_qs(urlparse(url).query)
        v = (q.get("v") or [None])[0]
        if v and re.fullmatch(r"[\w-]{11}", v):
            return v
    except Exception:
        pass
    return None


def _list_payload(data: Any, keys: tuple[str, ...]) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
    return []


def parse_youtube_channel(data: dict, *, channel: str = "") -> dict | None:
    if not isinstance(data, dict):
        return None
    ch = data.get("channel") if isinstance(data.get("channel"), dict) else data
    if not isinstance(ch, dict):
        return None
    handle = _first_str(
        ch.get("handle"),
        ch.get("channelHandle"),
        ch.get("customUrl"),
        channel,
    ).lstrip("@")
    name = _first_str(ch.get("name"), ch.get("title"), ch.get("channel"), handle or channel)
    if not name and not handle:
        return None
    thumbs = ch.get("thumbnails") if isinstance(ch.get("thumbnails"), list) else []
    avatar = _pick_url(ch.get("avatar"), ch.get("thumbnail"), ch.get("banner_url"))
    if not avatar and thumbs:
        
        best = None
        best_w = -1
        for t in thumbs:
            if not isinstance(t, dict):
                continue
            w = _as_int(t.get("width"))
            u = t.get("url")
            if isinstance(u, str) and u.startswith("http") and w >= best_w:
                best_w = w
                best = u
        avatar = best
    return {
        "id": _first_str(ch.get("id"), ch.get("channel_id"), ch.get("channelId")),
        "name": name or handle,
        "handle": handle,
        "description": _first_str(ch.get("description"), ch.get("bio")),
        "subscribers": _as_int(
            ch.get("subscriber_count") or ch.get("subscriberCount") or ch.get("subscribers")
        ),
        "views": _as_int(ch.get("view_count") or ch.get("viewCount") or ch.get("views")),
        "videos": _as_int(ch.get("video_count") or ch.get("videoCount") or ch.get("videos")),
        "avatar": avatar or "",
        "banner": _pick_url(ch.get("banner_url"), ch.get("banner")) or "",
        "is_verified": bool(ch.get("is_verified") or ch.get("verified")),
        "url": _first_str(
            ch.get("url"),
            ch.get("channel_url"),
            f"https://www.youtube.com/@{handle}" if handle else "",
            f"https://www.youtube.com/channel/{ch.get('id')}" if ch.get("id") else "",
        ),
        "source": "social-api",
    }


def parse_youtube_video(data: dict, *, source_url: str = "") -> SocialPost | None:
    if not isinstance(data, dict) or not data:
        return None
    vid = data.get("video") if isinstance(data.get("video"), dict) else data
    if not isinstance(vid, dict):
        return None

    video_id = _first_str(
        vid.get("id"),
        vid.get("video_id"),
        vid.get("videoId"),
        youtube_video_id_from_url(source_url),
    )
    is_short = bool(
        vid.get("is_short")
        or vid.get("isShort")
        or "/shorts/" in (source_url or "")
        or "/shorts/" in str(vid.get("webpage_url") or "")
    )
    if video_id:
        clean = (
            f"https://www.youtube.com/shorts/{video_id}"
            if is_short
            else f"https://www.youtube.com/watch?v={video_id}"
        )
    else:
        clean = source_url or _first_str(vid.get("webpage_url"), vid.get("url"))

    handle = _first_str(
        vid.get("channel_handle"),
        vid.get("channelHandle"),
        vid.get("uploader_id"),
        vid.get("channel"),
    ).lstrip("@")
    channel_name = _first_str(
        vid.get("channel_name"),
        vid.get("channelName"),
        vid.get("uploader"),
        vid.get("channel"),
        handle or "unknown",
    )

    media_urls: list[str] = []
    best = _pick_url(vid.get("best_url"), vid.get("url"), vid.get("download_url"))
    if best:
        media_urls.append(best)
    _formats = vid.get("formats")
    formats: list[Any] = list(_formats) if isinstance(_formats, list) else []

    progressive: list[tuple[int, str]] = []
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        u = fmt.get("url")
        if not isinstance(u, str) or not u.startswith("http"):
            continue
        if fmt.get("is_progressive") or (
            fmt.get("has_video") and fmt.get("has_audio")
        ):
            h = _as_int(fmt.get("height"))
            progressive.append((h, u))
    if progressive:
        progressive.sort(key=lambda x: x[0], reverse=True)
        media_urls = [progressive[0][1]] + [u for u in media_urls if u != progressive[0][1]]

    thumbs = vid.get("thumbnails") if isinstance(vid.get("thumbnails"), list) else []
    thumb = _pick_url(vid.get("thumbnail"), vid.get("thumbnail_url"))
    if not thumb and thumbs:
        best_t = None
        best_w = -1
        for t in thumbs:
            if not isinstance(t, dict):
                continue
            w = _as_int(t.get("width"))
            u = t.get("url")
            if isinstance(u, str) and u.startswith("http") and w >= best_w:
                best_w = w
                best_t = u
        thumb = best_t
    if not media_urls and thumb:
        media_urls = [thumb]

    return enrich_social_post(
        SocialPost(
            platform="youtube",
            url=clean,
            username=handle or channel_name or "unknown",
            display_name=channel_name or handle or "unknown",
            avatar_url=_pick_url(vid.get("channel_avatar"), vid.get("avatar"), thumb),
            caption=_first_str(vid.get("title"), vid.get("description"))[:2000],
            media_urls=list(dict.fromkeys(media_urls)),
            is_video=True,
            like_count=_as_int(vid.get("like_count") or vid.get("likeCount") or vid.get("likes")),
            comment_count=_as_int(
                vid.get("comment_count") or vid.get("commentCount") or vid.get("comments")
            ),
            play_count=_as_int(vid.get("view_count") or vid.get("viewCount") or vid.get("views")),
            raw={
                **vid,
                "source": "social-api",
                "id": video_id,
                "is_short": is_short,
                "thumbnail_url": thumb,
            },
        ),
        source_url=source_url or clean,
    )


async def fetch_youtube_social_post(url: str) -> SocialPost | None:
    data = await youtube_video(url, formats=True)
    if not data:
        return None
    post = parse_youtube_video(data, source_url=url)
    if post and (not post.avatar_url or post.username == "unknown"):
        handle = post.username if post.username != "unknown" else ""
        if handle:
            try:
                raw_ch = await youtube_channel(handle)
                parsed = parse_youtube_channel(raw_ch or {}, channel=handle)
                if parsed:
                    if not post.avatar_url and parsed.get("avatar"):
                        post.avatar_url = parsed["avatar"]
                    if parsed.get("name"):
                        post.display_name = parsed["name"]
            except Exception as exc:
                log.debug("youtube channel enrich failed: %s", exc)
    return enrich_social_post(post, source_url=url)







async def telegram_user(username: str) -> Optional[dict]:
    data = await api_get(f"/api/telegram/{quote(username.lstrip('@'))}")
    return data if isinstance(data, dict) else None


async def telegram_channel(username: str) -> Optional[dict]:
    data = await api_get(f"/api/telegram/channel/{quote(username.lstrip('@'))}")
    return data if isinstance(data, dict) else None


def parse_telegram_user(data: dict, *, username: str = "") -> dict | None:
    if not isinstance(data, dict):
        return None
    user = _unwrap(data, "user", "data", "result")
    if not isinstance(user, dict):
        return None
    alt_uname = ""
    usernames = user.get("usernames")
    if isinstance(usernames, list):
        for entry in usernames:
            if isinstance(entry, dict) and entry.get("username"):
                alt_uname = str(entry.get("username"))
                break
    uname = _first_str(user.get("username"), alt_uname, username).lstrip("@")
    first = _first_str(user.get("first_name"), user.get("firstName"))
    last = _first_str(user.get("last_name"), user.get("lastName"))
    name = " ".join(p for p in (first, last) if p).strip() or uname
    if not uname and not name:
        return None
    photo = _dict(user.get("photo"))
    avatar = _pick_url(
        user.get("avatar"),
        user.get("photo_url"),
        photo.get("url"),
        f"{_base()}/api/telegram/{quote(uname)}/avatar/bytes" if uname else None,
    )
    return {
        "username": uname,
        "name": name or uname,
        "bio": _first_str(user.get("about"), user.get("bio"), user.get("description")),
        "is_bot": bool(user.get("bot") or user.get("is_bot")),
        "is_verified": bool(user.get("verified") or user.get("is_verified")),
        "is_premium": bool(user.get("premium") or user.get("is_premium")),
        "is_private": False,
        "avatar": avatar or "",
        "id": _first_str(user.get("id"), user.get("user_id")),
        "source": "social-api",
    }


def parse_telegram_channel(data: dict, *, username: str = "") -> dict | None:
    if not isinstance(data, dict):
        return None
    ch = _unwrap(data, "channel", "data", "result")
    if not isinstance(ch, dict):
        return None
    uname = _first_str(ch.get("username"), username).lstrip("@")
    title = _first_str(ch.get("title"), ch.get("name"), uname)
    if not uname and not title:
        return None
    photo = _dict(ch.get("photo"))
    avatar = _pick_url(
        ch.get("avatar"),
        ch.get("photo_url"),
        photo.get("url"),
        f"{_base()}/api/telegram/channel/{quote(uname)}/avatar/bytes" if uname else None,
    )
    return {
        "username": uname,
        "name": title or uname,
        "bio": _first_str(ch.get("about"), ch.get("description"), ch.get("bio")),
        "members": _as_int(
            ch.get("participants_count")
            or ch.get("participantsCount")
            or ch.get("members")
            or ch.get("subscribers")
        ),
        "is_verified": bool(ch.get("verified") or ch.get("is_verified")),
        "is_private": bool(ch.get("restricted") or ch.get("is_private")),
        "is_broadcast": bool(ch.get("broadcast") or ch.get("is_broadcast")),
        "avatar": avatar or "",
        "id": _first_str(ch.get("id"), ch.get("channel_id")),
        "source": "social-api",
    }


async def _enrich_tiktok_post(post: SocialPost | None, *, source_url: str = "") -> SocialPost | None:
    post = enrich_social_post(post, source_url=source_url)
    if post is None:
        return None
    needs = (
        post.username in ("", "unknown")
        or not post.avatar_url
        or not post.display_name
        or post.display_name == post.username
    )
    if needs and post.username not in ("", "unknown"):
        try:
            raw_user = await tiktok_user(post.username)
            parsed = parse_tiktok_user(raw_user or {}, username=post.username)
            if parsed:
                if parsed.get("nickname"):
                    post.display_name = parsed["nickname"]
                if parsed.get("avatarLarger") and not post.avatar_url:
                    post.avatar_url = parsed["avatarLarger"]
        except Exception as exc:
            log.debug("tiktok profile enrich failed: %s", exc)
    return enrich_social_post(post, source_url=source_url)


async def fetch_instagram_social_post(url: str) -> SocialPost | None:
    code = instagram_shortcode_from_url(url)
    if not code:
        return None
    data = await instagram_post(code)
    if not data:
        return None
    post = parse_instagram_post(data, source_url=url)
    if post and (
        post.username in ("", "unknown")
        or not post.avatar_url
        or not post.display_name
        or post.display_name == post.username
    ):
        uname = post.username if post.username != "unknown" else _username_from_url(url, "instagram")
        if uname and uname != "unknown":
            try:
                raw_user = await instagram_user(uname)
                parsed = parse_instagram_user(raw_user or {}, username=uname)
                if parsed:
                    post.username = parsed["username"] or post.username
                    if parsed.get("full_name"):
                        post.display_name = parsed["full_name"]
                    if parsed.get("avatar") and not post.avatar_url:
                        post.avatar_url = parsed["avatar"]
            except Exception as exc:
                log.debug("ig profile enrich failed: %s", exc)
    return enrich_social_post(post, source_url=url)


async def fetch_tiktok_social_post(url: str) -> SocialPost | None:
    """Resolve a TikTok share URL via guilt (item id or shortcode)."""
    url = (url or "").strip()
    if not url:
        return None
    if not url.startswith("http"):
        url = "https://" + url

    m = _TT_ID_RE.search(url)
    if m:
        data = await tiktok_item(m.group(1))
        if data:
            post = await _enrich_tiktok_post(parse_tiktok_post(data, source_url=url), source_url=url)
            if post and (post.media_urls or post.caption):
                return post

    try:
        host = urlparse(url).netloc.lower()
        path = urlparse(url).path.strip("/")
    except Exception:
        host, path = "", ""

    code: str | None = None
    if any(h in host for h in ("vm.tiktok.com", "vt.tiktok.com")):
        code = path.split("/")[0] if path else None
    elif "/t/" in (url or ""):
        parts = path.split("/")
        if "t" in parts:
            i = parts.index("t")
            if i + 1 < len(parts):
                code = parts[i + 1]
    if code:
        data = await tiktok_shortcode(code)
        if not data:
            data = await tiktok_shortcode(url)
        if data:
            return await _enrich_tiktok_post(parse_tiktok_post(data, source_url=url), source_url=url)

    if not m:
        data = await tiktok_shortcode(url)
        if data:
            return await _enrich_tiktok_post(parse_tiktok_post(data, source_url=url), source_url=url)
    return None







async def twitch_user(username: str) -> Optional[dict]:
    data = await api_get(f"/api/twitch/{quote(username.lstrip('@'))}")
    return data if isinstance(data, dict) else None


async def twitch_live(username: str) -> Optional[dict]:
    data = await api_get(f"/api/twitch/{quote(username.lstrip('@'))}/live")
    return data if isinstance(data, dict) else None


async def twitch_stream(username: str) -> Optional[dict]:
    data = await api_get(f"/api/twitch/{quote(username.lstrip('@'))}/stream")
    return data if isinstance(data, dict) else None


async def twitch_videos(username: str) -> list[dict]:
    data = await api_get(f"/api/twitch/{quote(username.lstrip('@'))}/videos")
    return _list_payload(data, ("videos", "items", "data", "results"))


async def twitch_clips(username: str) -> list[dict]:
    data = await api_get(f"/api/twitch/{quote(username.lstrip('@'))}/clips")
    return _list_payload(data, ("clips", "items", "data", "results"))


async def twitch_video(video_id: str) -> Optional[dict]:
    data = await api_get(f"/api/twitch/v/{quote(str(video_id))}")
    return data if isinstance(data, dict) else None


def parse_twitch_user(data: dict, *, username: str = "") -> dict | None:
    if not isinstance(data, dict):
        return None
    user = _unwrap(data, "user", "data", "result")
    if not isinstance(user, dict):
        return None
    login = _first_str(user.get("login"), user.get("username"), username).lstrip("@")
    if not login and not user.get("display_name"):
        return None
    stream = _dict(user.get("stream"), data.get("stream"))
    return {
        "username": login,
        "display_name": _first_str(user.get("display_name"), user.get("displayName"), login),
        "bio": _first_str(user.get("description"), user.get("bio")),
        "avatar": _pick_url(user.get("profile_image_url"), user.get("avatar"), user.get("logo")) or "",
        "banner": _pick_url(user.get("banner_image_url"), user.get("banner")) or "",
        "followers": _as_int(user.get("followers") or user.get("follower_count")),
        "is_live": bool(user.get("is_live") or stream.get("is_live") or stream.get("type") == "live"),
        "is_partner": bool(user.get("is_partner") or user.get("partner")),
        "is_affiliate": bool(user.get("is_affiliate")),
        "url": _first_str(user.get("url"), f"https://www.twitch.tv/{login}" if login else ""),
        "stream_title": _first_str(stream.get("title")),
        "viewers": _as_int(stream.get("viewers") or stream.get("viewer_count")),
        "game": _first_str(
            (stream.get("game") or {}).get("name") if isinstance(stream.get("game"), dict) else None,
            stream.get("game_name"),
            stream.get("game"),
        ),
        "id": _first_str(user.get("id")),
        "source": "social-api",
    }


def parse_twitch_video(data: dict, *, source_url: str = "") -> SocialPost | None:
    if not isinstance(data, dict) or not data:
        return None
    vid = _unwrap(data, "video", "data", "result")
    owner = _dict(vid.get("owner"), vid.get("user"), data.get("owner"))
    username = _first_str(
        owner.get("login"),
        owner.get("display_name"),
        vid.get("broadcaster_login"),
        _username_from_url(source_url, "twitch"),
        "unknown",
    ).lstrip("@")
    display = _first_str(owner.get("display_name"), owner.get("login"), username)
    media = _url_list(vid.get("download_url"), vid.get("url"), vid.get("m3u8_url"))
    thumb = _pick_url(vid.get("preview_thumbnail_url"), vid.get("animated_preview_url"), vid.get("thumbnail"))
    if not media and thumb:
        media = [thumb]
    clean = _first_str(vid.get("url"), source_url, f"https://www.twitch.tv/videos/{vid.get('id')}" if vid.get("id") else "")
    return enrich_social_post(
        SocialPost(
            platform="twitch",
            url=clean,
            username=username or "unknown",
            display_name=display or username or "unknown",
            avatar_url=_pick_url(owner.get("profile_image_url"), owner.get("avatar")),
            caption=_first_str(vid.get("title"), vid.get("description"))[:2000],
            media_urls=list(dict.fromkeys(media)),
            is_video=True,
            play_count=_as_int(vid.get("view_count") or vid.get("views")),
            raw={**vid, "source": "social-api"},
        ),
        source_url=source_url or clean,
    )


async def snapchat_user(username: str) -> Optional[dict]:
    data = await api_get(f"/api/snapchat/{quote(username.lstrip('@'))}")
    return data if isinstance(data, dict) else None


def parse_snapchat_user(data: dict, *, username: str = "") -> dict | None:
    if not isinstance(data, dict):
        return None
    user = _unwrap(data, "user", "data", "result", "publicProfileInfo")
    if not isinstance(user, dict):
        return None
    uname = _first_str(user.get("username"), username).lstrip("@")
    if not uname and not user.get("name"):
        return None
    bitmoji = _dict(user.get("bitmoji"))
    avatar = _pick_url(
        user.get("profile_picture_url"),
        user.get("square_hero_image_url"),
        user.get("preview_image"),
        bitmoji.get("avatar"),
        user.get("snapcode_image_url"),
    )
    return {
        "username": uname,
        "name": _first_str(user.get("display_name"), user.get("title"), user.get("name"), uname),
        "bio": _first_str(user.get("bio"), user.get("page_description")),
        "avatar": avatar or "",
        "subscribers": _as_int(user.get("subscriber_count") or user.get("subscribers")),
        "is_verified": bool(user.get("verified")),
        "has_story": bool(user.get("has_story")),
        "url": _first_str(
            user.get("url"),
            user.get("canonical_url"),
            f"https://www.snapchat.com/add/{uname}" if uname else "",
        ),
        "source": "social-api",
    }


async def pinterest_user(username: str) -> Optional[dict]:
    data = await api_get(f"/api/pinterest/user/{quote(username.lstrip('@'))}")
    if not isinstance(data, dict):
        data = await api_get(f"/api/pinterest/profile/{quote(username.lstrip('@'))}")
    return data if isinstance(data, dict) else None


async def pinterest_pin(url_or_id: str) -> Optional[dict]:
    raw = (url_or_id or "").strip()
    if not raw:
        return None
    if raw.startswith("http"):
        data = await api_get("/api/pinterest/pin", params={"url": raw})
    else:
        data = await api_get("/api/pinterest/pin", params={"id": raw})
    return data if isinstance(data, dict) else None


async def pinterest_search(query: str, *, limit: int = 12) -> list[dict]:
    data = await api_get(
        "/api/pinterest/search",
        params={"q": query, "limit": max(1, min(int(limit), 50))},
    )
    return _list_payload(data, ("pins", "items", "results", "data"))


def parse_pinterest_user(data: dict, *, username: str = "") -> dict | None:
    if not isinstance(data, dict):
        return None
    user = _unwrap(data, "user", "data", "result", "profile")
    if not isinstance(user, dict):
        return None
    uname = _first_str(user.get("username"), username).lstrip("@")
    if not uname and not user.get("full_name"):
        return None
    return {
        "username": uname,
        "name": _first_str(user.get("full_name"), user.get("first_name"), uname),
        "bio": _first_str(user.get("about"), user.get("bio"), user.get("description")),
        "avatar": _pick_url(
            user.get("image_xlarge_url"),
            user.get("image_medium_url"),
            user.get("avatar"),
        )
        or "",
        "followers": _as_int(user.get("follower_count") or user.get("followers")),
        "following": _as_int(user.get("following_count") or user.get("following")),
        "pins": _as_int(user.get("pin_count") or user.get("pins")),
        "boards": _as_int(user.get("board_count") or user.get("boards")),
        "is_verified": bool(user.get("verified") or user.get("is_verified_merchant")),
        "is_private": bool(user.get("is_private_profile")),
        "url": _first_str(user.get("url"), f"https://www.pinterest.com/{uname}/" if uname else ""),
        "source": "social-api",
    }


def parse_pinterest_pin(data: dict, *, source_url: str = "") -> SocialPost | None:
    if not isinstance(data, dict) or not data:
        return None
    pin = _unwrap(data, "pin", "data", "result")
    pinner = _dict(pin.get("pinner"), pin.get("native_creator"), pin.get("user"))
    username = _first_str(
        pinner.get("username"),
        (pin.get("board") or {}).get("owner", {}).get("username")
        if isinstance(pin.get("board"), dict)
        else None,
        _username_from_url(source_url, "pinterest"),
        "unknown",
    ).lstrip("@")
    display = _first_str(pinner.get("full_name"), pinner.get("first_name"), username)
    media = _url_list(pin.get("image_urls"), pin.get("video_urls"), pin.get("images"), pin.get("videos"))
    if not media:
        images = pin.get("images") if isinstance(pin.get("images"), dict) else {}
        for key in ("orig", "originals", "736x", "564x", "474x"):
            block = images.get(key) if isinstance(images, dict) else None
            u = _pick_url(block)
            if u:
                media.append(u)
                break
    caption = _first_str(pin.get("grid_title"), pin.get("title"), pin.get("description"), pin.get("alt_text"))
    clean = _first_str(pin.get("url"), pin.get("link"), source_url)
    return enrich_social_post(
        SocialPost(
            platform="pinterest",
            url=clean,
            username=username or "unknown",
            display_name=display or username or "unknown",
            avatar_url=_pick_url(pinner.get("image_xlarge_url"), pinner.get("image_medium_url")),
            caption=caption[:2000],
            media_urls=list(dict.fromkeys(media)),
            is_video=bool(pin.get("is_video") or pin.get("video_urls")),
            like_count=_as_int(pin.get("reaction_counts") or pin.get("repin_count")),
            comment_count=_as_int(pin.get("comment_count")),
            raw={**pin, "source": "social-api"},
        ),
        source_url=source_url or clean,
    )


async def brave_search(query: str, *, count: int = 8) -> dict | None:
    data = await api_get(
        "/api/brave/search",
        params={"q": query, "count": max(1, min(int(count), 20))},
    )
    return data if isinstance(data, dict) else None


async def brave_scrape(url: str) -> dict | None:
    data = await api_get("/api/brave/scrape", params={"url": url})
    return data if isinstance(data, dict) else None


async def brave_ai(query: str) -> dict | None:
    data = await api_get("/api/brave/ai", params={"q": query}, timeout=60.0)
    return data if isinstance(data, dict) else None


async def google_search(query: str, *, count: int = 8) -> dict | None:
    data = await api_get(
        "/api/google/search",
        params={"q": query, "count": max(1, min(int(count), 20))},
    )
    return data if isinstance(data, dict) else None


async def google_scrape(url: str) -> dict | None:
    data = await api_get("/api/google/scrape", params={"url": url})
    return data if isinstance(data, dict) else None


def parse_search_results(data: dict | list | None) -> list[dict]:
    """Normalize Brave/Google search payloads into [{title,url,snippet,image}]."""
    if data is None:
        return []
    items: list[Any]
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = []
        for key in ("results", "web", "organic", "items", "data", "images"):
            val = data.get(key)
            if isinstance(val, list):
                items = val
                break
            if isinstance(val, dict):
                for k2 in ("results", "items"):
                    if isinstance(val.get(k2), list):
                        items = val[k2]
                        break
            if items:
                break
    else:
        return []
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        title = _first_str(it.get("title"), it.get("name"))
        url = _first_str(it.get("url"), it.get("link"), it.get("href"))
        if not title and not url:
            continue
        out.append(
            {
                "title": title,
                "url": url,
                "snippet": _first_str(
                    it.get("description"),
                    it.get("snippet"),
                    it.get("text"),
                    it.get("meta_description"),
                ),
                "image": _pick_url(it.get("image"), it.get("thumbnail"), it.get("img")) or "",
            }
        )
    return out
