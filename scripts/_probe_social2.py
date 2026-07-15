import asyncio
import json

import aiohttp


TT = "https://www.tiktok.com/@scout2015/video/6718339392112823553"
IG = "https://www.instagram.com/reel/DXbTOzTjWjW/"


async def hit(s, name, method, url, **kw):
    try:
        async with s.request(method, url, timeout=aiohttp.ClientTimeout(total=12), **kw) as r:
            txt = await r.text()
            print(f"\n=== {name} {r.status} ===")
            print(txt[:500])
    except Exception as e:
        print(f"\n=== {name} ERR {type(e).__name__}: {e}")


async def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    async with aiohttp.ClientSession(headers=headers) as s:
        await hit(s, "tikwm-get", "GET", "https://www.tikwm.com/api/", params={"url": TT, "hd": 1})
        await hit(
            s,
            "tikwm-post",
            "POST",
            "https://www.tikwm.com/api/",
            data={"url": TT, "hd": 1},
        )
        await hit(
            s,
            "tikmate",
            "POST",
            "https://api.tikmate.app/api/lookup",
            data={"url": TT},
        )
        await hit(
            s,
            "douyin",
            "GET",
            "https://api.douyin.wtf/api",
            params={"url": TT, "minimal": "false"},
        )
        await hit(
            s,
            "tiktok-scraper",
            "GET",
            f"https://www.tiktok.com/node/share/video/@scout2015/6718339392112823553",
        )
        # ig graph public
        await hit(
            s,
            "ig-gql",
            "GET",
            "https://www.instagram.com/graphql/query/",
            params={
                "query_hash": "b3055c01b4b222b8a47dc12b090e4e64",
                "variables": json.dumps({"shortcode": "DXbTOzTjWjW"}),
            },
        )
        # saveig style
        await hit(
            s,
            "snapinsta",
            "POST",
            "https://snapinsta.to/api/ajaxSearch",
            data={"q": IG, "t": "media", "lang": "en"},
            headers={**headers, "X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded"},
        )


if __name__ == "__main__":
    asyncio.run(main())
