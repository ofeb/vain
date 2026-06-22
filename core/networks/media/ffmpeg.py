from __future__ import annotations

import asyncio
import os
import tempfile
from io import BytesIO


async def run_ffmpeg(
    data: bytes,
    *,
    input_ext: str = "png",
    output_ext: str = "gif",
    vf: str | None = None,
    filter_complex: str | None = None,
    extra_args: list[str] | None = None,
) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, f"input.{input_ext}")
        output_path = os.path.join(temp_dir, f"output.{output_ext}")
        with open(input_path, "wb") as handle:
            handle.write(data)

        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", input_path]
        if vf:
            cmd.extend(["-vf", vf])
        if filter_complex:
            cmd.extend(["-filter_complex", filter_complex])
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(output_path)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0 or not os.path.exists(output_path):
            raise RuntimeError(stderr.decode() or "ffmpeg failed")

        with open(output_path, "rb") as handle:
            return handle.read()


async def image_to_gif(data: bytes, vf: str) -> bytes:
    return await run_ffmpeg(
        data,
        vf=vf,
        output_ext="gif",
        extra_args=["-loop", "0"],
    )


async def gif_speed(data: bytes, factor: float) -> bytes:
    factor = max(0.1, min(factor, 10.0))
    pts = 1 / factor
    return await run_ffmpeg(
        data,
        input_ext="gif",
        output_ext="gif",
        vf=f"setpts={pts}*PTS",
        extra_args=["-loop", "0"],
    )
