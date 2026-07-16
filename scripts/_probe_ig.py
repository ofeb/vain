"""Probe Instagram download sources that do NOT need session cookies."""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp

URL = "https://www.instagram.com/reel/DXbTOzTjWjW/"
CODE = "DXbTOzTjWjW"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


async def try_req(s, name, method, url, **kw):
    try:
        async with s.request(method, url, timeout=aiohttp.ClientTimeout(total=25), **kw) as r:
            text = await r.text()
            mp4 = re.findall(r"https?://[^\"'\\s<>]+\.mp4[^\"'\\s<>]*", text)
            vurls = re.findall(
                r"(?:video_url|download_url|\"url\")\s*[:=]\s*\"(https:[^\"]+)\"",
                text,
                re.I,
            )
            print(f"{name}: {r.status} len={len(text)} mp4={len(mp4)} urls={len(vurls)}")
            if mp4:
                print("  mp4", mp4[0][:180])
            elif vurls:
                print("  url", vurls[0][:180].replace("\\/", "/"))
            else:
                print("  head", text[:160].replace("\n", " "))
            return r.status, text, [u.replace("\\/", "/") for u in (mp4 or vurls)]
    except Exception as e:
        print(f"{name}: ERR {type(e).__name__}: {e}")
        return 0, "", []


async def main():
    h = {"User-Agent": UA, "Accept": "*/*"}
    async with aiohttp.ClientSession(headers=h) as s:
        tests = [
            (
                "saveig",
                "POST",
                "https://v3.saveig.app/api/ajaxSearch",
                {
                    "data": {"q": URL, "t": "media", "lang": "en"},
                    "headers": {
                        **h,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-Requested-With": "XMLHttpRequest",
                        "Origin": "https://saveig.app",
                        "Referer": "https://saveig.app/",
                    },
                },
            ),
            (
                "downloadgram",
                "POST",
                "https://downloadgram.org/wp-json/aio-dl/video-data/",
                {
                    "data": {"url": URL},
                    "headers": {
                        **h,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": "https://downloadgram.org",
                        "Referer": "https://downloadgram.org/",
                    },
                },
            ),
            (
                "ddinstagram",
                "GET",
                f"https://www.ddinstagram.com/reel/{CODE}",
                {"headers": {**h, "Accept": "text/html"}},
            ),
            (
                "kkinstagram",
                "GET",
                f"https://www.kkinstagram.com/reel/{CODE}",
                {"headers": {**h, "Accept": "text/html"}},
            ),
            (
                "storiesig",
                "GET",
                f"https://storiesig.info/api/ig/postInfo?url={URL}",
                {},
            ),
            (
                "anonyig",
                "POST",
                "https://anonyig.com/api/v1/post",
                {
                    "json": {"url": URL},
                    "headers": {
                        **h,
                        "Content-Type": "application/json",
                        "Origin": "https://anonyig.com",
                    },
                },
            ),
            (
                "instasave",
                "POST",
                "https://api.instasave.website/media",
                {
                    "json": {"url": URL},
                    "headers": {**h, "Content-Type": "application/json"},
                },
            ),
            (
                "cobalt_wuk",
                "POST",
                "https://co.wuk.sh/",
                {
                    "json": {"url": URL},
                    "headers": {
                        **h,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                },
            ),
            (
                "cobalt_best",
                "POST",
                "https://api.cobalt.best/",
                {
                    "json": {"url": URL},
                    "headers": {
                        **h,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                },
            ),
            (
                "snapinsta_io",
                "POST",
                "https://snapinsta.io/api/ajaxSearch",
                {
                    "data": {"q": URL, "t": "media", "lang": "en"},
                    "headers": {
                        **h,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-Requested-With": "XMLHttpRequest",
                        "Origin": "https://snapinsta.io",
                        "Referer": "https://snapinsta.io/",
                    },
                },
            ),
            (
                "igmate",
                "GET",
                f"https://api.igmate.net/api/media?url={URL}",
                {},
            ),
            (
                "ez-downloader",
                "POST",
                "https://api.ez-downloader.com/api/convert",
                {
                    "json": {"url": URL},
                    "headers": {**h, "Content-Type": "application/json"},
                },
            ),
            (
                "indown",
                "POST",
                "https://indown.io/download",
                {
                    "data": {"link": URL},
                    "headers": {
                        **h,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": "https://indown.io",
                        "Referer": "https://indown.io/",
                    },
                },
            ),
            (
                "igram_world",
                "GET",
                f"https://api.igram.world/api/media?url={URL}",
                {},
            ),
            (
                "v3.igdownloader",
                "POST",
                "https://v3.igdownloader.app/api/ajaxSearch",
                {
                    "data": {"q": URL, "t": "media", "lang": "en"},
                    "headers": {
                        **h,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                },
            ),
        ]
        winners = []
        for name, method, url, kw in tests:
            status, text, urls = await try_req(s, name, method, url, **kw)
            if urls and status and status < 400:
                winners.append((name, urls[0][:120]))
        print("\nWINNERS:", winners or "none")


if __name__ == "__main__":
    asyncio.run(main())
