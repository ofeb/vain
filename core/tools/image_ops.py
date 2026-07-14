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