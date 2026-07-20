"""Reusable face-aware cropping for Discord announcement banners."""

from __future__ import annotations

import io
from typing import Final

import requests
from PIL import Image, ImageOps

AUTO_CROP_POSITION: Final = "auto"
DEFAULT_FALLBACK_CROP_POSITION: Final = "upper center"
FACE_DETECTOR_MODEL_URL: Final = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)

_VERTICAL_POSITIONS: Final = {
    "top": 0.00,
    "upper": 0.20,
    "upper center": 0.35,
    "center": 0.50,
    "lower center": 0.65,
    "lower": 0.80,
    "bottom": 1.00,
}

_FACE_MODEL_BUFFER: bytes | None = None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _get_face_model_buffer() -> bytes:
    global _FACE_MODEL_BUFFER

    if _FACE_MODEL_BUFFER is None:
        response = requests.get(
            FACE_DETECTOR_MODEL_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        response.raise_for_status()
        _FACE_MODEL_BUFFER = response.content

    return _FACE_MODEL_BUFFER


def _detect_face_focus_box(image: Image.Image):
    """Return a combined, padded face box in source-image pixels."""
    try:
        import mediapipe as mp
        import numpy as np
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        image_array = np.ascontiguousarray(np.asarray(image.convert("RGB")))
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_array)

        options = vision.FaceDetectorOptions(
            base_options=mp_python.BaseOptions(
                model_asset_buffer=_get_face_model_buffer(),
            ),
            running_mode=vision.RunningMode.IMAGE,
            min_detection_confidence=0.35,
        )

        with vision.FaceDetector.create_from_options(options) as detector:
            result = detector.detect(mp_image)
    except Exception:
        return None

    detections = getattr(result, "detections", None) or []
    if not detections:
        return None

    width, height = image.size
    boxes = []

    for detection in detections:
        box = detection.bounding_box
        x1 = _clamp(float(box.origin_x), 0, width)
        y1 = _clamp(float(box.origin_y), 0, height)
        x2 = _clamp(float(box.origin_x + box.width), 0, width)
        y2 = _clamp(float(box.origin_y + box.height), 0, height)

        if x2 > x1 and y2 > y1:
            boxes.append((x1, y1, x2, y2))

    if not boxes:
        return None

    x1 = min(box[0] for box in boxes)
    y1 = min(box[1] for box in boxes)
    x2 = max(box[2] for box in boxes)
    y2 = max(box[3] for box in boxes)

    face_width = x2 - x1
    face_height = y2 - y1

    return (
        _clamp(x1 - (face_width * 0.20), 0, width),
        _clamp(y1 - (face_height * 0.45), 0, height),
        _clamp(x2 + (face_width * 0.20), 0, width),
        _clamp(y2 + (face_height * 0.25), 0, height),
    )


def _crop_by_position(
    image: Image.Image,
    ratio: float,
    crop_position: str = DEFAULT_FALLBACK_CROP_POSITION,
) -> Image.Image:
    width, height = image.size

    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid image size: {width}x{height}")

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


def _crop_around_focus_box(
    image: Image.Image,
    ratio: float,
    focus_box,
) -> Image.Image:
    width, height = image.size
    current_ratio = width / height
    x1, y1, x2, y2 = focus_box

    if current_ratio > ratio:
        new_width = int(height * ratio)
        focus_x = (x1 + x2) / 2.0
        left = int(round(focus_x - (new_width / 2.0)))
        left = int(_clamp(left, 0, max(width - new_width, 0)))
        return image.crop((left, 0, left + new_width, height))

    if current_ratio < ratio:
        new_height = int(width / ratio)
        focus_y = y1 + ((y2 - y1) * 0.42)
        top = int(round(focus_y - (new_height * 0.38)))
        top = int(_clamp(top, 0, max(height - new_height, 0)))
        return image.crop((0, top, width, top + new_height))

    return image


def crop_announcement_image(
    image: Image.Image,
    ratio: float,
    crop_position: str = AUTO_CROP_POSITION,
    *,
    fallback_crop_position: str = DEFAULT_FALLBACK_CROP_POSITION,
) -> Image.Image:
    """Crop around detected faces, otherwise use the requested fixed position."""
    normalized = (crop_position or AUTO_CROP_POSITION).strip().lower()

    if normalized == AUTO_CROP_POSITION:
        focus_box = _detect_face_focus_box(image)
        if focus_box is not None:
            return _crop_around_focus_box(image, ratio, focus_box)
        normalized = fallback_crop_position

    return _crop_by_position(image, ratio, crop_position=normalized)


def build_announcement_banner(
    image_url: str,
    *,
    output_size: tuple[int, int] = (1600, 600),
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
        ratio = output_size[0] / output_size[1]
        image = crop_announcement_image(
            image,
            ratio,
            crop_position=crop_position,
        )
        image = image.resize(output_size, Image.Resampling.LANCZOS)

        output = io.BytesIO()
        image.save(output, "PNG", optimize=True)

    return filename, output.getvalue(), "image/png"
