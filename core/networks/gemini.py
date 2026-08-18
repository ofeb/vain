from __future__ import annotations

import base64
import json
from typing import Any

import aiohttp

from config import api as api_cfg


class GeminiClient:
    """Thin Gemini generateContent client (text + audio)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = (api_key or getattr(api_cfg, "gemini_api_key", "") or "").strip()
        self.model = (model or getattr(api_cfg, "gemini_model", None) or getattr(api_cfg, "llm", None) or "gemini-2.5-flash-lite").strip()
        self.base = "https://generativelanguage.googleapis.com/v1beta"

    def _url(self, method: str = "generateContent") -> str:
        return f"{self.base}/models/{self.model}:{method}?key={self.api_key}"

    async def _post(self, payload: dict[str, Any]) -> str:
        if not self.api_key:
            raise RuntimeError("Gemini API key is not configured")
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self._url(), json=payload) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    err = data.get("error", {}) if isinstance(data, dict) else {}
                    msg = err.get("message") or str(data)[:300]
                    raise RuntimeError(f"Gemini error: {msg}")
        return self._extract_text(data)

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        try:
            parts = data["candidates"][0]["content"]["parts"]
            texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
            return "\n".join(t for t in texts if t).strip()
        except Exception:
            return ""

    async def prompt(self, question: str, *, system: str | None = None) -> str:
        parts: list[dict[str, Any]] = []
        if system:
            parts.append({"text": system})
        parts.append({"text": question})
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048},
        }
        return await self._post(payload)

    async def translate(
        self,
        text: str,
        *,
        to_lang: str = "en",
        from_lang: str | None = None,
    ) -> dict[str, str]:
        src = from_lang or "auto"
        system = (
            "You are a precise translator. Respond with ONLY valid JSON, no markdown: "
            '{"lang":"<English name of the source language>","text":"<translated text only>"}'
        )
        prompt = (
            f"Detect the source language and translate the text to {to_lang}. "
            f"Hint for source language: {src}.\n\nText:\n{text}"
        )
        raw = await self.prompt(prompt, system=system)
        lang = from_lang or "Unknown"
        out = raw.strip()
        try:
            start = out.find("{")
            end = out.rfind("}")
            if start >= 0 and end > start:
                import json
                data = json.loads(out[start : end + 1])
                if isinstance(data, dict):
                    if data.get("lang"):
                        lang = str(data["lang"]).strip()
                    if data.get("text") is not None:
                        out = str(data["text"]).strip()
        except Exception:
            pass
        return {"lang": lang, "text": out}

    async def transcribe_audio(self, audio: bytes, *, mime_type: str = "audio/ogg") -> str:
        if not audio:
            raise RuntimeError("empty audio")
        b64 = base64.b64encode(audio).decode("ascii")
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type or "audio/ogg",
                                "data": b64,
                            }
                        },
                        {
                            "text": (
                                "Transcribe this voice message accurately. "
                                "Output only the transcript text, nothing else."
                            )
                        },
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
        }
        return await self._post(payload)
