"""
feed_engine.py
--------------
Ranks the metadata index into a personalised Pinterest-style feed.

No database — everything is computed from:
  - The pre-built metadata index (list of dicts)
  - The client's interaction history (last 20, sent from mobile cache)

Scoring formula (weights tunable at top of file):
  score = quality(35%) + category_affinity(40%) + mood_match(15%) + variety(10%)
"""

import math
import random
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────────
# Tuneable weights
# ──────────────────────────────────────────────────────────────────────────────
W_QUALITY    = 0.35
W_CATEGORY   = 0.40
W_MOOD       = 0.15
W_VARIETY    = 0.10

# Max fraction of any single category in one page (diversity guard)
MAX_CATEGORY_FRACTION = 0.45

# ──────────────────────────────────────────────────────────────────────────────
# History parsing
# ──────────────────────────────────────────────────────────────────────────────

def _parse_history(history: Optional[list]) -> dict:
    """
    Parse the client's last-20-interactions list into affinity maps.

    Each interaction item expected shape:
        {
            "id": "abc123",
            "category": "Temple",
            "subcategory": "colourful_temple",   # optional
            "mood": "vibrant",                   # optional
            "viewDuration": 8.5                  # seconds, optional
        }

    Returns:
        {
            "category_weights": {"Temple": 0.8, "Beach": 0.3, ...},
            "mood_weights":     {"vibrant": 0.6, ...},
            "seen_ids":         {"abc123", ...}
        }
    """
    if not history:
        return {"category_weights": {}, "mood_weights": {}, "seen_ids": set()}

    cat_counts: dict[str, float] = {}
    mood_counts: dict[str, float] = {}
    seen: set[str] = set()

    for item in history:
        if not isinstance(item, dict):
            continue
        cat  = item.get("category", "")
        mood = item.get("mood", "")
        dur  = float(item.get("viewDuration", 1.0))
        iid  = item.get("id", "")

        # Weight by view duration (longer engagement = stronger signal)
        weight = math.log1p(max(dur, 0.5))

        if cat:
            cat_counts[cat] = cat_counts.get(cat, 0.0) + weight
        if mood:
            mood_counts[mood] = mood_counts.get(mood, 0.0) + weight
        if iid:
            seen.add(iid)

    def _normalise(d: dict) -> dict:
        total = sum(d.values()) or 1.0
        return {k: v / total for k, v in d.items()}

    return {
        "category_weights": _normalise(cat_counts),
        "mood_weights":     _normalise(mood_counts),
        "seen_ids":         seen,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────────────

def _score_image(img: dict, affinity: dict) -> float:
    # 1. Quality ── already 0-100, normalise to 0-1
    quality_norm = img.get("quality_score", 50) / 100.0

    # 2. Category affinity
    cat = img.get("category", "")
    cat_score = affinity["category_weights"].get(cat, 0.0)
    # If no history → uniform (0.5 so cold-start still works)
    if not affinity["category_weights"]:
        cat_score = 0.5

    # 3. Mood match
    mood = img.get("mood", "")
    mood_score = affinity["mood_weights"].get(mood, 0.0)
    if not affinity["mood_weights"]:
        mood_score = 0.5

    # 4. Variety (small random jitter so identical scores get shuffled)
    variety = random.uniform(0.0, 1.0)

    return (
        W_QUALITY  * quality_norm +
        W_CATEGORY * cat_score    +
        W_MOOD     * mood_score   +
        W_VARIETY  * variety
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def generate_feed(
    index: list[dict],
    history: Optional[list],
    categories: Optional[list[str]],
    seen_ids: Optional[list[str]],
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """
    Rank and paginate the index into a personalised feed.

    Parameters
    ----------
    index      : full metadata list (from index.json)
    history    : client's last-20 interaction list (may be None / empty)
    categories : optional category filter list (["Beach", "Temple"])
    seen_ids   : IDs the client already displayed (penalised but not hidden)
    limit      : page size
    offset     : for pagination (skip N top results)

    Returns
    -------
    List of ranked image dicts (enriched with score field)
    """
    affinity = _parse_history(history)

    # Merge seen_ids from affinity + explicit param
    all_seen = affinity["seen_ids"] | set(seen_ids or [])

    # ── Filter by category if requested ──────────────────────────────────────
    pool = index
    if categories:
        canon = {c.lower() for c in categories}
        pool = [img for img in index if img.get("category", "").lower() in canon]

    # ── Score ──────────────────────────────────────────────────────────────
    for img in pool:
        base = _score_image(img, affinity)
        # Penalise previously seen items (show them, but push down)
        if img.get("id") in all_seen:
            base *= 0.4
        img["_score"] = base

    # ── Sort by score desc ─────────────────────────────────────────────────
    ranked = sorted(pool, key=lambda x: x["_score"], reverse=True)

    # ── Diversity cap: no single category > MAX_CATEGORY_FRACTION ──────────
    final: list[dict] = []
    cat_counts_final: dict[str, int] = {}
    cap = max(1, int((limit + offset) * MAX_CATEGORY_FRACTION))

    for img in ranked:
        cat = img.get("category", "")
        if cat_counts_final.get(cat, 0) >= cap:
            continue
        cat_counts_final[cat] = cat_counts_final.get(cat, 0) + 1
        final.append(img)
        if len(final) >= limit + offset:
            break

    # Apply offset
    page = final[offset: offset + limit]

    # Strip internal score from response
    for img in page:
        img.pop("_score", None)

    return page
