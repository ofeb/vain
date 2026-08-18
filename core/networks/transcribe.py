from __future__ import annotations

import io
from typing import Any

import aiohttp


class WhisperTranscribeClient:
    """Best-effort free-ish transcription.

    Tries Groq whisper if ``api.groq_api_key`` is set, otherwise a public
    OpenAI-compatible whisper endpoint when configured, else raises so the
    caller can fall back.
    """

    def __init__(self, bot=None) -> None:
        self.bot = bot

    def _groq_key(self) -> str | None:
        try:
            from config import api
            key = getattr(api, "groq_api_key", None) or getattr(api, "groq", None)
            if isinstance(key, str) and key.strip():
                return key.strip()
        except Exception:
            pass
        return None

    async def transcribe_audio(self, audio: bytes, *, mime_type: str = "audio/ogg") -> str:
        if not audio:
            raise RuntimeError("empty audio")
        key = self._groq_key()
        if not key:
            raise RuntimeError("no free transcribe key configured")

        
        form = aiohttp.FormData()
        ext = "ogg"
        if "mpeg" in (mime_type or "") or "mp3" in (mime_type or ""):
            ext = "mp3"
        elif "wav" in (mime_type or ""):
            ext = "wav"
        elif "webm" in (mime_type or ""):
            ext = "webm"
        form.add_field(
            "file",
            audio,
            filename=f"audio.{ext}",
            content_type=mime_type or "audio/ogg",
        )
        form.add_field("model", "whisper-large-v3")
        form.add_field("response_format", "text")

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                data=form,
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"whisper HTTP {resp.status}: {text[:200]}")
                return (text or "").strip()
