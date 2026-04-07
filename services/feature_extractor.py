"""
feature_extractor.py
--------------------
Category-aware metadata extraction pipeline for Travel Pinterest.

Each of the 6 dataset categories has its own specialised extraction strategy,
layered on top of global quality / colour / mood features shared by all images.

All results are pure Python dicts — no DB, no side-effects.
Heavy imports (sklearn) are optional; the pipeline degrades gracefully.
"""

import os
import json
import hashlib
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# HSV colour-range helpers
# ──────────────────────────────────────────────────────────────────────────────

def _hsv_ratio(hsv_img: np.ndarray, lower: list, upper: list) -> float:
    mask = cv2.inRange(hsv_img, np.array(lower, np.uint8), np.array(upper, np.uint8))
    total = hsv_img.shape[0] * hsv_img.shape[1]
    return float(cv2.countNonZero(mask)) / total if total > 0 else 0.0


def _load_bgr(path: str):
    img = cv2.imread(path)
    if img is None:
        raise ValueError(f"Cannot read image: {path}")
    # Cap resolution for speed (max 640 wide)
    h, w = img.shape[:2]
    if w > 640:
        scale = 640 / w
        img = cv2.resize(img, (640, int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


# ──────────────────────────────────────────────────────────────────────────────
# K-Means dominant colours  (graceful fallback without sklearn)
# ──────────────────────────────────────────────────────────────────────────────

def _dominant_colours(img: np.ndarray, k: int = 3) -> list[str]:
    """Returns top-k hex colour strings."""
    try:
        from sklearn.cluster import KMeans
        pixels = img.reshape(-1, 3).astype(np.float32)
        # Sample for speed
        if len(pixels) > 3000:
            idx = np.random.choice(len(pixels), 3000, replace=False)
            pixels = pixels[idx]
        km = KMeans(n_clusters=k, n_init=3, random_state=42)
        km.fit(pixels)
        centres = km.cluster_centers_.astype(int)
        # centres are in BGR — convert to RGB hex
        return [f"#{int(c[2]):02x}{int(c[1]):02x}{int(c[0]):02x}" for c in centres]
    except Exception:
        # Simple quantile fallback
        flat = img.reshape(-1, 3)
        median = np.median(flat, axis=0).astype(int)
        return [f"#{int(median[2]):02x}{int(median[1]):02x}{int(median[0]):02x}"]


# ──────────────────────────────────────────────────────────────────────────────
# Global quality / mood features (all categories)
# ──────────────────────────────────────────────────────────────────────────────

def _global_features(img: np.ndarray) -> dict:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    brightness = float(np.mean(hsv[:, :, 2])) / 255.0          # 0-1
    saturation = float(np.mean(hsv[:, :, 1])) / 255.0          # 0-1
    sharpness  = float(cv2.Laplacian(gray, cv2.CV_64F).var())   # higher = sharper

    # Normalise sharpness to 0-1 via sigmoid-like cap at 2000
    sharpness_norm = min(sharpness / 2000.0, 1.0)

    quality_score = int(
        brightness   * 0.30 * 100 +
        sharpness_norm * 0.40 * 100 +
        saturation   * 0.30 * 100
    )
    quality_score = max(0, min(100, quality_score))

    # Mood heuristic
    if brightness > 0.65 and saturation > 0.45:
        mood = "vibrant"
    elif brightness < 0.35:
        mood = "dramatic"
    elif saturation < 0.20:
        mood = "misty"
    else:
        mood = "calm"

    h, w = img.shape[:2]
    dominant = _dominant_colours(img)

    return {
        "quality_score": quality_score,
        "brightness": round(brightness, 3),
        "saturation": round(saturation, 3),
        "sharpness": round(sharpness_norm, 3),
        "mood": mood,
        "aspect_ratio": round(w / h, 3),
        "dominant_colors": dominant,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Category-specific extractors
# ──────────────────────────────────────────────────────────────────────────────

def _extract_beach(img: np.ndarray, hsv: np.ndarray) -> dict:
    # Water: cyan-blue spectrum
    water_ratio = _hsv_ratio(hsv, [85, 40, 80], [130, 255, 255])
    # Sand: warm beige
    sand_ratio  = _hsv_ratio(hsv, [10, 20, 140], [30, 120, 255])
    # Sky: light blue with high value
    sky_ratio   = _hsv_ratio(hsv, [90, 30, 180], [130, 120, 255])

    # Horizon line detection via Hough
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    h = img.shape[0]
    # Look for long horizontal lines in middle 1/3
    roi = edges[h//3: 2*h//3, :]
    lines = cv2.HoughLinesP(roi, 1, np.pi/180, threshold=60, minLineLength=80, maxLineGap=20)
    has_horizon = lines is not None and len(lines) > 0

    # Water colour temperature: turquoise vs dark blue vs grey
    turq  = _hsv_ratio(hsv, [85, 80, 120], [105, 255, 255])
    deep  = _hsv_ratio(hsv, [105, 60, 60], [130, 255, 200])
    water_tone = "turquoise" if turq > deep else ("deep_blue" if deep > 0.05 else "grey")

    return {
        "subcategory": "beach",
        "water_ratio": round(water_ratio, 3),
        "sand_ratio": round(sand_ratio, 3),
        "sky_ratio": round(sky_ratio, 3),
        "water_tone": water_tone,
        "has_horizon": has_horizon,
        "features": _build_tags(
            ("clear_water", water_ratio > 0.25),
            ("sandy_shore", sand_ratio > 0.15),
            ("open_sky",    sky_ratio > 0.20),
            ("horizon_view", has_horizon),
        ),
    }


def _extract_hill_station(img: np.ndarray, hsv: np.ndarray) -> dict:
    # Snow: high brightness, low saturation
    snow_ratio = _hsv_ratio(hsv, [0, 0, 200], [180, 40, 255])
    # Green mountains
    green_ratio = _hsv_ratio(hsv, [35, 40, 60], [85, 255, 220])
    # Bare rock/brown
    rock_ratio = _hsv_ratio(hsv, [10, 20, 60], [30, 180, 200])
    # Fog/mist: desaturated, mid-brightness
    fog_ratio = _hsv_ratio(hsv, [0, 0, 140], [180, 40, 210])

    if snow_ratio > 0.15:
        sub = "snow_peak"
    elif green_ratio > 0.30:
        sub = "green_valley"
    elif fog_ratio > 0.25:
        sub = "misty_hill"
    else:
        sub = "barren_peak"

    return {
        "subcategory": sub,
        "snow_ratio": round(snow_ratio, 3),
        "green_ratio": round(green_ratio, 3),
        "rock_ratio": round(rock_ratio, 3),
        "fog_ratio": round(fog_ratio, 3),
        "features": _build_tags(
            ("snowcapped",   snow_ratio > 0.15),
            ("lush_green",   green_ratio > 0.25),
            ("misty",        fog_ratio > 0.20),
            ("rocky_terrain", rock_ratio > 0.20),
        ),
    }


def _extract_historical(img: np.ndarray, hsv: np.ndarray) -> dict:
    # Sandstone/ochre tones
    stone_ratio = _hsv_ratio(hsv, [8, 30, 80], [28, 200, 220])
    # Marble white
    marble_ratio = _hsv_ratio(hsv, [0, 0, 180], [180, 30, 255])

    # Architectural symmetry via Canny + vertical edge balance
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    h, w = edges.shape
    left  = int(np.sum(edges[:, :w//2]))
    right = int(np.sum(edges[:, w//2:]))
    symmetry_score = 1.0 - abs(left - right) / max(left + right, 1)

    # Intricate detail: high Laplacian variance
    detail_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    detail_norm  = min(detail_score / 2000.0, 1.0)

    # Palette from K-Means (3 dominant stone colours)
    palette = _dominant_colours(img, k=3)

    if marble_ratio > 0.20:
        sub = "marble_monument"
    elif stone_ratio > 0.25:
        sub = "sandstone_fort"
    else:
        sub = "ancient_ruins"

    return {
        "subcategory": sub,
        "stone_ratio": round(stone_ratio, 3),
        "marble_ratio": round(marble_ratio, 3),
        "symmetry_score": round(symmetry_score, 3),
        "detail_score": round(detail_norm, 3),
        "stone_palette": palette,
        "features": _build_tags(
            ("sandstone",   stone_ratio > 0.20),
            ("marble",      marble_ratio > 0.20),
            ("symmetric",   symmetry_score > 0.70),
            ("intricate",   detail_norm > 0.40),
        ),
    }


def _extract_national_park(img: np.ndarray, hsv: np.ndarray) -> dict:
    # Vegetation: deep greens
    veg_ratio  = _hsv_ratio(hsv, [35, 40, 40], [85, 255, 200])
    # Water body: dark blue-green
    water_ratio = _hsv_ratio(hsv, [85, 50, 50], [130, 255, 200])
    # Earth/soil
    soil_ratio  = _hsv_ratio(hsv, [8, 30, 60], [22, 200, 180])

    # Animal/wildlife ROI heuristic: look for warm-toned blobs (skin/fur)
    # using a wide warm-tan range with mid saturation
    animal_mask = cv2.inRange(hsv,
                               np.array([10, 40, 80], np.uint8),
                               np.array([30, 200, 220], np.uint8))
    contours, _ = cv2.findContours(animal_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blob_areas = [cv2.contourArea(c) for c in contours if cv2.contourArea(c) > 500]
    has_animal_roi = len(blob_areas) > 0

    if water_ratio > 0.20:
        sub = "waterhole"
    elif has_animal_roi and veg_ratio > 0.20:
        sub = "wildlife_habitat"
    elif veg_ratio > 0.40:
        sub = "dense_forest"
    else:
        sub = "savanna"

    return {
        "subcategory": sub,
        "vegetation_ratio": round(veg_ratio, 3),
        "water_ratio": round(water_ratio, 3),
        "soil_ratio": round(soil_ratio, 3),
        "has_animal_roi": has_animal_roi,
        "features": _build_tags(
            ("dense_forest",  veg_ratio > 0.40),
            ("waterhole",     water_ratio > 0.15),
            ("wildlife",      has_animal_roi),
            ("open_grassland", soil_ratio > 0.25 and veg_ratio < 0.30),
        ),
    }


def _extract_temple(img: np.ndarray, hsv: np.ndarray) -> dict:
    # Saffron/orange
    saffron_ratio = _hsv_ratio(hsv, [10, 120, 100], [22, 255, 255])
    # Gold/yellow
    gold_ratio    = _hsv_ratio(hsv, [22, 100, 120], [35, 255, 255])
    # Deep red (vermillion)
    red_ratio     = _hsv_ratio(hsv, [0, 100, 80], [10, 255, 255])
    # Dark stone (grey-brown)
    stone_ratio   = _hsv_ratio(hsv, [0, 0, 40], [180, 40, 140])

    # Intricate carvings → high Laplacian
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    detail_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    detail_norm  = min(detail_score / 2000.0, 1.0)

    palette = _dominant_colours(img, k=3)

    if saffron_ratio > 0.15 or gold_ratio > 0.10:
        sub = "colourful_temple"
    elif stone_ratio > 0.30:
        sub = "stone_temple"
    else:
        sub = "temple_architecture"

    return {
        "subcategory": sub,
        "saffron_ratio": round(saffron_ratio, 3),
        "gold_ratio":    round(gold_ratio, 3),
        "red_ratio":     round(red_ratio, 3),
        "stone_ratio":   round(stone_ratio, 3),
        "carvings_detail": round(detail_norm, 3),
        "colour_palette":  palette,
        "features": _build_tags(
            ("saffron_hues",  saffron_ratio > 0.10),
            ("golden_temple", gold_ratio > 0.10),
            ("vermillion",    red_ratio > 0.08),
            ("stone_carvings", stone_ratio > 0.25 and detail_norm > 0.35),
            ("ornate",        detail_norm > 0.50),
        ),
    }


def _extract_garden(img: np.ndarray, hsv: np.ndarray) -> dict:
    # Lush green
    green_ratio = _hsv_ratio(hsv, [35, 50, 60], [85, 255, 230])
    # Bloom: pink/magenta
    pink_ratio  = _hsv_ratio(hsv, [145, 60, 100], [175, 255, 255])
    # Yellow blooms
    yellow_ratio= _hsv_ratio(hsv, [22, 80, 120], [38, 255, 255])
    # Red blooms
    red_ratio   = _hsv_ratio(hsv, [0, 100, 100], [10, 255, 255])

    # Brightness harmony: std dev of brightness (lower = serene)
    bright_std = float(np.std(img[:, :, 2]))    # V channel std
    harmony = 1.0 - min(bright_std / 128.0, 1.0)

    bloom_present = (pink_ratio + yellow_ratio + red_ratio) > 0.05
    if bloom_present and green_ratio > 0.25:
        sub = "blooming_garden"
    elif green_ratio > 0.50:
        sub = "lush_greenery"
    else:
        sub = "ornamental_garden"

    return {
        "subcategory": sub,
        "green_ratio":  round(green_ratio, 3),
        "pink_ratio":   round(pink_ratio, 3),
        "yellow_ratio": round(yellow_ratio, 3),
        "red_ratio":    round(red_ratio, 3),
        "bloom_present": bloom_present,
        "harmony_score": round(harmony, 3),
        "features": _build_tags(
            ("lush_green",   green_ratio > 0.40),
            ("blooming",     bloom_present),
            ("pink_flowers", pink_ratio > 0.05),
            ("serene",       harmony > 0.65),
        ),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Category dispatcher
# ──────────────────────────────────────────────────────────────────────────────

# Canonical category names (lower-cased for robust matching)
_CATEGORY_MAP = {
    "beach":                _extract_beach,
    "hill station":         _extract_hill_station,
    "hill_station":         _extract_hill_station,
    "historical monuments": _extract_historical,
    "historical_monuments": _extract_historical,
    "national_park":        _extract_national_park,
    "national park":        _extract_national_park,
    "temple":               _extract_temple,
    "temples":              _extract_temple,
    "garden":               _extract_garden,
}

# Canonical display name
_CANONICAL = {
    "beach":                "Beach",
    "hill station":         "Hill Station",
    "hill_station":         "Hill Station",
    "historical monuments": "Historical Monuments",
    "historical_monuments": "Historical Monuments",
    "national_park":        "National Park",
    "national park":        "National Park",
    "temple":               "Temple",
    "temples":              "Temple",
    "garden":               "Garden",
}


def _build_tags(*cond_pairs) -> list[str]:
    return [tag for tag, cond in cond_pairs if cond]


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def extract_image_metadata(image_path: str, category: str) -> dict:
    """
    Extract rich, category-aware metadata for a single image.

    Parameters
    ----------
    image_path : absolute or relative path to the image file
    category   : raw folder name (e.g. "Beach", "hill station")

    Returns
    -------
    dict with keys: id, path, category, subcategory, quality_score,
                    mood, dominant_colors, features, + category-specific keys
    """
    cat_key = category.lower().strip()

    try:
        img = _load_bgr(image_path)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    except Exception as e:
        logger.warning(f"Skipping {image_path}: {e}")
        return None

    global_feats = _global_features(img)

    extractor = _CATEGORY_MAP.get(cat_key)
    category_feats = extractor(img, hsv) if extractor else {"subcategory": cat_key, "features": []}

    # Stable unique ID: hash of relative path
    img_id = hashlib.md5(image_path.encode()).hexdigest()[:12]

    return {
        "id":              img_id,
        "path":            image_path,          # relative from project root
        "category":        _CANONICAL.get(cat_key, category),
        **global_feats,
        **category_feats,
    }


def build_metadata_index(images_root: str, output_path: str) -> list[dict]:
    """
    Walk images/{train_set,test_set}/<category>/ and extract metadata for
    every image. Writes the result to output_path as JSON.
    
    Only the train_set is indexed (4-5k images) — test_set is for evaluation.
    """
    records = []
    train_root = Path(images_root) / "train_set"

    if not train_root.exists():
        logger.error(f"train_set not found at {train_root}")
        return []

    categories = [d for d in train_root.iterdir() if d.is_dir()]
    logger.info(f"Found {len(categories)} categories to index")

    for cat_dir in categories:
        category_name = cat_dir.name
        image_files = list(cat_dir.glob("*.jpg")) + list(cat_dir.glob("*.jpeg")) + list(cat_dir.glob("*.png"))
        logger.info(f"  {category_name}: {len(image_files)} images")

        for img_file in image_files:
            rel_path = str(img_file.relative_to(Path(images_root).parent)).replace("\\", "/")
            meta = extract_image_metadata(str(img_file), category_name)
            if meta:
                meta["path"] = rel_path   # overwrite with relative path for URL building
                records.append(meta)

    # Write index
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(records, f, indent=2)

    logger.info(f"Indexed {len(records)} images → {output_path}")
    return records
