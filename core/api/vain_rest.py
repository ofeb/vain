"""vain.rest API client.

Docs: https://vain.rest/docs  (OpenAPI: https://vain.rest/docs/openapi.json)

Primary source for TikTok / Instagram / Twitter / Reddit / GitHub / Brave.
Auth: ``X-API-Key`` header (from env ``VAIN_REST_API_KEY`` or ``api.vain_rest``).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import aiohttp

from .models import (
    BraveImages,
    BraveResult,
    BraveSearch,
    GitHubCommit,
    GitHubRepo,
    GitHubRepoOwner,
    GitHubUser,
    InstagramComment,
    InstagramFollower,
    InstagramHighlight,
    InstagramPostMedia,
    InstagramProfile,
    InstagramStory,
    RedditComment,
    RedditPost,
    RedditSearch,
    RedditUser,
    SubReddit,
    TikTokPost,
    TikTokProfile,
    TwitterMedia,
    TwitterTweet,
    TwitterUser,
    TwitterUserBiolinks,
)

log = logging.getLogger("vain.api.vain_rest")

_BASE = "https://vain.rest"


def _default_api_key() -> str:
    env = (os.environ.get("VAIN_REST_API_KEY") or "").strip()
    if env:
        return env
    try:
        from config import api as api_cfg

        return str(getattr(api_cfg, "vain_rest", "") or "").strip()
    except Exception:
        return ""


class VainRest:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = (api_key if api_key is not None else _default_api_key()).strip()

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        
        clean_params: dict[str, Any] | None = None
        if params:
            clean_params = {
                k: v for k, v in params.items() if v is not None and v != ""
            }
            if not clean_params:
                clean_params = None

        url = f"{_BASE}{path}"
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method, url, params=clean_params, headers=headers
            ) as resp:
                ctype = (resp.content_type or "").lower()
                if "json" in ctype:
                    data = await resp.json(content_type=None)
                else:
                    text = await resp.text()
                    if resp.status >= 400:
                        raise RuntimeError(f"vain.rest {resp.status}: {text[:200]}")
                    return text
                if resp.status >= 400:
                    detail = data
                    if isinstance(data, dict):
                        detail = data.get("detail") or data.get("error") or data
                    raise RuntimeError(f"vain.rest {resp.status}: {str(detail)[:200]}")
                return data

    

    async def instagram_media(
        self,
        shortcode: Optional[str] = None,
        url: Optional[str] = None,
    ) -> List[InstagramPostMedia]:
        data = await self._request(
            "GET",
            "/instagram/media",
            params={"shortcode": shortcode, "url": url},
        )
        if not data:
            return []
        return [InstagramPostMedia(**item) for item in data]

    async def instagram_profile(self, username: str) -> InstagramProfile:
        data = await self._request("GET", f"/instagram/profile/{username}")
        if not data:
            raise RuntimeError(f"No Instagram profile found for @{username}")
        return InstagramProfile(**data)

    async def instagram_stories(self, username: str) -> List[InstagramStory]:
        data = await self._request("GET", f"/instagram/stories/{username}")
        if not data:
            return []
        return [InstagramStory(**item) for item in data]

    async def instagram_highlights(self, username: str) -> List[InstagramHighlight]:
        data = await self._request("GET", f"/instagram/highlights/{username}")
        if not data:
            return []
        return [InstagramHighlight(**item) for item in data]

    async def instagram_comments(self, shortcode: str) -> List[InstagramComment]:
        data = await self._request("GET", f"/instagram/comments/{shortcode}")
        if not data:
            return []
        return [InstagramComment(**item) for item in data]

    async def instagram_followers(self, username: str) -> List[InstagramFollower]:
        data = await self._request("GET", f"/instagram/followers/{username}")
        if not data:
            return []
        return [InstagramFollower(**item) for item in data]

    async def instagram_following(self, username: str) -> List[InstagramFollower]:
        data = await self._request("GET", f"/instagram/following/{username}")
        if not data:
            return []
        return [InstagramFollower(**item) for item in data]

    

    async def tiktok_profile(self, username: str) -> TikTokProfile:
        username = (username or "").strip().lstrip("@")
        data = await self._request("GET", f"/tiktok/profile/{username}")
        if not data:
            raise RuntimeError(f"No TikTok profile found for @{username}")
        return TikTokProfile(**data)

    async def tiktok_video(self, username: str, post_id: str) -> TikTokPost:
        """GET /tiktok/video/{username}/{post_id} — docs: vain.rest/docs"""
        username = (username or "").strip().lstrip("@")
        post_id = (post_id or "").strip()
        if not username or not post_id:
            raise RuntimeError("TikTok video requires username and post_id")
        data = await self._request("GET", f"/tiktok/video/{username}/{post_id}")
        if not data:
            raise RuntimeError(f"No TikTok video found for {username}/{post_id}")
        return TikTokPost(**data)

    

    async def twitter_profile(self, username: str) -> TwitterUser:
        data = await self._request("GET", f"/twitter/profile/{username}")
        if not data:
            raise RuntimeError(f"No Twitter profile found for @{username}")
        return TwitterUser(**data)

    async def twitter_tweet(self, post_id: str) -> TwitterTweet:
        data = await self._request("GET", f"/twitter/tweet/{post_id}")
        if not data:
            raise RuntimeError(f"No Twitter tweet found for id {post_id}")
        return TwitterTweet(**data)

    async def twitter_tweets(self, username: str) -> List[TwitterTweet]:
        data = await self._request("GET", f"/twitter/tweets/{username}")
        if not data:
            return []
        return [TwitterTweet(**item) for item in data]

    

    async def github_user(self, username: str) -> GitHubUser:
        data = await self._request("GET", f"/github/user/{username}")
        if not data:
            raise RuntimeError(f"No GitHub user found for {username}")
        return GitHubUser(**data)

    async def github_repo(self, username: str, repo_name: str) -> GitHubRepo:
        data = await self._request("GET", f"/github/repo/{username}/{repo_name}")
        if not data:
            raise RuntimeError(f"No GitHub repo found for {username}/{repo_name}")
        return GitHubRepo(**data)

    async def github_repos(self, username: str, limit: int = 50) -> List[GitHubRepo]:
        data = await self._request(
            "GET", f"/github/repos/{username}", params={"limit": limit}
        )
        if not data:
            return []
        return [GitHubRepo(**item) for item in data]

    async def github_commits(
        self, username: str, repo_name: str, limit: int = 30
    ) -> List[GitHubCommit]:
        data = await self._request(
            "GET",
            f"/github/commits/{username}/{repo_name}",
            params={"limit": limit},
        )
        if not data:
            return []
        return [GitHubCommit(**item) for item in data]

    

    async def reddit_subreddit(self, name: str) -> SubReddit:
        data = await self._request("GET", f"/reddit/subreddit/{name}")
        if not data:
            raise RuntimeError(f"No subreddit found for r/{name}")
        return SubReddit(**data)

    async def reddit_subreddit_posts(
        self, name: str, sort: str = "new", limit: int = 10
    ) -> List[RedditPost]:
        data = await self._request(
            "GET",
            f"/reddit/subreddit/{name}/posts",
            params={"sort": sort, "limit": limit},
        )
        if not data:
            return []
        return [RedditPost(**item) for item in data]

    async def reddit_post(self, url: str) -> RedditPost:
        data = await self._request("GET", "/reddit/post", params={"url": url})
        if not data:
            raise RuntimeError(f"No Reddit post found for {url}")
        return RedditPost(**data)

    async def reddit_user(self, username: str) -> RedditUser:
        data = await self._request("GET", f"/reddit/user/{username}")
        if not data:
            raise RuntimeError(f"No Reddit user found for u/{username}")
        return RedditUser(**data)

    async def reddit_search(
        self, query: str, sort: str = "relevance", limit: int = 10
    ) -> List[RedditSearch]:
        data = await self._request(
            "GET",
            "/reddit/search",
            params={"sort": sort, "limit": limit},
        )
        if not data:
            return []
        return [RedditSearch(**item) for item in data]

    async def reddit_comments(self, url: str) -> List[RedditComment]:
        data = await self._request("GET", "/reddit/comments", params={"url": url})
        if not data:
            return []
        return [RedditComment(**item) for item in data]

    

    async def brave_search(
        self, query: str, safe: bool = True, limit: int = 10
    ) -> BraveSearch:
        data = await self._request(
            "GET",
            "/brave/search",
            params={"q": query, "safesearch": "strict" if safe else "off", "limit": limit},
        )
        if not data:
            return BraveSearch(query=query, results=[])
        return BraveSearch(
            query=data.get("query", query),
            results=[BraveResult(**r) for r in data.get("results", [])],
        )

    async def brave_images(
        self, query: str, safe: bool = True, limit: int = 25
    ) -> BraveImages:
        data = await self._request(
            "GET",
            "/brave/images",
            params={"q": query, "safesearch": "strict" if safe else "off", "limit": limit},
        )
        if not data:
            return BraveImages(query=query, images=[])
        return BraveImages(
            query=data.get("query", query),
            images=data.get("images", []),
        )

    

    async def instagram_resolve_media(self, url: str) -> Dict[str, Any]:
        code = _shortcode_from_url(url)
        if not code:
            raise RuntimeError("This is not a valid instagram post url.")

        media_items = await self.instagram_media(shortcode=code, url=url)
        if not media_items:
            raise RuntimeError("Could not resolve Instagram media for that URL.")

        video_urls: List[str] = []
        image_urls: List[str] = []
        for m in media_items:
            if m.video_url:
                video_urls.append(m.video_url)
            if m.image_urls:
                image_urls.extend(m.image_urls)

        author_name = media_items[0].owner_username or "unknown"
        title = media_items[0].caption or ""

        return {
            "code": code,
            "video_urls": video_urls,
            "image_urls": image_urls,
            "author_name": author_name,
            "title": title,
            "source": "vain.rest",
        }

    async def instagram_get_video_url(self, url: str) -> Optional[str]:
        resolved = await self.instagram_resolve_media(url)
        videos = resolved.get("video_urls") or []
        return videos[0] if videos else None

    async def instagram_get_post(self, url: str) -> List[Dict[str, Any]]:
        resolved = await self.instagram_resolve_media(url)
        video_urls = resolved.get("video_urls") or []
        image_urls = resolved.get("image_urls") or []
        author = resolved.get("author_name") or "unknown"
        title = resolved.get("title") or ""
        media_type = 2 if video_urls else 1

        return [
            {
                "pk": resolved.get("code", ""),
                "id": resolved.get("code", ""),
                "code": resolved.get("code", ""),
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
        ]

    async def instagram_get_user(self, username: str) -> Dict[str, Any]:
        profile = await self.instagram_profile(username)
        return {
            "pk": profile.id,
            "username": profile.username,
            "full_name": profile.full_name or profile.username,
            "is_private": profile.is_private,
            "is_verified": profile.is_verified,
            "media_count": profile.posts_count,
            "followers": profile.followers_count,
            "following": profile.following_count,
            "biography": profile.biography,
            "avatar": profile.profile_pic_url_hd or profile.profile_pic_url,
            "is_business": profile.is_business,
        }

    async def instagram_download_media(self, media_url: str) -> bytes:
        async with aiohttp.ClientSession() as session:
            async with session.get(media_url) as resp:
                resp.raise_for_status()
                return await resp.read()


def _shortcode_from_url(url: str) -> Optional[str]:
    import re
    from urllib.parse import urlparse

    match = re.search(
        r"(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv|reels)/(?P<code>[A-Za-z0-9_-]+)",
        url or "",
        re.I,
    )
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
