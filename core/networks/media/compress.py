"""compress video and image files.
uses ffmpeg for video compression.
returns compressed bytes"""

import asyncio, io
from typing import Optional


async def compress(data: bytes, ext: str = "mp4", max_mb: int = 8) -> bytes:
    """compress video data to fit under max_mb.
    runs ffmpeg in subprocess to re-encode.
    returns original data if already small enough"""
    if len(data) <= max_mb * 1024 * 1024:
        return data
    bitrate = str(int((max_mb * 8192) / 60)) + "k"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", "pipe:0",
        "-b:v", bitrate, "-b:a", "128k",
        "-f", ext, "pipe:1",
        "-y", "-loglevel", "error",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(input=data)
    if proc.returncode != 0 or not out:
        return data
    return out
