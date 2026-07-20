"""Reusable lightweight text-aware cropping for Discord announcement banners."""

from __future__ import annotations

import io
from typing import Final

import requests
from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat

AUTO_CROP_POSITION: Final = "auto"
DEFAULT_FALLBACK_CROP_POSITION: Final = "upper center"

_VERTICAL_POSITIONS: Final = {
    "top": 0.00,
    "upper": 0.20,
    "upper center": 0.35,
    "center": 0.50,
    "lower center": 0.65,
    "lower": 0.80,
    "bottom": 1.00,
}

# The heuristic is intentionally conservative. It does not perform OCR; it only
# compares coarse, high-contrast horizontal activity in the upper and lower
# parts of a cover. When the result is unclear, auto stays predictable and uses
# upper center.
_ANALYSIS_WIDTH: Final = 400
_TEXT_SCORE_MINIMUM: Final = 16.0
_TEXT_SCORE_RATIO: Final = 1.22
_TEXT_SCORE_DIFFERENCE: Final = 4.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _analysis_image(image: Image.Image) -> Image.Image:
    """Return a small grayscale copy suitable for inexpensive analysis."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size

    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid image size: {width}x{height}")

    if width > _ANALYSIS_WIDTH:
        new_height = max(1, int(round(height * (_ANALYSIS_WIDTH / width))))
        image = image.resize((_ANALYSIS_WIDTH, new_height), Image.Resampling.LANCZOS)

    return ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=1)


def _peak_band_score(
    image: Image.Image,
    *,
    start_fraction: float,
    end_fraction: float,
) -> float:
    """Return the strongest coarse-detail score in a vertical region."""
    width, height = image.size
    if width <= 0 or height <= 0:
        return 0.0

    left = int(round(width * 0.05))
    right = max(left + 1, int(round(width * 0.95)))
    start = int(round(height * start_fraction))
    end = int(round(height * end_fraction))
    window = max(6, int(round(height * 0.08)))
    step = max(2, window // 4)

    if end - start < window:
        return 0.0

    best = 0.0
    for top in range(start, end - window + 1, step):
        band = image.crop((left, top, right, top + window))
        score = float(ImageStat.Stat(band).mean[0])
        best = max(best, score)

    return best


def _text_aware_auto_position(
    image: Image.Image,
    *,
    fallback: str = DEFAULT_FALLBACK_CROP_POSITION,
) -> tuple[str, str]:
    """Choose the opposite side of a likely title band, or use fallback."""
    try:
        gray = _analysis_image(image)
        blur_radius = max(3.0, gray.width / 80.0)
        coarse_detail = ImageChops.difference(
            gray,
            gray.filter(ImageFilter.GaussianBlur(radius=blur_radius)),
        )

        top_score = _peak_band_score(
            coarse_detail,
            start_fraction=0.05,
            end_fraction=0.48,
        )
        bottom_score = _peak_band_score(
            coarse_detail,
            start_fraction=0.52,
            end_fraction=0.95,
        )
    except Exception as exc:
        return fallback, f"text-band analysis failed ({type(exc).__name__})"

    strongest = max(top_score, bottom_score)
    difference = abs(top_score - bottom_score)

    if (
        strongest >= _TEXT_SCORE_MINIMUM
        and difference >= _TEXT_SCORE_DIFFERENCE
        and top_score >= bottom_score * _TEXT_SCORE_RATIO
    ):
        return (
            "lower center",
            f"text-like activity is stronger near the top "
            f"(top={top_score:.1f}, bottom={bottom_score:.1f})",
        )

    if (
        strongest >= _TEXT_SCORE_MINIMUM
        and difference >= _TEXT_SCORE_DIFFERENCE
        and bottom_score >= top_score * _TEXT_SCORE_RATIO
    ):
        return (
            "upper center",
            f"text-like activity is stronger near the bottom "
            f"(top={top_score:.1f}, bottom={bottom_score:.1f})",
        )

    return (
        fallback,
        f"no clear top/bottom text band "
        f"(top={top_score:.1f}, bottom={bottom_score:.1f})",
    )


def _crop_by_position(
    image: Image.Image,
    ratio: float,
    crop_position: str = DEFAULT_FALLBACK_CROP_POSITION,
) -> Image.Image:
    width, height = image.size

    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid image size: {width}x{height}")
    if ratio <= 0:
        raise RuntimeError(f"Invalid target ratio: {ratio}")

    current_ratio = width / height

    if current_ratio > ratio:
        new_width = int(height * ratio)
        left = max((width - new_width) // 2, 0)
        return image.crop((left, 0, left + new_width, height))

    if current_ratio < ratio:
        new_height = int(width / ratio)
        excess = max(height - new_height, 0)
        factor = _VERTICAL_POSITIONS.get(
            (crop_position or DEFAULT_FALLBACK_CROP_POSITION).strip().lower(),
            _VERTICAL_POSITIONS[DEFAULT_FALLBACK_CROP_POSITION],
        )
        top = int(round(excess * factor))
        top = max(0, min(top, excess))
        return image.crop((0, top, width, top + new_height))

    return image


def crop_announcement_image(
    image: Image.Image,
    ratio: float,
    crop_position: str = AUTO_CROP_POSITION,
    *,
    fallback_crop_position: str = DEFAULT_FALLBACK_CROP_POSITION,
) -> Image.Image:
    """Crop by a manual position or a lightweight text-aware auto position."""
    normalized = (crop_position or AUTO_CROP_POSITION).strip().lower()

    if normalized == AUTO_CROP_POSITION:
        normalized, status = _text_aware_auto_position(
            image,
            fallback=fallback_crop_position,
        )
        print(
            f"[banner crop] Auto crop: {status}; "
            f"using {normalized}."
        )

    return _crop_by_position(image, ratio, crop_position=normalized)


def build_announcement_banner(
    image_url: str,
    *,
    output_size: tuple[int, int] | None = (1600, 600),
    crop_position: str = AUTO_CROP_POSITION,
    filename: str = "announcement_banner.png",
) -> tuple[str, bytes, str]:
    """Download an image and return a Discord-ready PNG attachment tuple."""
    image_url = (image_url or "").strip()
    if not image_url:
        raise RuntimeError("No featured image URL was provided.")

    response = requests.get(
        image_url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()

    with Image.open(io.BytesIO(response.content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")

        if output_size is not None:
            output_width, output_height = output_size
            if output_width <= 0 or output_height <= 0:
                raise RuntimeError(f"Invalid output size: {output_size}")

            ratio = output_width / output_height
            image = crop_announcement_image(
                image,
                ratio,
                crop_position=crop_position,
            )
            image = image.resize(output_size, Image.Resampling.LANCZOS)

        output = io.BytesIO()
        image.save(output, "PNG", optimize=True)

    return filename, output.getvalue(), "image/png"
