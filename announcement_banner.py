"""Reusable subject-aware cropping for Discord announcement banners."""

from __future__ import annotations

import io
import math
import os
import re
from pathlib import Path
from threading import Lock
from typing import Final

import requests
from PIL import Image, ImageOps

AUTO_CROP_POSITION: Final = "auto"
DEFAULT_FALLBACK_CROP_POSITION: Final = "upper center"
YOLOE_MODEL_FILENAME: Final = "yoloe-11s-seg-pf.pt"
YOLOE_MODEL_URL: Final = (
    "https://github.com/ultralytics/assets/releases/download/v8.4.0/"
    f"{YOLOE_MODEL_FILENAME}"
)
YOLOE_CACHE_DIR: Final = Path(
    os.environ.get(
        "ANNOUNCEMENT_BANNER_MODEL_CACHE",
        str(Path.home() / ".cache" / "cannibal-turtle" / "announcement-banner"),
    )
).expanduser()
YOLOE_CONFIDENCE: Final = float(
    os.environ.get("ANNOUNCEMENT_BANNER_YOLO_CONFIDENCE", "0.08")
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

_FACE_TERMS: Final = {
    "face",
    "head",
    "portrait",
}

_HUMAN_TERMS: Final = {
    "person",
    "human",
    "man",
    "woman",
    "boy",
    "girl",
    "child",
    "baby",
    "teenager",
    "youth",
    "gentleman",
    "lady",
    "prince",
    "princess",
    "king",
    "queen",
    "warrior",
    "soldier",
    "actor",
    "actress",
    "character",
    "anime",
    "cartoon",
    "chibi",
    "doll",
    "figurine",
    "mascot",
}

_ANIMAL_TERMS: Final = {
    "animal",
    "pet",
    "dog",
    "puppy",
    "canine",
    "wolf",
    "fox",
    "cat",
    "kitten",
    "feline",
    "rabbit",
    "bunny",
    "bird",
    "owl",
    "raven",
    "crow",
    "horse",
    "deer",
    "bear",
    "lion",
    "tiger",
    "leopard",
    "panther",
    "dragon",
    "monster",
    "creature",
    "sheep",
    "goat",
    "cow",
    "pig",
    "mouse",
    "rat",
    "squirrel",
    "raccoon",
    "monkey",
    "ape",
}

_EXCLUDED_LABEL_TERMS: Final = {
    "book jacket",
    "book cover",
    "poster",
    "billboard",
    "signboard",
    "sign",
    "text",
    "logo",
    "font",
    "website",
    "web site",
    "comic book",
    "magazine",
    "newspaper",
    "screen",
    "monitor",
    "television",
}

_YOLO_MODEL = None
_YOLO_MODEL_LOCK = Lock()


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _normalize_label(label: object) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(label or "").lower())
    return " ".join(text.split())


def _label_contains(label: str, terms: set[str]) -> bool:
    words = set(label.split())
    return any(term in label if " " in term else term in words for term in terms)


def _subject_kind(label: str) -> str | None:
    if any(term in label for term in _EXCLUDED_LABEL_TERMS):
        return None
    if _label_contains(label, _FACE_TERMS):
        return "face"
    if _label_contains(label, _HUMAN_TERMS):
        return "human"
    if _label_contains(label, _ANIMAL_TERMS):
        return "animal"
    return None


def _download_yolo_model() -> Path:
    YOLOE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    model_path = YOLOE_CACHE_DIR / YOLOE_MODEL_FILENAME

    if model_path.is_file() and model_path.stat().st_size > 1_000_000:
        return model_path

    temporary_path = model_path.with_suffix(model_path.suffix + ".part")
    temporary_path.unlink(missing_ok=True)

    print(f"[banner crop] Downloading YOLOE model to {model_path} ...")
    response = requests.get(
        YOLOE_MODEL_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        stream=True,
        timeout=(15, 180),
    )
    response.raise_for_status()

    with temporary_path.open("wb") as output:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                output.write(chunk)

    if temporary_path.stat().st_size <= 1_000_000:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded YOLOE model was unexpectedly small.")

    os.replace(temporary_path, model_path)
    return model_path


def _get_yolo_model():
    global _YOLO_MODEL

    if _YOLO_MODEL is not None:
        return _YOLO_MODEL

    with _YOLO_MODEL_LOCK:
        if _YOLO_MODEL is not None:
            return _YOLO_MODEL

        from ultralytics import YOLO

        _YOLO_MODEL = YOLO(str(_download_yolo_model()))
        return _YOLO_MODEL


def _result_name(names, class_index: int) -> str:
    if isinstance(names, dict):
        return str(names.get(class_index, class_index))
    try:
        return str(names[class_index])
    except Exception:
        return str(class_index)


def _candidate_score(
    *,
    confidence: float,
    area_fraction: float,
    center_x: float,
    image_width: float,
    kind: str,
) -> float:
    center_distance = abs(center_x - (image_width / 2.0)) / max(image_width / 2.0, 1.0)
    center_weight = 1.0 - (0.20 * _clamp(center_distance, 0.0, 1.0))
    size_weight = 0.70 + min(math.sqrt(max(area_fraction, 0.0)) * 1.15, 0.85)
    kind_weight = {"face": 1.35, "human": 1.15, "animal": 1.05}.get(kind, 1.0)
    return confidence * center_weight * size_weight * kind_weight


def _detect_yolo_subject_focus_box(image: Image.Image):
    """Return a combined subject box, focus kind, and explanatory status."""
    try:
        model = _get_yolo_model()
        result = model.predict(
            source=image.convert("RGB"),
            imgsz=640,
            conf=YOLOE_CONFIDENCE,
            iou=0.45,
            max_det=30,
            agnostic_nms=True,
            device="cpu",
            verbose=False,
        )[0]
    except Exception as exc:
        return None, None, f"YOLOE failed: {type(exc).__name__}: {exc}"

    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return None, None, "YOLOE detected no objects"

    width, height = image.size
    image_area = max(float(width * height), 1.0)
    candidates = []

    for box in boxes:
        try:
            class_index = int(box.cls.item())
            confidence = float(box.conf.item())
            x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
        except Exception:
            continue

        x1 = _clamp(x1, 0, width)
        y1 = _clamp(y1, 0, height)
        x2 = _clamp(x2, 0, width)
        y2 = _clamp(y2, 0, height)

        if x2 <= x1 or y2 <= y1:
            continue

        label = _normalize_label(_result_name(result.names, class_index))
        kind = _subject_kind(label)
        if kind is None:
            continue

        area = (x2 - x1) * (y2 - y1)
        area_fraction = area / image_area

        # Whole-page boxes are generally the cover/poster itself rather than a subject.
        if area_fraction > 0.94 and kind != "face":
            continue

        score = _candidate_score(
            confidence=confidence,
            area_fraction=area_fraction,
            center_x=(x1 + x2) / 2.0,
            image_width=width,
            kind=kind,
        )
        candidates.append(
            {
                "box": (x1, y1, x2, y2),
                "confidence": confidence,
                "area_fraction": area_fraction,
                "kind": kind,
                "label": label,
                "score": score,
            }
        )

    if not candidates:
        return None, None, "YOLOE found no usable person, character, or animal subject"

    face_candidates = [candidate for candidate in candidates if candidate["kind"] == "face"]
    pool = face_candidates or candidates
    pool.sort(key=lambda candidate: candidate["score"], reverse=True)

    top_score = pool[0]["score"]
    selected = []

    for candidate in pool:
        if len(selected) >= 5:
            break
        if candidate["score"] < top_score * 0.42:
            continue
        if candidate["area_fraction"] < 0.0025:
            continue
        selected.append(candidate)

    if not selected:
        selected = [pool[0]]

    x1 = min(candidate["box"][0] for candidate in selected)
    y1 = min(candidate["box"][1] for candidate in selected)
    x2 = max(candidate["box"][2] for candidate in selected)
    y2 = max(candidate["box"][3] for candidate in selected)

    box_width = x2 - x1
    box_height = y2 - y1
    pad_x = box_width * 0.10
    pad_top = box_height * 0.10
    pad_bottom = box_height * 0.05

    labels = []
    for candidate in selected:
        label = candidate["label"] or candidate["kind"]
        if label not in labels:
            labels.append(label)

    focus_kind = "face" if face_candidates else (
        "human" if any(candidate["kind"] == "human" for candidate in selected) else "animal"
    )
    status = (
        f"YOLOE subject detection ({len(selected)} selected: "
        f"{', '.join(labels[:4])})"
    )

    return (
        (
            _clamp(x1 - pad_x, 0, width),
            _clamp(y1 - pad_top, 0, height),
            _clamp(x2 + pad_x, 0, width),
            _clamp(y2 + pad_bottom, 0, height),
        ),
        focus_kind,
        status,
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
    *,
    focus_kind: str,
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
        box_height = max(y2 - y1, 1.0)

        if focus_kind == "face":
            focus_y = (y1 + y2) / 2.0
            target_fraction = 0.48
        elif box_height < height * 0.30:
            # Small chibis or grouped characters: use the detected group centre.
            focus_y = (y1 + y2) / 2.0
            target_fraction = 0.50
        elif focus_kind == "animal":
            focus_y = y1 + (box_height * 0.30)
            target_fraction = 0.45
        else:
            # For full-body human/character boxes, aim at the head and upper torso.
            focus_y = y1 + (box_height * 0.22)
            target_fraction = 0.45

        top = int(round(focus_y - (new_height * target_fraction)))
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
    """Crop around a YOLOE-detected subject, then use a fixed fallback."""
    normalized = (crop_position or AUTO_CROP_POSITION).strip().lower()

    if normalized == AUTO_CROP_POSITION:
        focus_box, focus_kind, status = _detect_yolo_subject_focus_box(image)
        if focus_box is not None and focus_kind is not None:
            print(f"[banner crop] Resolved auto crop: {status}.")
            return _crop_around_focus_box(
                image,
                ratio,
                focus_box,
                focus_kind=focus_kind,
            )

        print(
            f"[banner crop] {status}; "
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
