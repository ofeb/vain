"""Decode instasave response and verify download works."""
from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aiohttp

URL = "https://www.instagram.com/reel/DXbTOzTjWjW/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def decode_jwt_payload(token: str) -> dict:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    pad = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        raw = base64.urlsafe_b64decode(pad.encode())
        return json.loads(raw)
    except Exception as e:
        print("jwt decode fail", e)
        return {}


async def main():
    h = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Origin": "https://instasave.website",
        "Referer": "https://instasave.website/",
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(
            "https://api.instasave.website/media",
            json={"url": URL},
            headers=h,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as r:
            text = await r.text()
            print("status", r.status, "len", len(text))

        # extract tokens and hrefs
        tokens = re.findall(r"token=([A-Za-z0-9_\-\.]+)", text)
        print("tokens", len(tokens))
        media_urls = []
        for tok in tokens:
            payload = decode_jwt_payload(tok)
            if not payload:
                continue
            print("payload keys", payload.keys())
            print(" filename", payload.get("filename"))
            print(" url", str(payload.get("url", ""))[:200])
            if payload.get("url"):
                media_urls.append(payload["url"])

        # also extract plain cdn.instasave links
        cdn = re.findall(r"https://cdn\.instasave\.website/\?token=[A-Za-z0-9_\-\.]+", text)
        print("cdn links", len(cdn))
        for c in cdn[:5]:
            print(" ", c[:120])

        # extract href download links from escaped html
        unescaped = text.encode("utf-8").decode("unicode_escape") if "\\x" in text else text
        unescaped = unescaped.replace("\\/", "/")
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', unescaped)
        print("hrefs", len(hrefs))
        for hurl in hrefs[:10]:
            print(" HREF", hurl[:160])

        # try downloading first media_url or cdn token
        target = None
        if media_urls:
            # prefer mp4
            vids = [u for u in media_urls if ".mp4" in u.lower() or "video" in u.lower()]
            target = vids[0] if vids else media_urls[0]
        elif cdn:
            target = cdn[0]

        if not target:
            print("NO TARGET")
            return

        print("DOWNLOADING", target[:180])
        async with s.get(target, headers={"User-Agent": UA}, timeout=aiohttp.ClientTimeout(total=45)) as r:
            data = await r.read()
            print("dl status", r.status, "ctype", r.content_type, "bytes", len(data), "head", data[:12])
            out = Path("scripts/_ig_test.bin")
            out.write_bytes(data)
            print("saved", out)


if __name__ == "__main__":
    asyncio.run(main())
