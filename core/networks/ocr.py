from __future__ import annotations

import io
from typing import Any

import aiohttp

from config import api as api_cfg


def _content_type(filename: str) -> str:
    name = (filename or "image.png").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith(".bmp"):
        return "image/bmp"
    if name.endswith(".tif") or name.endswith(".tiff"):
        return "image/tiff"
    return "image/png"


def _prepare_image(data: bytes, filename: str) -> tuple[bytes, str, str]:
    """Downscale / re-encode large images so OCR.space free tier accepts them."""
    name = filename or "image.png"
    ctype = _content_type(name)
    if not data:
        return data, name, ctype
    if len(data) <= 900_000:
        return data, name if not name.lower().endswith(".gif") else "image.png", ctype

    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        im = im.convert("RGB")
        w, h = im.size
        # shrink until under ~850KB
        for scale in (1.0, 0.75, 0.5, 0.35, 0.25):
            if scale < 1.0:
                nw, nh = max(32, int(w * scale)), max(32, int(h * scale))
                frame = im.resize((nw, nh), Image.Resampling.LANCZOS)
            else:
                frame = im
            buf = io.BytesIO()
            frame.save(buf, format="JPEG", quality=85, optimize=True)
            out = buf.getvalue()
            if len(out) <= 900_000:
                return out, "image.jpg", "image/jpeg"
        buf = io.BytesIO()
        im.resize((max(32, w // 4), max(32, h // 4)), Image.Resampling.LANCZOS).save(
            buf, format="JPEG", quality=70, optimize=True
        )
        return buf.getvalue(), "image.jpg", "image/jpeg"
    except Exception:
        return data[:900_000], name, ctype


def _error_text(payload: dict[str, Any], status: int | None = None) -> str:
    msgs = payload.get("ErrorMessage") or payload.get("ErrorDetails")
    if isinstance(msgs, list):
        msgs = "; ".join(str(m) for m in msgs if m)
    if msgs and str(msgs).strip():
        return str(msgs).strip()
    code = payload.get("OCRExitCode")
    mapping = {
        3: "OCR failed to process this image",
        4: "Unable to process image (unsupported, corrupt, or too large)",
    }
    if code in mapping:
        return mapping[code]
    if status and status != 200:
        return f"OCR service returned HTTP {status}"
    return "OCR failed with an empty error from the provider"


async def ocr_image(data: bytes, *, filename: str = "image.png") -> str:
    """OCR.space free endpoint (Engine 2)."""
    key = (getattr(api_cfg, "ocr_space_api_key", "") or "").strip()
    if not key:
        raise RuntimeError("OCR.space API key is not configured")
    if not data:
        raise RuntimeError("No image data to OCR")

    data, filename, ctype = _prepare_image(data, filename)

    form = aiohttp.FormData()
    form.add_field("apikey", key)
    form.add_field("language", "eng")
    form.add_field("isOverlayRequired", "false")
    form.add_field("OCREngine", "2")
    form.add_field("scale", "true")
    form.add_field("detectOrientation", "true")
    form.add_field(
        "file",
        data,
        filename=filename,
        content_type=ctype,
    )

    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post("https://api.ocr.space/parse/image", data=form) as resp:
            status = resp.status
            try:
                payload = await resp.json(content_type=None)
            except Exception:
                body = await resp.text()
                raise RuntimeError(
                    f"OCR returned non-JSON (HTTP {status}): {body[:180]}"
                ) from None

    if not isinstance(payload, dict):
        raise RuntimeError("OCR failed: invalid response")

    errored = bool(payload.get("IsErroredOnProcessing"))
    exit_code = payload.get("OCRExitCode")
    if errored or (isinstance(exit_code, int) and exit_code not in (1, 2)):
        raise RuntimeError(_error_text(payload, status))

    results = payload.get("ParsedResults") or []
    texts: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        # per-result errors
        if item.get("ErrorMessage"):
            continue
        t = (item.get("ParsedText") or "").strip()
        if t:
            texts.append(t)
    return "\n".join(texts).strip()
