from __future__ import annotations

import aiohttp

from config import api as api_cfg


async def ocr_image(data: bytes, *, filename: str = "image.png") -> str:
    """OCR.space free endpoint."""
    key = (getattr(api_cfg, "ocr_space_api_key", "") or "").strip()
    if not key:
        raise RuntimeError("OCR.space API key is not configured")
    form = aiohttp.FormData()
    form.add_field("apikey", key)
    form.add_field("language", "eng")
    form.add_field("isOverlayRequired", "false")
    form.add_field("OCREngine", "2")
    form.add_field("file", data, filename=filename, content_type="application/octet-stream")
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post("https://api.ocr.space/parse/image", data=form) as resp:
            payload = await resp.json(content_type=None)
    if not isinstance(payload, dict):
        raise RuntimeError("OCR failed")
    if payload.get("IsErroredOnProcessing"):
        msgs = payload.get("ErrorMessage") or payload.get("ErrorDetails") or "OCR failed"
        if isinstance(msgs, list):
            msgs = "; ".join(str(m) for m in msgs)
        raise RuntimeError(str(msgs))
    results = payload.get("ParsedResults") or []
    texts = []
    for item in results:
        t = (item or {}).get("ParsedText") or ""
        if t.strip():
            texts.append(t.strip())
    return "\n".join(texts).strip()
