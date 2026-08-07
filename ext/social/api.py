"""Social content API client (scl.guilt.bot — socials-main route shape).

Base: https://scl.guilt.bot (override with ``config.api.social_base``).
No API key required.

Routes used:
  Instagram
    GET /api/instagram/{username}
    GET /api/instagram/p/{shortcode}
    GET /api/instagram/trending?count=
    GET /api/instagram/{username}/posts?count=
    GET /api/instagram/{username}/stories
    GET /api/instagram/{username}/highlights
    GET /api/instagram/highlights/{highlight_id}
  TikTok
    GET /api/tiktok/{username}
    GET /api/tiktok/fyp?limit=&region=
    GET /api/tiktok/{username}/posts?limit=
    GET /api/tiktok/{username}/reposts?limit=
    GET /api/tiktok/p/{item_id}
    GET /api/tiktok/shortcode/{code}
  Twitter / X
    GET /api/twitter/{username}
    GET /api/twitter/{username}/tweets
    GET /api/twitter/status/{status_id}
    GET /api/twitter/thread/{status_id}
  YouTube
    GET /api/youtube/channel/{channel}
    GET /api/youtube/channel/{channel}/videos|shorts|notifications
    GET /api/youtube/video/{video_id}
    GET /api/youtube/video?url=
    GET /api/youtube/download/{video_id}
  Telegram
    GET /api/telegram/{username}
    GET /api/telegram/channel/{username}
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
    return {
        "User-Agent": "VainBot/1.0 (+https://vain.bot)",
        "Accept": "application/json",
    }


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


def _first_str(*values: Any) -> str:
    for v in values:
        if v is None:
            continue
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return ""


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
                        item.get("downloadAddr"),
                        item.get("play"),
                    )
                    if u:
                        return u
        if isinstance(v, dict):
            u = _pick_url(
                v.get("url"),
                v.get("playAddr"),
                v.get("downloadAddr"),
                v.get("play"),
                v.get("hdplay"),
                v.get("urlList"),
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
    """GET JSON from scl.guilt.bot. Returns None on any failure."""
    url = f"{_base()}{path if path.startswith('/') else '/' + path}"
    try:
        async with aiohttp.ClientSession(headers=_headers()) as session:
            async with session.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
            ) as resp:
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
    for key in ("post", "item", "media", "data"):
        inner = data.get(key)
        if isinstance(inner, dict) and (
            inner.get("code") or inner.get("pk") or inner.get("user") or inner.get("caption")
        ):
            post = inner
            break

    user = post.get("user") if isinstance(post.get("user"), dict) else {}
    if not isinstance(user, dict):
        user = {}
    username = _first_str(
        user.get("username"),
        post.get("username"),
        post.get("author_name"),
        "unknown",
    ).lstrip("@")
    display = _first_str(
        user.get("full_name"),
        user.get("fullName"),
        post.get("full_name"),
        username,
    )
    avatar = _pick_url(
        user.get("profile_pic_url"),
        user.get("profile_pic_url_hd"),
        user.get("profilePicUrl"),
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

    return SocialPost(
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
    )


def parse_instagram_user(data: dict, *, username: str = "") -> dict | None:
    if not isinstance(data, dict):
        return None
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    if not isinstance(user, dict):
        return None
    uname = _first_str(user.get("username"), username).lstrip("@")
    if not uname:
        return None
    return {
        "username": uname,
        "full_name": _first_str(user.get("full_name"), user.get("fullName"), uname),
        "bio": _first_str(user.get("biography"), user.get("bio"), user.get("signature")),
        "followers": _as_int(
            user.get("follower_count")
            or user.get("followers")
            or (user.get("edge_followed_by") or {}).get("count")
        ),
        "following": _as_int(
            user.get("following_count")
            or user.get("following")
            or (user.get("edge_follow") or {}).get("count")
        ),
        "posts": _as_int(
            user.get("media_count")
            or user.get("posts")
            or (user.get("edge_owner_to_timeline_media") or {}).get("count")
        ),
        "is_private": bool(user.get("is_private") or user.get("isPrivate") or user.get("private")),
        "is_verified": bool(user.get("is_verified") or user.get("isVerified") or user.get("verified")),
        "avatar": _pick_url(
            user.get("profile_pic_url_hd"),
            user.get("hd_profile_pic_url_info"),
            user.get("profile_pic_url"),
            user.get("profilePicUrl"),
            user.get("avatar"),
        )
        or "",
        "pk": _first_str(user.get("pk"), user.get("id")),
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
    """Normalize guilt TikTok Video/Photo/Story payload → SocialPost."""
    if not isinstance(data, dict) or not data:
        return None

    post = data
    item = post.get("itemInfos") if isinstance(post.get("itemInfos"), dict) else None
    author_infos: dict = post.get("authorInfos") if isinstance(post.get("authorInfos"), dict) else {}
    video_block: dict = post.get("video") if isinstance(post.get("video"), dict) else {}
    stats: dict = post.get("stats") if isinstance(post.get("stats"), dict) else {}
    author: dict = post.get("author") if isinstance(post.get("author"), dict) else {}
    music: dict = post.get("music") if isinstance(post.get("music"), dict) else {}
    music_infos: dict = post.get("musicInfos") if isinstance(post.get("musicInfos"), dict) else {}

    post_id = ""
    caption = ""
    likes = comments = shares = plays = saves = 0
    media_urls: list[str] = []
    is_video = False
    username = "unknown"
    display = ""
    avatar: str | None = None
    music_title: str | None = None
    music_author: str | None = None
    mid = ""

    if item is not None:
        post_id = _first_str(item.get("id"), post.get("id"))
        caption = _first_str(item.get("text"), post.get("desc"), post.get("caption"))
        likes = _as_int(item.get("diggCount") or item.get("digg_count"))
        comments = _as_int(item.get("commentCount") or item.get("comment_count"))
        shares = _as_int(item.get("shareCount") or item.get("share_count"))
        plays = _as_int(item.get("playCount") or item.get("play_count"))
        saves = _as_int(stats.get("collectCount") or post.get("collect_count"))
        video_node = item.get("video") if isinstance(item.get("video"), dict) else {}
        video_urls = _url_list(video_node.get("urls"), video_node, item.get("video"))
        images = _url_list(post.get("imagePostInfo"))
        media_urls = list(dict.fromkeys([*video_urls, *images]))
        is_video = bool(video_urls) and not images
        username = _first_str(
            author_infos.get("uniqueId"),
            author_infos.get("unique_id"),
            author.get("uniqueId"),
            "unknown",
        ).lstrip("@")
        display = _first_str(
            author_infos.get("nickName"),
            author_infos.get("nickname"),
            author.get("nickname"),
            username,
        )
        avatar = _pick_url(
            author_infos.get("coversLarger"),
            author_infos.get("coversMedium"),
            author_infos.get("covers"),
            author.get("avatarLarger"),
            author.get("avatar"),
        )
        if music_infos:
            music_title = _first_str(music_infos.get("musicName"), music_infos.get("title")) or None
            music_author = (
                _first_str(music_infos.get("authorName"), music_infos.get("author")) or None
            )
            mid = _first_str(music_infos.get("musicId"), music_infos.get("id"))
        else:
            music_title = _first_str(music.get("title"), music.get("musicName")) or None
            music_author = _first_str(music.get("authorName"), music.get("author")) or None
            mid = _first_str(music.get("id"), music.get("musicId"))
    else:
        post_id = _first_str(post.get("id"), video_block.get("id"))
        caption = _first_str(
            post.get("desc"), post.get("caption"), post.get("title"), post.get("text")
        )
        likes = _as_int(
            stats.get("diggCount")
            or post.get("digg_count")
            or post.get("like_count")
            or post.get("likes")
        )
        comments = _as_int(
            stats.get("commentCount") or post.get("comment_count") or post.get("comments")
        )
        shares = _as_int(stats.get("shareCount") or post.get("share_count") or post.get("shares"))
        plays = _as_int(stats.get("playCount") or post.get("play_count") or post.get("plays"))
        saves = _as_int(stats.get("collectCount") or post.get("collect_count") or post.get("saves"))
        media_urls = _url_list(
            video_block.get("playAddr"),
            video_block.get("downloadAddr"),
            post.get("video_url"),
            post.get("download_url"),
            post.get("play"),
            post.get("hdplay"),
            post.get("images"),
            post.get("imagePostInfo"),
        )
        cover = _pick_url(
            video_block.get("cover"),
            video_block.get("originCover"),
            post.get("thumbnail"),
            post.get("cover"),
        )
        is_video = bool(
            _pick_url(
                video_block.get("playAddr"),
                video_block.get("downloadAddr"),
                post.get("video_url"),
                post.get("play"),
            )
        )
        if not media_urls and cover:
            media_urls = [cover]
            is_video = False
        username = _first_str(
            author.get("uniqueId"),
            author.get("unique_id"),
            author.get("username"),
            post.get("username"),
            "unknown",
        ).lstrip("@")
        display = _first_str(
            author.get("nickname"),
            author.get("nickName"),
            author.get("display_name"),
            username,
        )
        avatar = _pick_url(
            author.get("avatarLarger"),
            author.get("avatarMedium"),
            author.get("avatarThumb"),
            author.get("avatar"),
            author.get("coversLarger"),
        )
        music_title = _first_str(music.get("title"), music.get("musicName")) or None
        music_author = _first_str(music.get("authorName"), music.get("author")) or None
        mid = _first_str(music.get("id"), music.get("musicId"))

    if not username or username == "unknown":
        um = _TT_USER_RE.search(source_url or "")
        if um:
            username = um.group(1)

    kind = "photo" if (not is_video and media_urls) else "video"
    if post_id and username and username != "unknown":
        clean = f"https://www.tiktok.com/@{username}/{kind}/{post_id}"
    else:
        clean = source_url or (f"https://www.tiktok.com/@{username}" if username else "")

    music_url = f"https://www.tiktok.com/music/original-sound-{mid}" if mid else None

    return SocialPost(
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
    )


def parse_tiktok_user(data: dict, *, username: str = "") -> dict | None:
    if not isinstance(data, dict):
        return None
    
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    if not isinstance(user, dict):
        return None
    uname = _first_str(
        user.get("uniqueId"),
        user.get("unique_id"),
        user.get("username"),
        username,
    ).lstrip("@")
    if not uname:
        return None
    return {
        "uniqueId": uname,
        "nickname": _first_str(user.get("nickname"), user.get("nickName"), uname),
        "avatarLarger": _pick_url(
            user.get("avatarLarger"),
            user.get("avatar_larger"),
            user.get("avatarMedium"),
            user.get("avatar"),
        )
        or "",
        "signature": _first_str(user.get("signature"), user.get("bio")),
        "followerCount": _as_int(
            user.get("followerCount")
            or user.get("followers")
            or stats.get("followerCount")
        ),
        "followingCount": _as_int(
            user.get("followingCount")
            or user.get("following")
            or stats.get("followingCount")
        ),
        "heartCount": _as_int(
            user.get("heart")
            or user.get("heartCount")
            or user.get("likes")
            or stats.get("heart")
            or stats.get("heartCount")
        ),
        "videoCount": _as_int(
            user.get("videoCount") or user.get("videos") or stats.get("videoCount")
        ),
        "verified": bool(user.get("verified") or user.get("is_verified")),
        "is_private": bool(
            user.get("privateAccount")
            or user.get("secret")
            or user.get("isPrivate")
            or user.get("is_private")
            or user.get("private")
        ),
        "id": _first_str(user.get("id"), user.get("userId")),
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
    
    user = data
    for key in ("user", "data", "result", "legacy"):
        inner = data.get(key) if isinstance(data.get(key), dict) else None
        if inner and (
            inner.get("screen_name")
            or inner.get("core")
            or (isinstance(inner.get("legacy"), dict) and inner.get("legacy").get("screen_name"))
            or inner.get("username")
        ):
            user = inner
            break

    core = user.get("core") if isinstance(user.get("core"), dict) else {}
    legacy = user.get("legacy") if isinstance(user.get("legacy"), dict) else {}
    privacy = user.get("privacy") if isinstance(user.get("privacy"), dict) else {}
    verification = user.get("verification") if isinstance(user.get("verification"), dict) else {}
    avatar_block = user.get("avatar") if isinstance(user.get("avatar"), dict) else {}

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

    status = data
    for key in ("status", "tweet", "data", "result", "legacy"):
        inner = data.get(key)
        if isinstance(inner, dict) and (
            inner.get("full_text")
            or inner.get("text")
            or inner.get("rest_id")
            or isinstance(inner.get("legacy"), dict)
        ):
            
            if key == "legacy" and data.get("rest_id"):
                break
            if key != "legacy":
                status = inner
            break

    legacy = status.get("legacy") if isinstance(status.get("legacy"), dict) else {}
    if not legacy and (status.get("full_text") or status.get("text")):
        legacy = status

    core = status.get("core") if isinstance(status.get("core"), dict) else {}
    user_result = (
        (core.get("user_results") or {}).get("result")
        if isinstance(core.get("user_results"), dict)
        else None
    )
    if not isinstance(user_result, dict):
        user_result = status.get("user") if isinstance(status.get("user"), dict) else {}

    user_core = user_result.get("core") if isinstance(user_result.get("core"), dict) else {}
    user_legacy = (
        user_result.get("legacy") if isinstance(user_result.get("legacy"), dict) else {}
    )
    username = _first_str(
        user_core.get("screen_name"),
        user_legacy.get("screen_name"),
        user_result.get("screen_name"),
        status.get("user", {}).get("screen_name") if isinstance(status.get("user"), dict) else "",
        "unknown",
    ).lstrip("@")
    display = _first_str(
        user_core.get("name"),
        user_legacy.get("name"),
        user_result.get("name"),
        username,
    )
    avatar_block = (
        user_result.get("avatar") if isinstance(user_result.get("avatar"), dict) else {}
    )
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
    media_list = []
    if isinstance(entities, dict):
        media_list = entities.get("media") or []
    if not media_list:
        ents = legacy.get("entities") or status.get("entities") or {}
        if isinstance(ents, dict):
            media_list = ents.get("media") or []
    if not media_list and isinstance(status.get("mediaDetails"), list):
        media_list = status["mediaDetails"]
    if not media_list and isinstance(status.get("media"), list):
        media_list = status["media"]

    for m in media_list:
        if not isinstance(m, dict):
            continue
        mtype = str(m.get("type") or "").lower()
        if mtype in {"video", "animated_gif"}:
            is_video = True
            vinfo = m.get("video_info") if isinstance(m.get("video_info"), dict) else {}
            variants = vinfo.get("variants") if isinstance(vinfo.get("variants"), list) else []
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
            if cover and cover not in media_urls:
                
                pass
            if not best_url and cover:
                media_urls.append(cover)
                is_video = False
        else:
            u = _pick_url(m.get("media_url_https"), m.get("media_url"), m.get("url"))
            if u:
                media_urls.append(u)

    views = status.get("views") if isinstance(status.get("views"), dict) else {}
    play_count = _as_int(views.get("count") or status.get("view_count") or status.get("views"))

    if status_id and username and username != "unknown":
        clean = f"https://x.com/{username}/status/{status_id}"
    else:
        clean = source_url or (f"https://x.com/{username}" if username else "")

    return SocialPost(
        platform="twitter",
        url=clean,
        username=username or "unknown",
        display_name=display or username or "unknown",
        avatar_url=avatar,
        caption=text[:2000],
        media_urls=list(dict.fromkeys(media_urls)),
        is_video=bool(is_video),
        like_count=_as_int(legacy.get("favorite_count") or status.get("favorite_count") or status.get("likes")),
        comment_count=_as_int(legacy.get("reply_count") or status.get("reply_count") or status.get("replies")),
        share_count=_as_int(legacy.get("retweet_count") or status.get("retweet_count") or status.get("reposts")),
        save_count=_as_int(legacy.get("bookmark_count") or status.get("bookmark_count")),
        play_count=play_count,
        raw={**status, "source": "social-api", "id": status_id},
    )


async def fetch_twitter_social_post(url: str) -> SocialPost | None:
    sid = twitter_status_id_from_url(url)
    if not sid:
        return None
    data = await twitter_status(sid)
    if not data:
        return None
    return parse_twitter_status(data, source_url=url)







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
    formats = vid.get("formats") if isinstance(vid.get("formats"), list) else []
    
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

    return SocialPost(
        platform="youtube",
        url=clean,
        username=handle or channel_name or "unknown",
        display_name=channel_name or handle or "unknown",
        avatar_url=None,
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
    )


async def fetch_youtube_social_post(url: str) -> SocialPost | None:
    data = await youtube_video(url, formats=True)
    if not data:
        return None
    return parse_youtube_video(data, source_url=url)







async def telegram_user(username: str) -> Optional[dict]:
    data = await api_get(f"/api/telegram/{quote(username.lstrip('@'))}")
    return data if isinstance(data, dict) else None


async def telegram_channel(username: str) -> Optional[dict]:
    data = await api_get(f"/api/telegram/channel/{quote(username.lstrip('@'))}")
    return data if isinstance(data, dict) else None


def parse_telegram_user(data: dict, *, username: str = "") -> dict | None:
    if not isinstance(data, dict):
        return None
    user = data.get("user") if isinstance(data.get("user"), dict) else data
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
    photo = user.get("photo") if isinstance(user.get("photo"), dict) else {}
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
    ch = data.get("channel") if isinstance(data.get("channel"), dict) else data
    if not isinstance(ch, dict):
        return None
    uname = _first_str(ch.get("username"), username).lstrip("@")
    title = _first_str(ch.get("title"), ch.get("name"), uname)
    if not uname and not title:
        return None
    photo = ch.get("photo") if isinstance(ch.get("photo"), dict) else {}
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


async def fetch_instagram_social_post(url: str) -> SocialPost | None:
    code = instagram_shortcode_from_url(url)
    if not code:
        return None
    data = await instagram_post(code)
    if not data:
        return None
    return parse_instagram_post(data, source_url=url)


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
            post = parse_tiktok_post(data, source_url=url)
            if post and post.media_urls:
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
            post = parse_tiktok_post(data, source_url=url)
            if post:
                return post

    
    if not m:
        data = await tiktok_shortcode(url)
        if data:
            return parse_tiktok_post(data, source_url=url)
    return None
