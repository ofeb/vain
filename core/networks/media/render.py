"""render text and image overlays onto images.
uses pillow to draw text and composite layers.
use render_text for simple text overlays"""

import io
from typing import Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False


async def render_text(
    image_bytes: bytes,
    text: str,
    position: Tuple[int, int] = (10, 10),
    color: Tuple[int, int, int] = (255, 255, 255),
    font_size: int = 32,
) -> bytes:
    """draw text onto an image and return new bytes.
    requires pillow to be installed.
    returns original bytes if pillow not available"""
    if not PIL_OK:
        return image_bytes
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()
    draw.text(position, text, fill=(*color, 255), font=font)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
