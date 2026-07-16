import asyncio
import aiohttp

async def main():
    # discover a working public tiktok via tikwm trending or known links
    urls = [
        "https://vm.tiktok.com/",  # not useful
        "https://www.tiktok.com/@willsmith/video/7067639219922996526",
        "https://www.tiktok.com/@khaby.lame/video/7004957048106773766",
        "https://www.tiktok.com/@charlidamelio/video/6818067085343370501",
        "https://vt.tiktok.com/ZSjrGQeEj/",
    ]
    async with aiohttp.ClientSession() as s:
        for u in urls:
            try:
                async with s.post(
                    "https://www.tikwm.com/api/",
                    data={"url": u, "hd": "1"},
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://www.tikwm.com/",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as r:
                    data = await r.json(content_type=None)
                    code = data.get("code") if isinstance(data, dict) else None
                    d = (data or {}).get("data") or {}
                    play = d.get("hdplay") or d.get("play")
                    print(u[:60], "code", code, "play", bool(play), (play or "")[:60])
            except Exception as e:
                print(u[:60], "ERR", type(e).__name__, e)

asyncio.run(main())
