import asyncio
import re
import aiohttp

URL = "https://www.tiktok.com/@scout2015/video/6718339392112823557"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

async def try_one(s, name, method, url, **kw):
    try:
        async with s.request(method, url, timeout=aiohttp.ClientTimeout(total=25), **kw) as r:
            text = await r.text()
            mp4 = re.findall(r"https?://[^\"'\\s<>]+\.mp4[^\"'\\s<>]*", text)
            print(f"{name}: {r.status} len={len(text)} mp4={len(mp4)}")
            print(" ", text[:220].replace("\n", " "))
            if mp4:
                print("  mp4", mp4[0][:140])
            return text
    except Exception as e:
        print(f"{name}: ERR {type(e).__name__}: {e}")
        return ""

async def main():
    h = {"User-Agent": UA}
    async with aiohttp.ClientSession(headers=h) as s:
        await try_one(s, "tikwm_post", "POST", "https://www.tikwm.com/api/",
            data={"url": URL, "hd": "1"},
            headers={**h, "Referer": "https://www.tikwm.com/", "Content-Type": "application/x-www-form-urlencoded"})
        await try_one(s, "tikwm_get", "GET", f"https://www.tikwm.com/api/?url={URL}&hd=1",
            headers={**h, "Referer": "https://www.tikwm.com/"})
        await try_one(s, "tikmate", "POST", "https://api.tikmate.app/api/lookup", data={"url": URL})
        await try_one(s, "tikdown", "GET", f"https://api.tiklydown.eu.org/api/download/v3?url={URL}")
        await try_one(s, "tikdown2", "GET", f"https://api.tiklydown.eu.org/api/download?url={URL}")
        await try_one(s, "ssstik", "POST", "https://ssstik.io/abc?url=dl",
            data={"id": URL, "locale": "en", "tt": "0"},
            headers={**h, "Content-Type": "application/x-www-form-urlencoded", "Origin": "https://ssstik.io", "Referer": "https://ssstik.io/"})
        await try_one(s, "ttdownloader", "POST", "https://ttdownloader.com/search/",
            data={"url": URL},
            headers={**h, "Content-Type": "application/x-www-form-urlencoded", "Origin": "https://ttdownloader.com", "Referer": "https://ttdownloader.com/"})
        await try_one(s, "musicaldown", "POST", "https://musicaldown.com/download",
            data={"url": URL},
            headers={**h, "Content-Type": "application/x-www-form-urlencoded", "Origin": "https://musicaldown.com", "Referer": "https://musicaldown.com/"})
        await try_one(s, "tiktok_scraper", "GET", f"https://www.tiktok.com/oembed?url={URL}")
        # double click / alternative
        await try_one(s, "tikwm_v2", "POST", "https://tikwm.com/api/",
            data={"url": URL, "hd": 1},
            headers={**h, "Referer": "https://tikwm.com/", "Content-Type": "application/x-www-form-urlencoded"})

asyncio.run(main())
