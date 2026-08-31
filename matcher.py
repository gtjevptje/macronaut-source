"""
Unified on-screen image matching for Macronaut.

Both the Basic clicker (clicker.py) and the Sequence engine (recorder.py) use
this single module so matching behaves identically everywhere.

Key improvement over plain pyautogui.locate():
  * MULTI-SCALE matching — the template is searched at a range of sizes, so an
    image captured on one monitor/DPI still matches on a different
    resolution or Windows display-scaling setting (the #1 cause of
    "works on my machine, fails on theirs").
  * Optional GRAYSCALE fallback for minor colour/theme differences.
  * Returns the best similarity SCORE (not just found/not-found) so the UI can
    show a live confidence read-out.

Graceful degradation:
  * If OpenCV (cv2) is available  -> fast, robust multi-scale matching.
  * If only pyautogui is available -> falls back to single-scale locate().
  * If neither / PIL missing       -> ENABLED is False; callers should treat
    "can't check" as "don't block" so automation still runs.

All coordinates returned are in the pixel space of the screenshot that was
searched (for an all-screens grab that is PHYSICAL pixels), matching what the
callers already expect from pyautogui.locate().
"""

from collections import namedtuple
from typing import List, Optional

# Match in the coordinate space of the searched screenshot.
Match = namedtuple("Match", ["left", "top", "width", "height", "score"])

# ── Optional dependencies ──────────────────────────────────────────────────
try:
    import numpy as _np
    import cv2 as _cv2
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

try:
    from PIL import ImageGrab as _ImageGrab, Image as _Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

try:
    import pyautogui as _pyautogui
    _pyautogui.FAILSAFE = False
    _HAS_PYAUTOGUI = True
except Exception:
    _HAS_PYAUTOGUI = False

# Matching is possible if we can grab the screen (PIL) and match it somehow.
ENABLED = _HAS_PIL and (_HAS_CV2 or _HAS_PYAUTOGUI)
# True only when the upgraded multi-scale engine is active.
MULTISCALE = _HAS_CV2 and _HAS_PIL

# Default scale factors. Covers common DPI ratios (100/125/150/175/200 % and
# their inverses) plus small resolution differences. 1.0 is tried first.
DEFAULT_SCALES: List[float] = [
    1.0, 0.9, 1.1, 0.8, 1.25, 0.75, 1.33, 0.67, 1.5, 0.6, 2.0, 0.5,
]

_MIN_TEMPLATE_PX = 8   # ignore degenerate scaled templates


# ── Screen capture ──────────────────────────────────────────────────────────
def grab_all_screens():
    """Return a PIL RGB image of the full virtual desktop (physical pixels)."""
    if not _HAS_PIL:
        return None
    return _ImageGrab.grab(all_screens=True).convert("RGB")


# ── Core multi-scale matcher (OpenCV) ───────────────────────────────────────
def _best_match_cv2(hay_rgb, needle_rgb, scales, grayscale) -> Optional[Match]:
    """Best match of needle within hay across scales. Score-only, no threshold."""
    hay = _np.asarray(hay_rgb)
    needle = _np.asarray(needle_rgb)
    if grayscale:
        hay = _cv2.cvtColor(hay, _cv2.COLOR_RGB2GRAY)
        needle = _cv2.cvtColor(needle, _cv2.COLOR_RGB2GRAY)

    H, W = hay.shape[:2]
    nh, nw = needle.shape[:2]
    if nh == 0 or nw == 0:
        return None

    best: Optional[Match] = None
    for s in scales:
        tw, th = int(round(nw * s)), int(round(nh * s))
        if tw < _MIN_TEMPLATE_PX or th < _MIN_TEMPLATE_PX or tw > W or th > H:
            continue
        interp = _cv2.INTER_AREA if s < 1.0 else _cv2.INTER_LINEAR
        tmpl = _cv2.resize(needle, (tw, th), interpolation=interp)
        res = _cv2.matchTemplate(hay, tmpl, _cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = _cv2.minMaxLoc(res)
        if best is None or max_val > best.score:
            best = Match(int(max_loc[0]), int(max_loc[1]), tw, th, float(max_val))
    return best


def _best_match_pyautogui(template_path, screenshot, confidence) -> Optional[Match]:
    """Fallback: single-scale locate via pyautogui. Returns Match or None."""
    try:
        needle = _Image.open(template_path).convert("RGB")
        box = _pyautogui.locate(needle, screenshot, confidence=confidence)
    except Exception:
        return None
    if box is None:
        return None
    return Match(int(box.left), int(box.top), int(box.width), int(box.height),
                 float(confidence))


# ── Search-area helpers ──────────────────────────────────────────────────────
def _crop_to_region(shot, region):
    """
    Crop `shot` to a PHYSICAL (x, y, w, h) box, returning (image, dx, dy).

    dx/dy is the crop origin, which every match found inside the crop has to be
    shifted by — a caller that clicks what it found needs full-screenshot
    coordinates, not coordinates inside a box only this module knows about.
    An unusable region degrades to "search everything" rather than to nothing:
    a search area is an optimisation, and failing it closed would silently stop
    a working flow from ever matching. "Unusable" includes a zero-size box and
    one that lies entirely off the screenshot — clamping those to a 1x1 sliver
    would technically be a search area and would never match anything again.
    A region that merely *overhangs* an edge is clipped and still used.
    """
    if not region or shot is None:
        return shot, 0, 0
    try:
        x, y, w, h = (int(v) for v in region)
    except Exception:
        return shot, 0, 0
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(shot.width, x + w), min(shot.height, y + h)
    if w <= 0 or h <= 0 or x1 <= x0 or y1 <= y0:
        return shot, 0, 0
    try:
        return shot.crop((x0, y0, x1, y1)), x0, y0
    except Exception:
        return shot, 0, 0


def _shifted(m: Optional[Match], dx: int, dy: int) -> Optional[Match]:
    """Move a Match found in a crop back into full-screenshot coordinates."""
    if m is None or (dx == 0 and dy == 0):
        return m
    return m._replace(left=m.left + dx, top=m.top + dy)


# ── Public API ───────────────────────────────────────────────────────────────
def best_match(template_path: str, screenshot=None, grayscale: bool = True,
               scales: Optional[List[float]] = None, region=None) -> Optional[Match]:
    """
    Return the BEST match of the template anywhere on screen, regardless of
    threshold (so the UI can display the score). None if matching impossible.
    `screenshot` may be a pre-grabbed PIL RGB image; otherwise the full virtual
    desktop is grabbed. `region` is an optional PHYSICAL (x, y, w, h) search
    area; the returned box is still in full-screenshot coordinates either way.
    """
    if not ENABLED or not template_path:
        return None
    shot = screenshot if screenshot is not None else grab_all_screens()
    if shot is None:
        return None
    shot, dx, dy = _crop_to_region(shot, region)

    if _HAS_CV2:
        try:
            needle = _Image.open(template_path).convert("RGB")
        except Exception:
            return None
        sc = scales or DEFAULT_SCALES
        color = _best_match_cv2(shot, needle, sc, grayscale=False)
        if not grayscale:
            return _shifted(color, dx, dy)
        gray = _best_match_cv2(shot, needle, sc, grayscale=True)
        # Return whichever scored higher.
        if color is None:
            return _shifted(gray, dx, dy)
        if gray is None:
            return _shifted(color, dx, dy)
        return _shifted(color if color.score >= gray.score else gray, dx, dy)

    # No cv2: single-scale fallback (uses a default confidence just for the box).
    return _shifted(_best_match_pyautogui(template_path, shot, confidence=0.8),
                    dx, dy)


def find(template_path: str, confidence: float = 0.8, screenshot=None,
         grayscale: bool = True, scales: Optional[List[float]] = None,
         region=None) -> Optional[Match]:
    """
    Return a Match if the template is present at or above `confidence`,
    else None. Drop-in replacement for the old pyautogui.locate() calls; the
    returned box uses the same screenshot pixel coordinates. `region` narrows
    the search to a PHYSICAL (x, y, w, h) box without changing that.
    """
    if not ENABLED or not template_path:
        return None
    shot = screenshot if screenshot is not None else grab_all_screens()
    if shot is None:
        return None

    if _HAS_CV2:
        m = best_match(template_path, screenshot=shot, grayscale=grayscale,
                       scales=scales, region=region)
        return m if (m is not None and m.score >= confidence) else None

    # Fallback path honours confidence directly via pyautogui.
    shot, dx, dy = _crop_to_region(shot, region)
    return _shifted(_best_match_pyautogui(template_path, shot,
                                          confidence=confidence), dx, dy)


def present(template_path: str, confidence: float = 0.8, screenshot=None,
            region=None) -> bool:
    """Convenience boolean: is the template on screen at/above confidence?"""
    return find(template_path, confidence=confidence, screenshot=screenshot,
                region=region) is not None
