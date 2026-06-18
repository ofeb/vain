"""social media platform api clients.
each file wraps one platform api.
from core.networks.social import TikTok Twitter YouTube"""

from .tiktok import TikTok
from .twitter import Twitter
from .youtube import YouTube
from .ig import Instagram

__all__ = ["TikTok", "Twitter", "YouTube", "Instagram"]
