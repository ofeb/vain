import asyncio
import re

import aiohttp

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


async def main() -> None:
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        async with session.get(
            "https://duckduckgo.com/",
            params={"q": "cats", "iax": "images", "ia": "images"},
        ) as resp:
            html = await resp.text()
        match = re.search(r"vqd=['\"]([^'\"]+)['\"]", html)
        print("vqd", bool(match))
        if not match:
            return
        vqd = match.group(1)
        async with session.get(
            "https://duckduckgo.com/i.js",
            params={"l": "us-en", "o": "json", "q": "cats", "vqd": vqd, "f": ",,,", "p": "1"},
            headers={**_HEADERS, "Referer": "https://duckduckgo.com/"},
        ) as resp:
            text = await resp.text()
            print("i.js", resp.status, len(text), text[:100])


if __name__ == "__main__":
    asyncio.run(main())
