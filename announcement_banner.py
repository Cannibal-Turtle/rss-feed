"""Reusable face- and content-aware cropping for Discord announcement banners."""

from __future__ import annotations

import io
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from typing import Final

import requests
from PIL import Image, ImageFilter, ImageOps

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


def _detect_human_face_focus_box(image: Image.Image):
    """Return a combined human-face box and an explanatory status string."""
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        # create_from_file avoids the NumPy-backed mp.Image constructor issue that
        # can leave a half-created object and emit an _image_ptr destructor warning.
        with TemporaryDirectory(prefix="announcement-face-") as temp_dir:
            image_path = Path(temp_dir) / "source.png"
            image.convert("RGB").save(image_path, "PNG")
            mp_image = mp.Image.create_from_file(str(image_path))

            options = vision.FaceDetectorOptions(
                base_options=mp_python.BaseOptions(
                    model_asset_buffer=_get_face_model_buffer(),
                ),
                running_mode=vision.RunningMode.IMAGE,
                min_detection_confidence=0.35,
            )

            with vision.FaceDetector.create_from_options(options) as detector:
                result = detector.detect(mp_image)
    except Exception as exc:
        return None, f"MediaPipe failed: {type(exc).__name__}: {exc}"

    detections = getattr(result, "detections", None) or []
    if not detections:
        return None, "no human face detected"

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
        return None, "MediaPipe returned no usable human-face box"

    x1 = min(box[0] for box in boxes)
    y1 = min(box[1] for box in boxes)
    x2 = max(box[2] for box in boxes)
    y2 = max(box[3] for box in boxes)

    face_width = x2 - x1
    face_height = y2 - y1

    return (
        (
            _clamp(x1 - (face_width * 0.20), 0, width),
            _clamp(y1 - (face_height * 0.45), 0, height),
            _clamp(x2 + (face_width * 0.20), 0, width),
            _clamp(y2 + (face_height * 0.25), 0, height),
        ),
        f"MediaPipe human face ({len(boxes)} detected)",
    )


def _border_background_color(image: Image.Image) -> tuple[float, float, float]:
    width, height = image.size
    border = max(2, min(width, height) // 40)
    pixels = image.load()
    samples = []

    for x in range(width):
        for offset in range(border):
            samples.append(pixels[x, offset])
            samples.append(pixels[x, height - 1 - offset])

    for y in range(height):
        for offset in range(border):
            samples.append(pixels[offset, y])
            samples.append(pixels[width - 1 - offset, y])

    return tuple(float(median(pixel[channel] for pixel in samples)) for channel in range(3))


def _detect_content_focus_box(image: Image.Image):
    """Find a likely illustrated subject in the upper half of a cover."""
    preview = image.convert("RGB").copy()
    preview.thumbnail((320, 480), Image.Resampling.LANCZOS)

    width, height = preview.size
    if width < 8 or height < 8:
        return None

    # Heavy smoothing suppresses thin title text while preserving large subjects.
    smooth = preview.filter(ImageFilter.GaussianBlur(radius=8))
    background = _border_background_color(smooth)
    gray = preview.convert("L")
    edge = gray.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(radius=2))

    smooth_pixels = smooth.load()
    edge_pixels = edge.load()
    row_scores = []

    for y in range(height):
        normalized_y = y / max(height - 1, 1)

        # Novel-cover faces and heads are normally in the upper half. Excluding
        # the lower title area prevents large lettering from winning the crop.
        if normalized_y < 0.08 or normalized_y > 0.55:
            row_scores.append(0.0)
            continue

        vertical_weight = 1.10 - (0.25 * normalized_y)
        row_score = 0.0

        for x in range(width):
            normalized_x = abs((x / max(width - 1, 1)) - 0.5) * 2.0
            center_weight = 0.25 + (0.75 * ((1.0 - normalized_x) ** 1.8))
            red, green, blue = smooth_pixels[x, y]
            background_distance = (
                abs(red - background[0])
                + abs(green - background[1])
                + abs(blue - background[2])
            ) / 3.0
            detail = (0.90 * background_distance) + (0.10 * edge_pixels[x, y])
            row_score += center_weight * detail

        row_scores.append(row_score * vertical_weight)

    band_height = max(8, int(height * 0.14))
    prefix_sums = [0.0]
    for score in row_scores:
        prefix_sums.append(prefix_sums[-1] + score)

    best_y = None
    best_score = 0.0

    for y in range(height):
        start = max(0, y - (band_height // 2))
        end = min(height, y + (band_height // 2) + 1)
        score = prefix_sums[end] - prefix_sums[start]
        if score > best_score:
            best_score = score
            best_y = y

    if best_y is None or best_score <= 0:
        return None

    source_y = (best_y / height) * image.height
    focus_height = max(image.height * 0.08, 1.0)

    return (
        0.0,
        _clamp(source_y - (focus_height / 2.0), 0, image.height),
        float(image.width),
        _clamp(source_y + (focus_height / 2.0), 0, image.height),
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
    """Crop around human faces, then illustrated content, then a fixed fallback."""
    normalized = (crop_position or AUTO_CROP_POSITION).strip().lower()

    if normalized == AUTO_CROP_POSITION:
        face_box, face_status = _detect_human_face_focus_box(image)
        if face_box is not None:
            print(f"[banner crop] Resolved auto crop: {face_status}.")
            return _crop_around_focus_box(image, ratio, face_box)

        content_box = _detect_content_focus_box(image)
        if content_box is not None:
            print(
                f"[banner crop] {face_status}; "
                "resolved auto crop: content-aware illustration fallback."
            )
            return _crop_around_focus_box(image, ratio, content_box)

        print(
            f"[banner crop] {face_status}; content-aware crop found nothing; "
            f"resolved auto crop: {fallback_crop_position} fallback."
        )
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
