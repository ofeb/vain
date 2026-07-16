import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aiohttp

URL = "https://www.instagram.com/reel/DXbTOzTjWjW/"
CODE = "DXbTOzTjWjW"


async def try_req(s, name, method, url, **kw):
    try:
        async with s.request(method, url, timeout=aiohttp.ClientTimeout(total=15), **kw) as r:
            text = await r.text()
            mp4 = re.findall(r"https?://[^\"'\\s<>]+\.mp4[^\"'\\s<>]*", text)
            print(f"{name}: {r.status} len={len(text)} mp4={len(mp4)}")
            if mp4:
                print("  SAMPLE", mp4[0][:180])
            else:
                print("  HEAD", text[:160].replace("\n", " "))
            return text, mp4
    except Exception as e:
        print(f"{name}: ERR {type(e).__name__}: {e}")
        return "", []


async def main():
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    async with aiohttp.ClientSession(headers=h) as s:
        await try_req(
            s,
            "snapinsta",
            "POST",
            "https://snapinsta.app/api/ajaxSearch",
            data={"q": URL, "t": "media", "lang": "en"},
            headers={
                **h,
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://snapinsta.app",
                "Referer": "https://snapinsta.app/",
            },
        )
        await try_req(s, "igram", "GET", f"https://api.igram.world/api/converting?url={URL}")
        await try_req(
            s,
            "fastdl",
            "POST",
            "https://fastdl.app/api/convert",
            json={"url": URL},
            headers={**h, "Content-Type": "application/json", "Origin": "https://fastdl.app"},
        )
        await try_req(
            s,
            "cobalt",
            "POST",
            "https://api.cobalt.tools/",
            json={"url": URL},
            headers={
                **h,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        # Anon IG graphql doc_id style
        await try_req(
            s,
            "web_info",
            "GET",
            f"https://www.instagram.com/api/v1/media/{CODE}/info/",
            headers={**h, "X-IG-App-ID": "936619743392459"},
        )


if __name__ == "__main__":
    asyncio.run(main())
