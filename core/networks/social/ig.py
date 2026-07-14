"""instagram public api client using i.instagram.com.
fetches public profile and post metadata. no auth for public accounts."""

import aiohttp
import re
from typing import Optional

_SHORT_RE = re.compile(r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/([\w-]+)")


class Instagram:
    """instagram unofficial api wrapper using i.instagram.com mobile endpoints"""

    HDR = {
        "User-Agent": "Instagram 123.0.0.21.114 (iPhone; CPU iPhone OS 11_0 like Mac OS X) AppleWebKit/604.1.38 (KHTML, like Gecko)",
        "Accept": "*/*",
        "Accept-Language": "en-US",
    }

    async def post(self, url: str) -> Optional[dict]:
        """get rich metadata for a post or reel via i.instagram.com"""
        m = _SHORT_RE.match(url)
        if not m:
            return None
        code = m.group(1)
        endpoint = f"https://i.instagram.com/api/v1/media/{code}/info/"
        async with aiohttp.ClientSession(headers=self.HDR) as s:
            try:
                async with s.get(endpoint) as r:
                    if r.status != 200:
                        return None
                    data = await r.json()
                    item = (data.get("items") or [None])[0]
                    if not item:
                        return None
                    
                    user = item.get("user", {})
                    caption = (item.get("caption") or {}).get("text", "") or ""
                    video_url = item.get("video_versions", [{}])[0].get("url") if item.get("video_versions") else None
                    image_url = item.get("image_versions2", {}).get("candidates", [{}])[0].get("url")
                    media_url = video_url or image_url
                    return {
                        "shortcode": code,
                        "username": user.get("username"),
                        "full_name": user.get("full_name"),
                        "avatar": user.get("profile_pic_url"),
                        "caption": caption[:1500],
                        "media_url": media_url,
                        "is_video": bool(video_url),
                        "like_count": item.get("like_count", 0),
                        "comment_count": item.get("comment_count", 0),
                        "url": f"https://www.instagram.com/p/{code}/",
                    }
            except Exception:
                return None

    async def profile(self, username: str) -> Optional[dict]:
        """get public profile via i.instagram.com web_profile_info"""
        endpoint = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
        async with aiohttp.ClientSession(headers=self.HDR) as s:
            try:
                async with s.get(endpoint) as r:
                    if r.status != 200:
                        return None
                    data = await r.json()
                    return (data.get("data") or {}).get("user")
            except Exception:
                return None
