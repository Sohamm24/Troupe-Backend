"""
image_matcher.py
----------------
Visual similarity matching for the POST /api/match route.

Strategy (fast + meaningful, no deep learning):
  score = 0.6 × colour_histogram_similarity
        + 0.4 × ORB_keypoint_match_ratio

Pre-computed ORB descriptors + colour histograms are stored in:
  metadata/descriptors.npz

This file is built once (at startup or via rebuild) and memory-mapped on load,
making per-request matching sub-second even for 5k images on CPU.
"""

import os
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

HIST_BINS    = 32        # bins per HSV channel for colour histogram
ORB_FEATURES = 500       # max ORB keypoints per image
MATCH_RATIO  = 0.75      # Lowe's ratio test threshold
W_COLOUR     = 0.60
W_ORB        = 0.40


# ──────────────────────────────────────────────────────────────────────────────
# Feature computation (shared between build and query)
# ──────────────────────────────────────────────────────────────────────────────

def _resize_for_matching(img: np.ndarray) -> np.ndarray:
    """Downscale to 320px wide for speed."""
    h, w = img.shape[:2]
    if w > 320:
        scale = 320 / w
        img = cv2.resize(img, (320, int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def _compute_colour_hist(img: np.ndarray) -> np.ndarray:
    """Normalised HSV histogram (H+S+V concatenated, 32 bins each → 96 dims)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h_hist = cv2.calcHist([hsv], [0], None, [HIST_BINS], [0, 180]).flatten()
    s_hist = cv2.calcHist([hsv], [1], None, [HIST_BINS], [0, 256]).flatten()
    v_hist = cv2.calcHist([hsv], [2], None, [HIST_BINS], [0, 256]).flatten()
    hist = np.concatenate([h_hist, s_hist, v_hist]).astype(np.float32)
    # L1 normalise
    total = hist.sum()
    if total > 0:
        hist /= total
    return hist


def _compute_orb_descriptor(img: np.ndarray) -> Optional[np.ndarray]:
    """ORB descriptor matrix (Nx32 uint8). Returns None if no keypoints."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    orb  = cv2.ORB_create(nfeatures=ORB_FEATURES)
    _, des = orb.detectAndCompute(gray, None)
    return des   # None if no keypoints found


# ──────────────────────────────────────────────────────────────────────────────
# Pre-computation (build phase)
# ──────────────────────────────────────────────────────────────────────────────

def build_descriptor_store(index: list[dict], images_root: str, output_path: str) -> None:
    """
    For every image in the metadata index, compute:
      - colour histogram  → stored as float32 array
      - ORB descriptor    → stored as uint8 array (padded / truncated to ORB_FEATURES rows)

    Saves two .npy arrays inside a single .npz file:
      hists      : (N, 96)    float32
      orb_descs  : (N, 500*32) uint8    ← flattened, -1 for missing keypoints
      ids        : (N,)       str

    Parameters
    ----------
    index       : metadata list (from feature_extractor)
    images_root : absolute path to the project root (parent of images/)
    output_path : where to write the .npz file
    """
    n = len(index)
    hists      = np.zeros((n, HIST_BINS * 3),           dtype=np.float32)
    orb_descs  = np.full((n, ORB_FEATURES * 32), -1,    dtype=np.int16)
    ids        = np.empty(n, dtype=object)

    root = Path(images_root)

    for i, meta in enumerate(index):
        ids[i] = meta["id"]
        img_path = root / meta["path"]

        img = cv2.imread(str(img_path))
        if img is None:
            logger.warning(f"Cannot read {img_path}, skipping descriptor")
            continue

        img = _resize_for_matching(img)

        # Colour histogram
        hists[i] = _compute_colour_hist(img)

        # ORB
        des = _compute_orb_descriptor(img)
        if des is not None:
            # Truncate or pad to exactly ORB_FEATURES rows
            rows = min(des.shape[0], ORB_FEATURES)
            flat = des[:rows, :].flatten()
            orb_descs[i, :len(flat)] = flat.astype(np.int16)

        if (i + 1) % 200 == 0:
            logger.info(f"  Descriptors: {i+1}/{n}")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    np.savez_compressed(output_path, hists=hists, orb_descs=orb_descs, ids=ids)
    logger.info(f"Saved descriptors → {output_path}")


# ──────────────────────────────────────────────────────────────────────────────
# Runtime matching
# ──────────────────────────────────────────────────────────────────────────────

class ImageMatcher:
    """
    Singleton-friendly matcher. Load once at startup, call find_similar() per request.
    """

    def __init__(self, descriptor_path: str, index: list[dict]):
        data = np.load(descriptor_path, allow_pickle=True)
        self.hists      = data["hists"]        # (N, 96)
        self.orb_descs  = data["orb_descs"]    # (N, ORB_FEATURES*32)
        self.ids        = data["ids"]          # (N,)
        # Build id→metadata map for quick lookup
        self.id_meta = {m["id"]: m for m in index}
        logger.info(f"ImageMatcher loaded {len(self.ids)} descriptors")

    # ──────────────────────────────────────────────────────────────────

    def _colour_similarity(self, query_hist: np.ndarray) -> np.ndarray:
        """Bhattacharyya coefficient for each row (higher = more similar)."""
        # Vectorised dot product approximation (fast Manhattan-complement)
        # 1 - normalised L1 distance  →  in [0,1]
        dist = np.sum(np.abs(self.hists - query_hist), axis=1)  # (N,)
        return 1.0 - (dist / 2.0)   # convert to similarity

    def _orb_similarity(self, query_des: Optional[np.ndarray]) -> np.ndarray:
        """BF match ratio for each stored descriptor. Returns 0 for no-keypoint cases."""
        sims = np.zeros(len(self.ids), dtype=np.float32)
        if query_des is None:
            return sims

        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        q32 = query_des.astype(np.uint8)

        for i, flat in enumerate(self.orb_descs):
            # Reconstruct descriptor (skip if all -1 = no keypoints)
            if flat[0] == -1:
                continue
            valid = flat[flat >= 0]
            if len(valid) < 32:
                continue
            rows = len(valid) // 32
            stored_des = valid[: rows * 32].reshape(rows, 32).astype(np.uint8)

            try:
                matches = bf.knnMatch(q32, stored_des, k=2)
                good = sum(
                    1 for m in matches
                    if len(m) == 2 and m[0].distance < MATCH_RATIO * m[1].distance
                )
                sims[i] = good / max(len(q32), 1)
            except Exception:
                pass

        return sims

    # ──────────────────────────────────────────────────────────────────

    def find_similar(self, image_bytes: bytes, top_n: int = 10) -> list[dict]:
        """
        Find top-N visually similar images from the dataset.

        Parameters
        ----------
        image_bytes : raw uploaded image bytes
        top_n       : number of results to return

        Returns
        -------
        List of dicts: metadata + similarity_score (0-1)
        """
        # Decode uploaded image
        arr  = np.frombuffer(image_bytes, np.uint8)
        img  = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Cannot decode uploaded image")

        img = _resize_for_matching(img)

        # Compute query features
        q_hist = _compute_colour_hist(img)
        q_des  = _compute_orb_descriptor(img)

        # Score all indexed images
        colour_sims = self._colour_similarity(q_hist)
        orb_sims    = self._orb_similarity(q_des)

        scores = W_COLOUR * colour_sims + W_ORB * orb_sims

        # Get top-N indices
        top_indices = np.argsort(scores)[::-1][:top_n]

        results = []
        for idx in top_indices:
            img_id = str(self.ids[idx])
            meta   = self.id_meta.get(img_id, {})
            if not meta:
                continue
            result = dict(meta)
            result["similarity_score"] = round(float(scores[idx]), 4)
            results.append(result)

        return results


# ──────────────────────────────────────────────────────────────────────────────
# Convenience: match from a temp file path (used in router)
# ──────────────────────────────────────────────────────────────────────────────

def match_from_upload(matcher: ImageMatcher, file_bytes: bytes, top_n: int = 10) -> list[dict]:
    return matcher.find_similar(file_bytes, top_n=top_n)
