"""Compress video/image payloads so they fit Discord upload limits.

Uses ffmpeg for re-encode when available (system PATH or imageio-ffmpeg
bundle). Falls back to original bytes when already small enough or when
ffmpeg cannot be found.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from functools import lru_cache
from typing import Optional

# Discord non-Nitro default is 25 MiB; leave headroom for multipart overhead.
DEFAULT_MAX_BYTES = 24 * 1024 * 1024


def discord_upload_limit(guild=None) -> int:
    """Resolve the effective Discord attachment limit for a guild/DM."""
    limit = None
    if guild is not None:
        limit = getattr(guild, "filesize_limit", None)
    try:
        limit = int(limit) if limit else DEFAULT_MAX_BYTES
    except (TypeError, ValueError):
        limit = DEFAULT_MAX_BYTES
    # Keep a small safety margin under the hard cap
    return max(1_000_000, min(limit - 256 * 1024, limit))


@lru_cache(maxsize=1)
def find_ffmpeg() -> str | None:
    """Locate an ffmpeg binary (PATH first, then imageio-ffmpeg bundle)."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return None


async def compress(
    data: bytes,
    ext: str = "mp4",
    max_mb: int = 8,
    *,
    max_bytes: int | None = None,
) -> bytes:
    """Compress media to fit under ``max_bytes`` (or ``max_mb`` MiB).

    Returns original data when already small enough or compression fails.
    """
    limit = max_bytes if max_bytes is not None else int(max_mb * 1024 * 1024)
    if not data or len(data) <= limit:
        return data

    ext = (ext or "mp4").lstrip(".").lower()
    if ext in {"jpg", "jpeg", "png", "webp", "gif"}:
        return await _compress_image(data, ext=ext, max_bytes=limit)

    return await _compress_video(data, ext=ext if ext in {"mp4", "webm", "mov"} else "mp4", max_bytes=limit)


async def _compress_video(data: bytes, *, ext: str, max_bytes: int) -> bytes:
    """Multi-pass ffmpeg compress targeting max_bytes."""
    # Estimate duration-agnostic CRF ladder; try progressively harder settings
    attempts: list[list[str]] = [
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"],
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "32", "-vf", "scale='min(1280,iw)':-2", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart"],
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "36", "-vf", "scale='min(854,iw)':-2", "-c:a", "aac", "-b:a", "48k", "-movflags", "+faststart"],
        ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "40", "-vf", "scale='min(640,iw)':-2", "-c:a", "aac", "-b:a", "32k", "-movflags", "+faststart"],
    ]

    best = data
    for extra in attempts:
        try:
            out = await _ffmpeg_file_io(data, input_ext="mp4", output_ext="mp4", extra_args=extra)
        except Exception:
            continue
        if not out:
            continue
        if len(out) < len(best):
            best = out
        if len(out) <= max_bytes:
            return out

    # Last resort: cap duration isn't an option; return best effort if smaller
    return best if len(best) < len(data) else data


async def _compress_image(data: bytes, *, ext: str, max_bytes: int) -> bytes:
    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(data))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        quality = 85
        best = data
        while quality >= 30:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            out = buf.getvalue()
            if len(out) < len(best):
                best = out
            if len(out) <= max_bytes:
                return out
            # shrink dimensions
            w, h = img.size
            img = img.resize((max(1, int(w * 0.85)), max(1, int(h * 0.85))), Image.LANCZOS)
            quality -= 10
        return best
    except Exception:
        return data


async def _ffmpeg_file_io(
    data: bytes,
    *,
    input_ext: str,
    output_ext: str,
    extra_args: list[str],
) -> bytes:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found (install ffmpeg or imageio-ffmpeg)")

    with tempfile.TemporaryDirectory(prefix="vain-compress-") as tmp:
        inp = os.path.join(tmp, f"in.{input_ext}")
        outp = os.path.join(tmp, f"out.{output_ext}")
        with open(inp, "wb") as fh:
            fh.write(data)

        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            inp,
            *extra_args,
            outp,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0 or not os.path.exists(outp):
            raise RuntimeError(err.decode("utf-8", "replace") or "ffmpeg failed")
        with open(outp, "rb") as fh:
            return fh.read()


async def fit_for_discord(
    data: bytes,
    *,
    filename: str = "media.mp4",
    guild=None,
    max_bytes: int | None = None,
) -> tuple[bytes, str]:
    """Ensure ``data`` fits Discord upload limits; compress if needed.

    Returns ``(bytes, filename)``.
    """
    limit = max_bytes if max_bytes is not None else discord_upload_limit(guild)
    if len(data) <= limit:
        return data, filename

    ext = (os.path.splitext(filename)[1] or ".mp4").lstrip(".").lower() or "mp4"
    compressed = await compress(data, ext=ext, max_bytes=limit)
    if len(compressed) <= limit:
        # normalize extension after video re-encode
        if ext not in {"jpg", "jpeg", "png", "webp", "gif"}:
            filename = f"{os.path.splitext(filename)[0]}.mp4"
        return compressed, filename

    # Still too big — return best compressed so caller can fail with size info
    if ext not in {"jpg", "jpeg", "png", "webp", "gif"}:
        filename = f"{os.path.splitext(filename)[0]}.mp4"
    return compressed, filename
