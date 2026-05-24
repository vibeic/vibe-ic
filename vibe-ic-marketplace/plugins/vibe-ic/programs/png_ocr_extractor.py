"""v1.6.124 — for #36 Bug 3: PNG OCR Tier-2 fallback.

Field-agent verbatim spec (issue #36 Bug 3):

  Apply to: litesata (PNG only), litesdcard, litedram, litescope
  Today the .dia parser works (litedram/litescope/litesdcard/sha1)
  and exposes real submodule names; PNG-only ICs (litesata) lose
  this entirely. Wire pytesseract or easyocr behind a feature
  flag so PNG-only diagrams contribute submodule labels.

This module ships the scaffolding for that fallback. By default
the picker is INERT — it only fires when:

  * Environment variable ``PHASE2A_ENABLE_OCR=1`` (or ``true`` /
    ``yes`` / ``on``, case-insensitive) is set, AND
  * ``pytesseract`` (a Python wrapper around the Tesseract OCR
    engine) AND ``PIL`` (Pillow) are importable.

When both conditions hold and PNG files exist under
``input/docs/``, OCR text is harvested and plausible
snake_case submodule identifiers are surfaced via the same
structural-floor heuristic used by the markdown file-list
extractor (≥1 underscore, ≥4 chars; chip-AGNOSTIC).

Both the env-var gate AND the import-graceful-degradation path
are tested; a follow-up issue can request the Tesseract binary
to be installed in the dev container if real-on-benchmark
verification is desired.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

OCR_FEATURE_FLAG = "PHASE2A_ENABLE_OCR"

# Truthy values for the feature flag (case-insensitive).
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Snake_case identifier — same structural floor as the markdown
# file-list extractor: ≥1 underscore, lowercase-led, all
# alphanumeric + underscore. Chip-AGNOSTIC.
_SUBMODULE_NAME_RE = re.compile(
    r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b",
)

# Generic identifiers that show up in vendor manuals / OCR noise
# and must NOT be recorded as submodules. Chip-AGNOSTIC list of
# tool/vendor placeholder words.
_GENERIC_DENY = frozenset({
    "test_bench", "tb_top", "test_top", "my_module",
    "your_module", "example_top", "dut_top", "top_level",
})

_MIN_NAME_LEN = 4
_MAX_HITS = 16


def is_ocr_feature_enabled() -> bool:
    """Return True iff the user has opted into OCR."""
    return os.environ.get(OCR_FEATURE_FLAG, "").strip().lower() in _TRUTHY


def is_ocr_runtime_available() -> bool:
    """Return True iff feature-flag enabled AND pytesseract / PIL
    are importable. False causes graceful no-op.
    """
    if not is_ocr_feature_enabled():
        return False
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


def _collect_png_paths(docs_dir: Path) -> List[Path]:
    if not docs_dir.is_dir():
        return []
    return sorted(docs_dir.rglob("*.png"))


def _ocr_one(png_path: Path) -> str:
    """Run pytesseract on a single PNG; return text or empty
    string on failure. Lazy import inside the body so callers can
    stub this for tests without needing the real Tesseract binary.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    try:
        with Image.open(png_path) as img:
            return pytesseract.image_to_string(img)
    except Exception:
        return ""


def _extract_names_from_ocr_text(text: str) -> List[str]:
    """Extract plausible snake_case submodule identifiers from
    OCR text. Apply structural floor + generic-name deny list.
    """
    names: List[str] = []
    seen: set = set()
    for m in _SUBMODULE_NAME_RE.finditer(text):
        name = m.group(1).lower()
        if len(name) < _MIN_NAME_LEN:
            continue
        if name in _GENERIC_DENY:
            continue
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def extract_submodules_from_png_diagrams(
    project: Optional[Path],
) -> List[dict]:
    """Tier-2 PNG-OCR submodule extractor.

    Returns a list of dicts shaped to populate the existing
    L9.submodules schema:

        {
            "name":          "rx_classifier",
            "role":          "extracted from PNG diagram OCR",
            "evidence_file": "input/docs/architecture.png",
        }

    Returns [] when feature flag is unset, dependencies missing,
    project path is None, no PNG files found, or OCR text yields
    no plausible identifiers.

    Chip-AGNOSTIC.
    """
    if project is None:
        return []
    if not is_ocr_runtime_available():
        return []

    docs_dir = project / "input" / "docs"
    png_paths = _collect_png_paths(docs_dir)
    if not png_paths:
        return []

    results: List[dict] = []
    seen: set = set()
    for png in png_paths:
        text = _ocr_one(png)
        if not text:
            continue
        for name in _extract_names_from_ocr_text(text):
            if name in seen:
                continue
            seen.add(name)
            try:
                rel_path = str(png.relative_to(project))
            except ValueError:
                rel_path = str(png)
            results.append({
                "name":          name,
                "role":          "extracted from PNG diagram OCR",
                "evidence_file": rel_path,
            })
            if len(results) >= _MAX_HITS:
                return results
    return results


__all__ = [
    "OCR_FEATURE_FLAG",
    "extract_submodules_from_png_diagrams",
    "is_ocr_feature_enabled",
    "is_ocr_runtime_available",
]
