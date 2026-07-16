"""Deeper probe of promising Instagram sources."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aiohttp

URL = "https://www.instagram.com/reel/DXbTOzTjWjW/"
CODE = "DXbTOzTjWjW"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def find_media(text: str) -> list[str]:
    found = []
    # unescape common forms
    raw = (
        text.replace("\\/", "/")
        .replace("\\u0026", "&")
        .replace("\\x20", " ")
        .replace("\\x22", '"')
        .replace("\\x27", "'")
    )
    patterns = [
        r'https?://[^"\'\s<>]+\.mp4[^"\'\s<>]*',
        r'https?://[^"\'\s<>]*cdninstagram[^"\'\s<>]*',
        r'https?://[^"\'\s<>]*fbcdn[^"\'\s<>]*',
        r'https?://scontent[^"\'\s<>]+',
    ]
    for pat in patterns:
        for m in re.findall(pat, raw, re.I):
            u = unquote(m).strip("\\\"'")
            if u not in found and len(u) > 30:
                found.append(u)
    return found


async def dump(name, method, url, **kw):
    h = {"User-Agent": UA, "Accept": "*/*"}
    async with aiohttp.ClientSession(headers=h) as s:
        try:
            async with s.request(method, url, timeout=aiohttp.ClientTimeout(total=30), **kw) as r:
                text = await r.text()
                media = find_media(text)
                print(f"\n=== {name} status={r.status} len={len(text)} media={len(media)} ===")
                for u in media[:5]:
                    print(" MEDIA", u[:200])
                if not media:
                    print(text[:500].replace("\n", " "))
                # try parse json
                try:
                    data = json.loads(text)
                    print(" JSON keys", list(data)[:20] if isinstance(data, dict) else type(data))
                    print(json.dumps(data, indent=0)[:800])
                except Exception:
                    pass
                return media
        except Exception as e:
            print(f"{name}: ERR {type(e).__name__}: {e}")
            return []


async def main():
    await dump(
        "instasave",
        "POST",
        "https://api.instasave.website/media",
        json={"url": URL},
        headers={"User-Agent": UA, "Content-Type": "application/json", "Origin": "https://instasave.website", "Referer": "https://instasave.website/"},
    )
    await dump(
        "instasave2",
        "POST",
        "https://api.instasave.website/media",
        data={"url": URL},
        headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded", "Origin": "https://instasave.website", "Referer": "https://instasave.website/"},
    )
    # common save-style sites with k token
    await dump(
        "snapcdn",
        "POST",
        "https://snapcdn.app/api/ajaxSearch",
        data={"q": URL, "t": "media", "lang": "en"},
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://snapcdn.app",
            "Referer": "https://snapcdn.app/",
        },
    )
    await dump(
        "igdownloader",
        "POST",
        "https://igdownloader.app/api/ajaxSearch",
        data={"q": URL, "t": "media", "lang": "en"},
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://igdownloader.app",
            "Referer": "https://igdownloader.app/",
        },
    )
    await dump(
        "gramsnap",
        "POST",
        "https://gramsnap.com/api/ajaxSearch",
        data={"q": URL, "t": "media", "lang": "en"},
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://gramsnap.com",
            "Referer": "https://gramsnap.com/",
        },
    )
    await dump(
        "instastories",
        "GET",
        f"https://www.instagram.com/p/{CODE}/embed/captioned/",
        headers={"User-Agent": UA, "Accept": "text/html"},
    )
    await dump(
        "embed",
        "GET",
        f"https://www.instagram.com/reel/{CODE}/embed/",
        headers={"User-Agent": UA, "Accept": "text/html"},
    )
    # oembed
    await dump(
        "oembed",
        "GET",
        f"https://www.instagram.com/api/v1/oembed/?url={URL}",
        headers={"User-Agent": UA, "X-IG-App-ID": "936619743392459"},
    )
    # public graphql doc ids (often change)
    await dump(
        "web_profile",
        "GET",
        "https://i.instagram.com/api/v1/users/web_profile_info/?username=instagram",
        headers={
            "User-Agent": UA,
            "X-IG-App-ID": "936619743392459",
            "Accept": "*/*",
        },
    )
    # try rapidapi free-ish style public wrappers
    await dump(
        "rosp",
        "GET",
        f"https://instagram-looter2.p.rapidapi.com/post?url={URL}",
        headers={"User-Agent": UA},
    )
    # another known public endpoint
    await dump(
        "for-devs",
        "GET",
        f"https://instagram-downloader-download-instagram-videos-stories1.p.rapidapi.com/get-info-rapidapi?url={URL}",
        headers={"User-Agent": UA},
    )
    # tikwm style for ig? no
    # use expertgram / toolzu
    await dump(
        "toolzu",
        "POST",
        "https://api.toolzu.com/tools/download/instagram",
        json={"url": URL},
        headers={"User-Agent": UA, "Content-Type": "application/json", "Origin": "https://toolzu.com"},
    )
    await dump(
        "expertgram",
        "POST",
        "https://api.expertgram.net/media",
        json={"url": URL},
        headers={"User-Agent": UA, "Content-Type": "application/json"},
    )
    # SaveFrom style
    await dump(
        "sssinstagram",
        "POST",
        "https://sssinstagram.com/request",
        json={"url": URL},
        headers={"User-Agent": UA, "Content-Type": "application/json", "Origin": "https://sssinstagram.com"},
    )


if __name__ == "__main__":
    asyncio.run(main())
