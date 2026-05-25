"""v1.6.121 — for #36 Bug 9 (L8 portion): SATA-spec timing literal picker.

Field-agent verbatim spec (issue #36 Bug 9, L8 sub-portion):

  Apply to: litesata
  Pattern: literal speeds (1.5 / 3.0 / 6.0 Gbps), system clocks
    (37.5 / 75 / 150 MHz).
  Output: L8.timing_constants.

The SATA spec line rates (1.5 / 3.0 / 6.0 Gbps for Gen1 / Gen2 /
Gen3) and the litex-litesata system-clock values (37.5 / 75 / 150
MHz) are all specific enough that observing ≥2 of them in the same
document is high-confidence SATA evidence.

The L8 generator's existing timing-constant extractor only looks at
files matching `timing|wave|signal|measure` and at AID-class
timing names (`T_<NAME>` / `tBR` / `tIBT` / etc.). It misses the
SATA-spec literal speeds + clocks because they live in the README
under prose, not in a timing-named file with a T-prefixed name.

Chip-AGNOSTIC: pure regex against industry-standard SATA-spec
literals. No chip-specific identifiers.
"""
from __future__ import annotations

import re
from typing import List, Optional

# SATA spec line rates — Gen1 / Gen2 / Gen3.
_SATA_LINE_RATES = {
    "1.5": ("sata_gen1_line_rate", 1.5),
    "3.0": ("sata_gen2_line_rate", 3.0),
    "6.0": ("sata_gen3_line_rate", 6.0),
}
_SATA_LINE_RATE_RE = re.compile(
    r"\b(1\.5|3\.0|6\.0)\s*Gbps\b",
    re.IGNORECASE,
)

# litex-litesata canonical system-clock values.
_SATA_SYS_CLOCKS = {
    "37.5": ("sata_sys_clk_37p5_mhz", 37.5),
    "75":   ("sata_sys_clk_75_mhz",   75.0),
    "150":  ("sata_sys_clk_150_mhz",  150.0),
}
_SATA_SYS_CLOCK_RE = re.compile(
    r"\b(37\.5|75|150)\s*MHz\b",
    re.IGNORECASE,
)

# v1.6.122 (#46) — slash-separated value tuple form. Real LiteSATA
# README phrases all six literals on a single line:
#   "1.5/3.0/6.0GBps supported speeds
#    (respectively 37.5/75/150MHz system clk)"
# Each tuple ends with a SHARED unit. Pre-tokenize into individual
# (value, unit) pairs before unit-anchored single-value matching.
# Accept both `Gbps` (industry standard) and `GBps` (LiteSATA README
# capital-B variant).
_SLASH_TUPLE_RE = re.compile(
    r"(?P<values>\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)+)"
    r"\s*"
    r"(?P<unit>Gbps|GBps|MHz)\b",
    re.IGNORECASE,
)

_MIN_HITS_PER_FILE = 2


def extract_sata_timing_constants_from_readme(
    readme_text: Optional[str],
) -> List[dict]:
    """Return SATA-spec timing-constant hits.

    Each hit is shaped to populate the existing L8.timing_constants
    schema:

        {
            "name":          "sata_gen3_line_rate",
            "value":         6.0,
            "unit":          "Gbps",
            "evidence_line": L,
        }

    Empty list when fewer than ``_MIN_HITS_PER_FILE`` distinct SATA
    timing literals are mentioned. Chip-AGNOSTIC.
    """
    if not readme_text:
        return []

    out: List[dict] = []
    seen: set = set()
    for line_num, line in enumerate(readme_text.split("\n"), start=1):
        # v1.6.122 (#46) — Pass A: slash-separated value tuples.
        # Expand each tuple into individual (value, unit) hits BEFORE
        # the single-value regexes. This catches the real-LiteSATA
        # canonical phrasing "1.5/3.0/6.0GBps" / "37.5/75/150MHz".
        for m in _SLASH_TUPLE_RE.finditer(line):
            unit_raw = m.group("unit").lower()
            canonical_unit = "MHz" if unit_raw == "mhz" else "Gbps"
            for raw_v in m.group("values").split("/"):
                tag = raw_v.strip()
                if canonical_unit == "Gbps" and tag in _SATA_LINE_RATES:
                    name, value = _SATA_LINE_RATES[tag]
                elif canonical_unit == "MHz" and tag in _SATA_SYS_CLOCKS:
                    name, value = _SATA_SYS_CLOCKS[tag]
                else:
                    continue
                if name in seen:
                    continue
                seen.add(name)
                out.append({
                    "name":          name,
                    "value":         value,
                    "unit":          canonical_unit,
                    "evidence_line": line_num,
                })

        # Pass B — single-value form (preserves v1.6.121 behaviour).
        for m in _SATA_LINE_RATE_RE.finditer(line):
            tag = m.group(1)
            if tag not in _SATA_LINE_RATES:
                continue
            name, value = _SATA_LINE_RATES[tag]
            if name in seen:
                continue
            seen.add(name)
            out.append({
                "name":          name,
                "value":         value,
                "unit":          "Gbps",
                "evidence_line": line_num,
            })
        for m in _SATA_SYS_CLOCK_RE.finditer(line):
            tag = m.group(1)
            if tag not in _SATA_SYS_CLOCKS:
                continue
            name, value = _SATA_SYS_CLOCKS[tag]
            if name in seen:
                continue
            seen.add(name)
            out.append({
                "name":          name,
                "value":         value,
                "unit":          "MHz",
                "evidence_line": line_num,
            })

    if len(out) < _MIN_HITS_PER_FILE:
        return []
    return out


__all__ = [
    "extract_sata_timing_constants_from_readme",
]
