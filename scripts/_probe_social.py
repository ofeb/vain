import asyncio
import json
import re

import aiohttp


async def test():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "X-IG-App-ID": "936619743392459",
    }
    ig = "https://www.instagram.com/reel/DXbTOzTjWjW/"
    async with aiohttp.ClientSession(headers=headers) as s:
        async with s.get(
            "https://www.instagram.com/api/v1/oembed/?url=" + ig,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            data = await r.json()
            print("OEMBED", json.dumps(data, indent=2)[:2000])

        async with s.get(
            "https://www.instagram.com/reel/DXbTOzTjWjW/embed/captioned/",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            html = await r.text()
            print("embed status", r.status, "len", len(html))
            vids = re.findall(r"https://[^\s\"']+\.mp4[^\s\"']*", html)
            print("vids", len(vids))
            for v in vids[:3]:
                print(" V", v[:160])
            for pat in ("video_url", "video_versions", "playback_url", "contentUrl", "og:video"):
                print(pat, pat in html)

        
        
        for name, method, url, kw in [
            (
                "ddig",
                "get",
                "https://www.ddinstagram.com/reel/DXbTOzTjWjW/",
                {},
            ),
        ]:
            try:
                async with s.request(method, url, timeout=aiohttp.ClientTimeout(total=10), **kw) as r:
                    txt = await r.text()
                    print(name, r.status, txt[:200].replace("\n", " "))
            except Exception as e:
                print(name, e)


if __name__ == "__main__":
    asyncio.run(test())
