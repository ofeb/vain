from __future__ import annotations

from io import BytesIO

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
except ImportError:
    Image = None  # type: ignore


def _require_pil() -> None:
    if Image is None:
        raise RuntimeError("Pillow is not installed")


def _load_image(data: bytes) -> Image.Image:
    _require_pil()
    image = Image.open(BytesIO(data))
    if getattr(image, "is_animated", False):
        image.seek(0)
    return image.convert("RGBA")


def _save_png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def pil_grayscale(data: bytes) -> bytes:
    return _save_png(ImageOps.grayscale(_load_image(data)).convert("RGBA"))


def pil_invert(data: bytes) -> bytes:
    rgb = _load_image(data)
    r, g, b, *rest = rgb.split()
    merged = Image.merge("RGB", (r, g, b))
    inverted = ImageOps.invert(merged)
    if rest:
        inverted.putalpha(rest[0])
    return _save_png(inverted.convert("RGBA"))


def pil_blur(data: bytes, radius: int = 5) -> bytes:
    return _save_png(_load_image(data).filter(ImageFilter.GaussianBlur(radius=max(1, radius))))


def pil_pixelate(data: bytes, size: int = 12) -> bytes:
    image = _load_image(data)
    width, height = image.size
    small = image.resize(
        (max(1, width // size), max(1, height // size)),
        resample=Image.Resampling.NEAREST,
    )
    return _save_png(small.resize((width, height), resample=Image.Resampling.NEAREST))


def pil_rotate(data: bytes, angle: int = 90) -> bytes:
    return _save_png(_load_image(data).rotate(angle, expand=True))


def pil_mirror(data: bytes) -> bytes:
    return _save_png(ImageOps.mirror(_load_image(data)))


def pil_flip(data: bytes) -> bytes:
    return _save_png(ImageOps.flip(_load_image(data)))


def pil_brightness(data: bytes, factor: float = 1.2) -> bytes:
    image = _load_image(data)
    enhanced = ImageEnhance.Brightness(image).enhance(factor)
    return _save_png(enhanced)


def pil_contrast(data: bytes, factor: float = 1.4) -> bytes:
    image = _load_image(data)
    enhanced = ImageEnhance.Contrast(image).enhance(factor)
    return _save_png(enhanced)


def pil_sharpen(data: bytes) -> bytes:
    return _save_png(_load_image(data).filter(ImageFilter.SHARPEN))


def pil_resize(data: bytes, width: int, height: int) -> bytes:
    image = _load_image(data)
    return _save_png(image.resize((max(16, width), max(16, height)), Image.Resampling.LANCZOS))

def _caption_font_path():
    from pathlib import Path
    return Path(__file__).resolve().parents[2] / "var" / "caption.otf"


def _build_caption_strip(text: str, width: int, size: int, text_width: int):
    from PIL import Image, ImageDraw, ImageFont

    text_value = (text or "").strip() or "..."
    font_path = _caption_font_path()
    try:
        font = ImageFont.truetype(str(font_path), size=size)
    except Exception:
        font = ImageFont.load_default()

    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
    wrapped_lines: list[str] = []
    for paragraph in text_value.splitlines() or ["..."]:
        words = paragraph.split()
        if not words:
            wrapped_lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            cb = measure.textbbox((0, 0), candidate, font=font)
            if (cb[2] - cb[0]) <= text_width:
                current = candidate
            else:
                wrapped_lines.append(current)
                current = word
        wrapped_lines.append(current)
    if not wrapped_lines:
        wrapped_lines = ["..."]

    line_boxes = [measure.textbbox((0, 0), ln if ln else " ", font=font) for ln in wrapped_lines]
    line_heights = [max(1, box[3] - box[1]) for box in line_boxes]
    line_gap = max(1, size // 8)
    text_h = sum(line_heights) + (line_gap * (len(wrapped_lines) - 1))
    caption_h = max(1, text_h + size)

    strip = Image.new("RGBA", (width, caption_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(strip)
    y = max(0, (caption_h - text_h) // 2)
    for idx, line in enumerate(wrapped_lines):
        bb = draw.textbbox((0, 0), line if line else " ", font=font)
        lw = max(1, bb[2] - bb[0])
        x = max(0, (width - lw) // 2)
        if line:
            draw.text((x, y), line, fill=(0, 0, 0, 255), font=font)
        y += line_heights[idx] + line_gap
    return strip


def _caption_frame(src: "Image.Image", strip: "Image.Image") -> "Image.Image":
    w, h = src.size
    caption_h = strip.height
    out = Image.new("RGBA", (w, h + caption_h), (255, 255, 255, 255))
    out.paste(strip, (0, 0), strip)
    frame = src.convert("RGBA")
    if frame.size != (w, h):
        frame = frame.resize((w, h), Image.Resampling.NEAREST)
    out.paste(frame, (0, caption_h), frame)
    return out


def pil_caption(data: bytes, text: str) -> bytes:
    """White-bar caption; original frame pixels stay the same size. Always GIF."""
    _require_pil()
    from PIL import Image

    src = Image.open(BytesIO(data))
    w, h = src.size
    size = max(1, w // 10)
    text_width = max(20, w - (((w // 25) * 2)))
    strip = _build_caption_strip(text, w, size, text_width)

    frames = []
    durations = []
    n = getattr(src, "n_frames", 1) or 1
    for i in range(n):
        try:
            src.seek(i)
        except Exception:
            break
        frame = src.convert("RGBA")
        frames.append(_caption_frame(frame, strip).convert("P", palette=Image.ADAPTIVE))
        durations.append(int(src.info.get("duration", 40) or 40))

    if not frames:
        frames = [_caption_frame(src.convert("RGBA"), strip).convert("P", palette=Image.ADAPTIVE)]
        durations = [40]

    buf = BytesIO()
    save_kw = {
        "format": "GIF",
        "save_all": True,
        "append_images": frames[1:],
        "duration": durations if len(durations) == len(frames) else 40,
        "loop": src.info.get("loop", 0),
        "disposal": 2,
    }
    frames[0].save(buf, **save_kw)
    return buf.getvalue()
