from __future__ import annotations

from typing import Any
from urllib.parse import quote

import aiohttp


class GoogleTranslateClient:
    """Unofficial free Google Translate endpoint (translate.googleapis.com)."""

    BASE = "https://translate.googleapis.com/translate_a/single"

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is not None and not self._session.closed:
            return self._session
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"User-Agent": "Mozilla/5.0"},
        )

    async def translate(
        self,
        text: str,
        *,
        to_lang: str = "en",
        from_lang: str | None = None,
    ) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {"lang": from_lang or "auto", "text": ""}

        sl = (from_lang or "auto").strip().lower() or "auto"
        tl = (to_lang or "en").strip().lower() or "en"
        params = {
            "client": "gtx",
            "sl": sl,
            "tl": tl,
            "dt": "t",
            "q": text,
        }
        own = self._session is None or self._session.closed
        session = await self._session_get()
        try:
            async with session.get(self.BASE, params=params) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"translate HTTP {resp.status}: {body[:200]}")
                data = await resp.json(content_type=None)
        finally:
            if own and session is not self._session:
                await session.close()

        # data[0] is list of [translated, original, ...] segments
        parts: list[str] = []
        try:
            for seg in data[0] or []:
                if seg and seg[0]:
                    parts.append(str(seg[0]))
        except Exception:
            parts = [str(data)]

        detected = sl
        try:
            if isinstance(data, list) and len(data) > 2 and data[2]:
                detected = str(data[2])
        except Exception:
            pass

        return {"lang": detected, "text": "".join(parts).strip()}
