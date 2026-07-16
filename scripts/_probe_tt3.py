import asyncio
import re
import aiohttp

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

async def main():
    async with aiohttp.ClientSession(headers={"User-Agent": UA}) as s:
        # get a live link from tikwm homepage or random
        # try douyin/tiktok via snaptik
        candidates = []
        # scrape snaptik homepage? 
        # try popular fixed demo urls used by downloader sites
        demos = [
            "https://www.tiktok.com/@tiktok/video/7095677593139916075",
            "https://www.tiktok.com/@scout2015/video/6718339392112823557?is_from_webapp=1",
            "https://m.tiktok.com/v/6718339392112823557.html",
        ]
        # also pull example from musicaldown
        try:
            async with s.get("https://musicaldown.com/", timeout=aiohttp.ClientTimeout(total=15)) as r:
                html = await r.text()
            # find placeholder or example urls
            found = re.findall(r"https?://(?:www\.)?tiktok\.com/[^\s\"'<>]+", html)
            demos.extend(found[:5])
            print("from musicaldown", found[:5])
        except Exception as e:
            print("musicaldown home", e)

        try:
            async with s.get("https://snaptik.app/", timeout=aiohttp.ClientTimeout(total=15)) as r:
                html = await r.text()
            found = re.findall(r"https?://(?:www\.)?tiktok\.com/[^\s\"'<>]+", html)
            demos.extend(found[:5])
            print("from snaptik", found[:5])
        except Exception as e:
            print("snaptik", e)

        # try tiktok explore page for video links
        try:
            async with s.get("https://www.tiktok.com/explore", timeout=aiohttp.ClientTimeout(total=15)) as r:
                html = await r.text()
            found = re.findall(r"/@[\w.-]+/video/(\d+)", html)
            print("explore ids", found[:10])
            for vid in found[:5]:
                demos.append(f"https://www.tiktok.com/@x/video/{vid}")
        except Exception as e:
            print("explore", e)

        demos = list(dict.fromkeys(demos))
        print("trying", len(demos), "urls")
        for u in demos:
            try:
                async with s.post(
                    "https://www.tikwm.com/api/",
                    data={"url": u, "hd": "1"},
                    headers={
                        "User-Agent": UA,
                        "Referer": "https://www.tikwm.com/",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as r:
                    data = await r.json(content_type=None)
                code = data.get("code")
                d = data.get("data") or {}
                play = d.get("hdplay") or d.get("play")
                print("OK" if play else "NO", code, u[:70], (play or data.get("msg",""))[:80])
                if play:
                    # download head
                    async with s.get(play, timeout=aiohttp.ClientTimeout(total=20)) as dr:
                        blob = await dr.read()
                        print("  DL", dr.status, dr.content_type, len(blob), blob[:8])
                    break
            except Exception as e:
                print("ERR", u[:50], type(e).__name__, e)

asyncio.run(main())
