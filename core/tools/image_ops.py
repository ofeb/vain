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


def _build_caption_strip(text: str, width: int, size: int, text_width: int, emoji_bytes: dict | None = None):
    _require_pil()
    from PIL import Image, ImageDraw, ImageFont

    text_value = (text or "...").strip() or "..."
    font = None
    from pathlib import Path as _P
    for path in (
        _caption_font_path(),
        _P("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        _P("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        _P("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ):
        try:
            font = ImageFont.truetype(str(path), size=size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    emoji_size = max(12, int(size * 0.88))
    wrapped_lines: list[str] = []
    for paragraph in text_value.splitlines() or ["..."]:
        if not paragraph.strip():
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(
            wrap_text_with_emojis(paragraph, font, text_width, emoji_bytes, emoji_size)
        )
    if not wrapped_lines:
        wrapped_lines = ["..."]

    line_heights = []
    for ln in wrapped_lines:
        if not ln:
            line_heights.append(max(1, size))
            continue
        bb_h = max(emoji_size, size)
        try:
            from PIL import ImageDraw as _ID, Image as _I
            # measure only the text parts for height
            plain = "".join(v if k == "text" else " " for k, v in tokenize_emojis(ln))
            sample = plain.strip() or "Hg"
            bb = _ID.Draw(_I.new("RGBA", (1, 1))).textbbox((0, 0), sample, font=font)
            bb_h = max(bb_h, bb[3] - bb[1], emoji_size)
        except Exception:
            pass
        line_heights.append(bb_h)
    line_gap = max(4, size // 10)
    text_h = sum(line_heights) + line_gap * max(0, len(wrapped_lines) - 1)
    pad_y = max(8, size // 4)
    caption_h = text_h + pad_y * 2

    strip = Image.new("RGBA", (width, caption_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(strip)
    y = max(0, (caption_h - text_h) // 2)
    for idx, line in enumerate(wrapped_lines):
        if line:
            lw = line_width_with_emojis(line, font, emoji_bytes, emoji_size)
            x = max(0, (width - lw) // 2)
            measure_draw_emoji_line(
                draw,
                (x, y),
                line,
                font,
                (0, 0, 0, 255),
                emoji_bytes,
                emoji_size,
                draw_it=True,
                canvas=strip,
                line_height=line_heights[idx],
            )
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


def pil_caption(data: bytes, text: str, emoji_bytes: dict | None = None) -> bytes:
    """White-bar caption on first frame as PNG (filename can still be .gif)."""
    _require_pil()
    from PIL import Image

    src = Image.open(BytesIO(data))
    try:
        src.seek(0)
    except Exception:
        pass
    frame = src.convert("RGBA")
    w, h = frame.size
    size = max(1, w // 10)
    text_width = max(20, w - (((w // 25) * 2)))
    strip = _build_caption_strip(text, w, size, text_width, emoji_bytes=emoji_bytes)
    out = _caption_frame(frame, strip)
    return _save_png(out)


def pil_to_gif(data: bytes) -> bytes:
    """Convert a static image to GIF without changing pixel dimensions."""
    _require_pil()
    from PIL import Image

    src = Image.open(BytesIO(data))
    frame = src.convert("RGBA")
    
    w, h = frame.size
    buf = BytesIO()
    
    pal = frame.convert("P", palette=Image.ADAPTIVE, colors=255)
    pal.save(buf, format="GIF")
    return buf.getvalue()


import re as _re

_CUSTOM_EMOJI_RE = _re.compile(r"<(a?):([A-Za-z0-9_~]+):(\d+)>")
# Broad unicode emoji coverage (Discord/Twemoji style)
_UNICODE_EMOJI_RE = _re.compile(
    r"(?:"
    r"[🇦-🇿]{2}"  # flags
    r"|[🌀-🫿]️?"
    r"|[😀-🙏]️?"
    r"|[🚀-🛿]️?"
    r"|[🤀-🧿]️?"
    r"|[☀-⛿]️?"
    r"|[✀-➿]️?"
    r"|[🀀-🀯]️?"
    r")"
    r"(?:‍"
    r"(?:[🌀-🫿]|[☀-➿]|[🀀-🧿])️?"
    r")*"
)


def tokenize_emojis(text: str) -> list[tuple[str, str]]:
    """Split text into (kind, value) tokens: text | unicode | custom."""
    raw = text or ""
    tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(raw):
        m = _CUSTOM_EMOJI_RE.match(raw, i)
        if m:
            tokens.append(("custom", m.group(0)))
            i = m.end()
            continue
        m = _UNICODE_EMOJI_RE.match(raw, i)
        if m:
            seq = m.group(0)
            # collapse pure joiners
            if seq.strip("\u200d\ufe0f"):
                tokens.append(("unicode", seq))
            i = m.end()
            continue
        # accumulate plain text until next emoji
        j = i + 1
        while j < len(raw):
            if _CUSTOM_EMOJI_RE.match(raw, j) or _UNICODE_EMOJI_RE.match(raw, j):
                break
            j += 1
        tokens.append(("text", raw[i:j]))
        i = j
    return tokens


def twemoji_codepoint(seq: str) -> str:
    parts = []
    for ch in seq:
        o = ord(ch)
        if o in (0xFE0F,):  # variation selector often omitted in twemoji filenames
            continue
        parts.append(f"{o:x}")
    return "-".join(parts)


def twemoji_url(seq: str) -> str:
    cp = twemoji_codepoint(seq)
    return f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{cp}.png"


def twemoji_urls(seq: str) -> list[str]:
    """Candidate Twemoji URLs (with/without FE0F variants)."""
    cps_full = []
    cps_nofe0f = []
    for ch in seq:
        o = ord(ch)
        cps_full.append(f"{o:x}")
        if o != 0xFE0F:
            cps_nofe0f.append(f"{o:x}")
    urls = []
    for cp in ( "-".join(cps_nofe0f), "-".join(cps_full) ):
        if not cp:
            continue
        urls.append(f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{cp}.png")
        urls.append(f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{cp}.png")
    # dedupe
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def custom_emoji_url(token: str) -> tuple[str, bool]:
    m = _CUSTOM_EMOJI_RE.match(token)
    if not m:
        return "", False
    animated = m.group(1) == "a"
    eid = m.group(3)
    ext = "gif" if animated else "png"
    return f"https://cdn.discordapp.com/emojis/{eid}.{ext}?size=96&quality=lossless", animated


def _emoji_placeholder(token: str) -> str:
    m = _CUSTOM_EMOJI_RE.match(token)
    if m:
        return f":{m.group(2)}:"
    return "\ufffd"


async def fetch_emoji_images(text: str, session=None) -> dict[str, bytes]:
    """Download Twemoji + Discord custom emoji assets used in text."""
    import aiohttp

    needed: dict[str, list[str]] = {}
    for kind, val in tokenize_emojis(text):
        if kind == "unicode":
            needed[val] = twemoji_urls(val)
        elif kind == "custom":
            url, _ = custom_emoji_url(val)
            if url:
                needed[val] = [url]
    if not needed:
        return {}

    own = session is None
    if own:
        timeout = aiohttp.ClientTimeout(total=20)
        session = aiohttp.ClientSession(
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 vain-bot"},
        )
    out: dict[str, bytes] = {}
    try:
        for key, urls in needed.items():
            for url in urls:
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            if data and (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] in (b"GIF", b"\xff\xd8")):
                                out[key] = data
                                break
                except Exception:
                    continue
    finally:
        if own:
            await session.close()
    return out


def _load_emoji_im(data: bytes, size: int):
    from PIL import Image
    im = Image.open(BytesIO(data))
    try:
        im.seek(0)
    except Exception:
        pass
    im = im.convert("RGBA")
    return im.resize((size, size), Image.Resampling.LANCZOS)


def measure_draw_emoji_line(
    draw,
    xy: tuple[int, int],
    line: str,
    font,
    fill,
    emoji_bytes: dict[str, bytes] | None,
    emoji_size: int,
    *,
    draw_it: bool = True,
    canvas=None,
    line_height: int | None = None,
) -> int:
    """Draw/measure a line that may contain unicode/custom emojis. Returns width.

    Text and emoji glyphs are vertically centered inside ``line_height`` so a
    caption like ``hello ☠️`` sits on one shared middle line.
    """
    x, y = xy
    start_x = x
    emoji_bytes = emoji_bytes or {}
    fsize = getattr(font, "size", None) or emoji_size
    line_h = int(line_height or max(fsize, emoji_size))

    for kind, val in tokenize_emojis(line):
        if kind == "text":
            if not val:
                continue
            bb = draw.textbbox((0, 0), val, font=font)
            tw = max(1, bb[2] - bb[0])
            th = max(1, bb[3] - bb[1])
            if draw_it:
                # center glyph box in the line, compensate bbox top offset
                ty = y + (line_h - th) // 2 - bb[1]
                draw.text((x, ty), val, fill=fill, font=font)
            x += tw
        else:
            data = emoji_bytes.get(val)
            size = int(emoji_size)
            if data:
                try:
                    em = _load_emoji_im(data, size)
                    if draw_it and canvas is not None:
                        ey = y + (line_h - size) // 2
                        canvas.paste(em, (int(x), int(ey)), em)
                        x += size + max(2, size // 12)
                        continue
                    if not draw_it:
                        x += size + max(2, size // 12)
                        continue
                except Exception:
                    pass
            ph = _emoji_placeholder(val) if kind == "custom" else "?"
            bb = draw.textbbox((0, 0), ph, font=font)
            tw = max(1, bb[2] - bb[0])
            th = max(1, bb[3] - bb[1])
            if draw_it:
                ty = y + (line_h - th) // 2 - bb[1]
                draw.text((x, ty), ph, fill=fill, font=font)
            x += tw
    return max(1, x - start_x)


def line_width_with_emojis(text: str, font, emoji_bytes: dict[str, bytes] | None, emoji_size: int) -> int:
    from PIL import Image, ImageDraw
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    return measure_draw_emoji_line(measure, (0, 0), text, font, (0, 0, 0, 255), emoji_bytes, emoji_size, draw_it=False)


def wrap_text_with_emojis(
    text: str,
    font,
    max_width: int,
    emoji_bytes: dict[str, bytes] | None,
    emoji_size: int,
) -> list[str]:
    # wrap on spaces but keep emoji tokens intact
    tokens: list[str] = []
    for kind, val in tokenize_emojis(text.replace("\n", " \n ")):
        if kind == "text":
            for part in val.split(" "):
                if part == "\n":
                    tokens.append("\n")
                elif part:
                    tokens.append(part)
                tokens.append(" ")
            if tokens and tokens[-1] == " ":
                tokens.pop()
        else:
            tokens.append(val)
    lines: list[str] = []
    current = ""
    for tok in tokens:
        if tok == "\n":
            lines.append(current)
            current = ""
            continue
        candidate = f"{current}{tok}" if current else tok
        if current and line_width_with_emojis(candidate, font, emoji_bytes, emoji_size) > max_width:
            lines.append(current.rstrip())
            current = tok.lstrip() if isinstance(tok, str) else tok
        else:
            current = candidate
    if current or not lines:
        lines.append(current.rstrip() if current else "")
    return lines or [""]

