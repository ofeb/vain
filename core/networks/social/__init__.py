"""social media platform api clients.
each file wraps one platform api.
from core.networks.social import TikTok Twitter YouTube"""

from .tiktok import TikTok, is_tiktok_url
from .twitter import Twitter
from .youtube import YouTube
from .ig import Instagram, is_instagram_url
from .models import SocialPost

__all__ = [
    "TikTok",
    "Twitter",
    "YouTube",
    "Instagram",
    "SocialPost",
    "is_tiktok_url",
    "is_instagram_url",
]
