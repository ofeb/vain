"""twitter api client for tweet lookup.
uses syndication api so no auth needed.
use Twitter class methods directly"""

import aiohttp
from typing import Optional


class Twitter:
    """twitter public api wrapper"""

    SYND = "https://cdn.syndication.twimg.com/tweet-result"

    async def tweet(self, tweet_id: str) -> Optional[dict]:
        """get tweet data by id"""
        async with aiohttp.ClientSession() as s:
            async with s.get(self.SYND, params={"id": tweet_id, "lang": "en"}) as r:
                if r.status != 200:
                    return None
                return await r.json()
