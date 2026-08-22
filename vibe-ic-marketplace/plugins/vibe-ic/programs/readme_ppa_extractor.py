"""v1.6.118 — for #36 Bug 10: PPA implementation-results table picker.

Field-agent verbatim spec (issue #36 Bug 10):

  Apply to: ALL 10 ICs
  Pattern: rows in README implementation tables matching
    ``(LUTs|Regs|ALMs|LEs|Slices|Fmax|MHz|kCells|um)\\s*[:|]\\s*\\d+``
  E.g. AES has TSMC180nm 8 kCells / 520x520 um.
  Output: ``L1.implementation_results[platform].{luts, regs, fmax_mhz, ...}``

Many open-source IPs ship a README section labelled "Implementation
results" / "Resource utilization" / "Synthesis results" that shows
post-synthesis or post-fitter PPA numbers, either as a markdown
table:

    | Platform   | LUTs | Regs | Fmax    |
    |------------|------|------|---------|
    | Cyclone V  | 1234 | 567  | 250 MHz |
    | Stratix V  | 2345 | 678  | 300 MHz |

or as inline key-value lists under a per-platform heading:

    ## Cyclone V
    LUTs: 1234
    Regs: 567
    Fmax: 250 MHz

The phase1 runner emits L1.implementation_results = []
for every IC today. This picker extracts the structured PPA
numbers from either presentation form so downstream consumers
(architecture exploration, PPA-prediction calibration) have real
ground truth to work from.

Chip-AGNOSTIC. Pure regex over README markdown.
"""
from __future__ import annotations

import argparse
import os
import re
import sys as _sys
from pathlib import Path as _Path
from typing import Any, Dict, List, Optional, Tuple

# A bare `from _atomic_artefact import ...` works when this file is run as a
# script (sys.path[0] is this directory) and DIES when a test loads it through
# `importlib.util.spec_from_file_location`, which puts nothing on sys.path.
# Ten programs in this tree already carry that latent break; this one does not.
_PROGRAMS_DIR = _Path(__file__).resolve().parent
if str(_PROGRAMS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_PROGRAMS_DIR))

from _atomic_artefact import write_text as _atomic_write_text  # noqa: E402
from _ppa.canonical_json import digest_of as _digest_of  # noqa: E402
from _ppa.canonical_json import dumps as _canon_dumps  # noqa: E402

# Canonical metric keys (lowercase) and their token aliases.
# Chip-AGNOSTIC: these are FPGA / ASIC industry-standard PPA metric
# names, not chip-specific identifiers.
# v1.6.138 (#53 Defect A) adds:
#   - combinational_cells / noncombinational_cells / total_cells —
#     ASIC stdcell counts published by post-synth flows (e.g. sha256
#     40nm low-power-stdcell block).
#   - `clock frequency` alias on fmax_mhz — ASIC datasheets often use
#     this phrasing instead of `Fmax`.
_METRIC_TOKENS: Dict[str, List[str]] = {
    "luts":      ["luts", "lut"],
    "regs":      ["regs", "registers", "ffs"],
    "alms":      ["alms", "alm"],
    "les":       ["les"],
    "slices":    ["slices", "slice"],
    "fmax_mhz":  ["fmax", "f_max", "fmax_mhz",
                  "clock frequency", "clock_frequency"],
    "kcells":    ["kcells", "kgates", "gates"],
    "kbits":     ["kbits", "kb"],
    "rams":      ["rams", "brams", "block_rams", "m9k", "m20k"],
    "dsps":      ["dsps", "dsp"],
    "combinational_cells":    ["combinational cells",
                               "combinational_cells"],
    "noncombinational_cells": ["non-combinational cells",
                               "noncombinational cells",
                               "non_combinational_cells",
                               "noncombinational_cells"],
    "total_cells":            ["total cells", "total_cells"],
}

# Reverse lookup: alias-token (lowercase) → canonical metric key.
_TOKEN_TO_METRIC: Dict[str, str] = {
    alias: metric
    for metric, aliases in _METRIC_TOKENS.items()
    for alias in aliases
}

# Inline metric line: `LUTs: 1234` / `Fmax = 250 MHz` / `LUTs | 1234`.
_INLINE_RE = re.compile(
    r"\b(?P<metric>"
    + "|".join(re.escape(a) for a in _TOKEN_TO_METRIC)
    + r")\b\s*[:=|]\s*"
    r"(?P<value>\d+(?:\.\d+)?)"
    r"\s*(?P<unit>[A-Za-z][\w/]{0,8})?",
    re.IGNORECASE,
)

# v1.6.119 (#45) — number-first bullet form, dominant pattern in
# aes / sha1 / sha256 READMEs:
#     - 2624 ALMs
#     - 8 kCells
#     - 96 MHz
#     - 1589 LUTs
# The leading bullet (`-` / `*` / `+` / `•` / `·`) is optional; the
# value comes BEFORE the metric token rather than after a `:`/`=`/`|`
# separator. Optional SI prefix (k / K / M / G) between value and
# metric scales the value.
_NUMBER_FIRST_RE = re.compile(
    r"^[\s\-*+•·]*"                                  # bullets / whitespace
    r"(?P<value>\d+(?:\.\d+)?)\s*"                   # numeric value
    r"(?P<si>[kKMG])?\s*"                            # optional SI prefix
    r"(?P<metric>"
    r"LUTs?|Regs?|ALMs?|LEs?|Slices?|kCells?|kBits?|MHz|GHz|"
    r"BRAMs?|RAMs?|DSPs?|cycles?"
    r")\b",
    re.IGNORECASE,
)

# Number-first metric token (lowercase) → canonical metric key.
# Distinct from _TOKEN_TO_METRIC so the number-first regex can also
# accept `MHz` / `GHz` as METRIC tokens (in inline-KV form they are
# UNIT suffixes attached to `Fmax`).
_NUMBER_FIRST_METRIC_MAP: Dict[str, str] = {
    "lut": "luts", "luts": "luts",
    "reg": "regs", "regs": "regs",
    "alm": "alms", "alms": "alms",
    "le":  "les",  "les":  "les",
    "slice": "slices", "slices": "slices",
    "kcell": "kcells", "kcells": "kcells",
    "kbit": "kbits", "kbits": "kbits",
    "mhz": "fmax_mhz",
    "ghz": "fmax_mhz",
    "ram": "rams", "rams": "rams",
    "bram": "rams", "brams": "rams",
    "dsp": "dsps", "dsps": "dsps",
    "cycle": "cycles", "cycles": "cycles",
}

# Heading line that gives a platform hint for subsequent inline metrics.
# Matches markdown headings (`## Platform`) and "Platform: Cyclone V".
# v1.6.138 (#53 Defect A) — also recognise plain-text tech-node
# prose like `Implementation in 40 nm low power standard cell process.`
# / `Implemented in TSMC 180nm` / `Synthesised on Cyclone V`.
# Without this, the sha256 40nm ASIC stdcell block has no platform
# context and the per-platform record loses its `platform` field.
# v1.6.175 (#73) — added optional `\s+#+` tail to swallow markdown
# heading closers like `### Altera Cyclone FPGAs ###` so the trailing
# `###` never leaks into platform / vendor fields.
_HEADING_RE = re.compile(
    r"^\s*[\-*+•·]?\s*(?:"
    r"#{1,4}\s+(?P<h1>.+?)(?:\s+#+)?|"
    r"(?:platform|target|device|technology|tech\s*node|fpga|asic)"
    r"\s*[:=]\s*(?P<h2>.+?)|"
    r"(?:implementation\s+in|implemented\s+in|"
    r"synthesi[sz]ed\s+(?:in|on)|results\s+on)"
    r"\s+(?P<h3>.+?)"
    r")\s*\.?\s*$",
    re.IGNORECASE,
)

# v1.6.176 (#74) — ASIC area / die-size kv line. Two of 11 ICs
# document silicon area in their README in plain bullet form:
#
#     - Aera: 520 x 520 um     (typo: 'Aera' not 'Area', sic)
#     - Area: 14200 um2
#     - Die size: 0.142 mm2
#
# Pre-v1.6.176 the picker recognised LUTs / kCells / Registers /
# Fmax etc but not area — a tapeout-grade ASIC metric — so 2 of
# 11 ICs lost their silicon-area datapoint entirely.
#
# Accepts both scalar (`14200 um2`) and side-length-pair
# (`520 x 520 um`) forms; ASCII `x` and Unicode `×` both work.
# Tolerates the common `Aera` typo seen in the wild (aes README).
# chip-AGNOSTIC: pure regex over ASIC datasheet vocabulary.
_RE_AREA_KV = re.compile(
    r"^\s*[\-*+•·]?\s*"
    r"(?:Area|Aera|Die\s*size|Silicon\s*area|Active\s*area|Core\s*area)"
    r"\s*[:=]\s*"
    r"(?P<value>[\d.]+(?:\s*[x×]\s*[\d.]+)?)"
    r"\s*(?P<unit>um2|µm2|um\^2|µm\^2|mm2|µm|um|mm)\b",
    re.IGNORECASE,
)

# v1.6.175 (#73) — bold-emphasised sub-platform header. Real
# hash-core READMEs (sha1 / sha256, Bjorn Berg / SecWorks family)
# organise FPGA-proven results as a three-level pyramid:
#
#     ### Altera Cyclone FPGAs ###     <- vendor (markdown heading)
#     **Cyclone IV E**                  <- sub-platform / family (bold)
#     - Device: EP4CE6F17C6             <- per-family device + metrics
#     - LUTs: 1538
#     - Registers: 432
#     - Fmax: 51 MHz
#
# Pre-v1.6.175 the bold sub-header was invisible to the picker, so
# every block under one `### …` collapsed into a single record
# whose `platform` field was the vendor heading. This loses
# vendor-vs-family identity for 11 entries on sha1+sha256.
#
# The bold sub-header is `**Family**` (markdown bold) or
# `***Family***` (markdown bold+italic). The text inside is the
# canonical platform name; the surrounding `###` heading becomes
# the `vendor` field. chip-AGNOSTIC: never matches any chip-class
# string.
_RE_PLATFORM_BOLD_SUBHEADER = re.compile(
    r"^\s*\*{2,3}\s*(?P<family>[^*\n]+?)\s*\*{2,3}\s*$",
)

# Markdown table row: `| col1 | col2 | col3 |`.
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
# Markdown table separator: `|---|---|---|` or `|:--|:--:|`.
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")

# v1.6.141 (#55) — bullet-form sub-variant boundary marker.
# Matches a bullet line that is JUST an identifier (optionally
# followed by a parenthetical clarifier), with no separator and no
# metric token, e.g. ``- cmt_sbox`` or ``- master (S-box with table)``.
# These lines separate "variant" blocks under a common parent heading
# (``#### Altera`` / ``- Device: Cyclone V``). Without this, the
# picker's `setdefault` semantics kept the first variant's metrics
# and silently dropped every following variant's metrics + sub-blocks.
# The variant identifier is composed into the next block's
# platform_hint as ``<parent> / <variant>`` so each block surfaces as
# a distinct implementation_results entry.
_BULLET_SUBVARIANT_RE = re.compile(
    r"^\s*[\-*+•·]\s+"                                # mandatory bullet
    r"(?P<name>[A-Za-z][\w]*(?:[._\-]\w+)*)"          # identifier
    r"(?:\s+\([^)]*\))?"                              # optional clarifier
    r"\s*$",                                          # nothing else
)

# v1.6.183 (#73 v2) — device-code form for bold-sub-header context.
# Real FPGA device codes routinely start with a digit
# (`5CGXFC7D6F31C7` Cyclone V) or a letter+digit mix
# (`xc6slx45-3csg324` Spartan-6, `EP4CE6F17C6` Cyclone IV E). The
# original _BULLET_SUBVARIANT_RE required a leading letter, so
# digit-led device codes silently fell through. This relaxed form
# is gated on `extraction_strategy_hint` in the main loop so it
# only fires inside an established bold-sub-header block; outside
# that context it would over-capture numeric noise.
_RE_BULLET_DEVICE_CODE_ANY_LEAD = re.compile(
    r"^\s*[\-*+•·]\s+"
    r"(?P<name>[A-Za-z0-9][\w]*(?:[._\-]\w+)*)"
    r"(?:\s+\([^)]*\))?"
    r"\s*$",
)

# v1.6.139 (#53 Defect D) — sub-block resource breakdown line.
# Matches per-submodule resource counts that occur INSIDE an existing
# platform context, e.g. ``- aes_sbox: 160 ALUTs`` or
# ``- mixer_unit: 22 ALMs``. The identifier on the left of the colon
# is a submodule/function name (SCREAMING_SNAKE or snake_case),
# distinct from the platform-level metric tokens handled by
# ``_INLINE_RE``. Only attaches when the current block already has at
# least one platform-level metric — this prevents random prose like
# ``column: 5 items`` from being mis-classified as a sub-block.
# Separator is `:` only (not `=`); the unit alternation is the strong
# guard against false positives.
_SUB_BLOCK_RE = re.compile(
    r"^\s*[\-*+•·]?\s*"
    r"(?P<name>[A-Za-z][\w]*(?:[.\-]\w+)*)\s*"
    r":\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>ALUTs?|LUTs?|ALMs?|FFs?|registers?|"
    r"slices?|kCells?|LEs?|gates?|cells?)\b",
    re.IGNORECASE,
)

# Sub-block unit token (lowercase) → canonical sub-block count key.
_SUB_BLOCK_UNIT_MAP: Dict[str, str] = {
    "alut": "alut_count", "aluts": "alut_count",
    "lut":  "lut_count",  "luts":  "lut_count",
    "alm":  "alm_count",  "alms":  "alm_count",
    "ff":   "ff_count",   "ffs":   "ff_count",
    "register": "ff_count", "registers": "ff_count",
    "slice": "slice_count", "slices": "slice_count",
    "kcell": "kcell_count", "kcells": "kcell_count",
    "le":    "le_count",   "les":    "le_count",
    "gate":  "cell_count", "gates":  "cell_count",
    "cell":  "cell_count", "cells":  "cell_count",
}

# Names that must NOT be treated as sub-block identifiers — they are
# platform / vendor / heading words that legitimately precede colons
# in PPA prose ("Cyclone: 1234 LUTs"). Sub-blocks are submodules of
# the DUT (function names like aes_sbox / mixer_core), not vendors.
_SUB_BLOCK_NAME_DENY = frozenset({
    "cyclone", "stratix", "arria", "xilinx", "altera", "intel",
    "spartan", "kintex", "virtex", "artix", "zynq", "ultrascale",
    "lattice", "ecp", "icestick", "tsmc", "umc", "globalfoundries",
    "samsung", "smic", "sky130", "gf180",
    "platform", "target", "device", "technology", "process",
    "fpga", "asic", "stdcell", "synthesis", "fitter",
})


def _span_of(m: "re.Match", group: int = 0) -> Tuple[int, int]:
    """Column span of `m.group(group).strip()` inside the line it matched.

    Every parse helper below reports its evidence as `m.group(0).strip()`.
    `.strip()` moves the text but not the offsets, so the offsets have to be
    corrected by the amount that was stripped -- otherwise the recorded span
    would not slice back to the recorded text, and a span that does not
    reproduce its own text is worse than no span at all.

    Half-open, 0-indexed: `line[col_start:col_end] == text`, always.
    """
    text = m.group(group)
    lead = len(text) - len(text.lstrip())
    start = m.start(group) + lead
    return start, start + len(text.strip())


def _normalise_value(metric: str, raw_value: str,
                     unit: Optional[str]) -> Optional[object]:
    """Convert raw value+unit into the canonical metric value."""
    try:
        f = float(raw_value)
    except ValueError:
        return None
    u = (unit or "").lower()
    if metric == "fmax_mhz":
        if u.startswith("ghz"):
            return f * 1000.0
        if u.startswith("khz"):
            return f / 1000.0
        return f  # default MHz
    if metric == "kcells" and u.startswith("kgates"):
        return f
    if metric in ("luts", "regs", "alms", "les", "slices",
                  "rams", "dsps"):
        return int(f) if f.is_integer() else f
    return f


def _parse_inline_line(line: str) -> List[Dict[str, object]]:
    """Find every inline `<metric>: <value>` hit on a single line.

    Returns a list of dicts ``{metric, value, raw}``.
    """
    out: List[Dict[str, object]] = []
    for m in _INLINE_RE.finditer(line):
        token = m.group("metric").lower()
        metric = _TOKEN_TO_METRIC.get(token)
        if metric is None:
            continue
        value = _normalise_value(metric, m.group("value"), m.group("unit"))
        if value is None:
            continue
        c0, c1 = _span_of(m)
        out.append({
            "metric":      metric,
            "value":       value,
            "raw":         m.group(0).strip(),
            "col_start":   c0,
            "col_end":     c1,
        })
    return out


def _parse_number_first_line(line: str) -> Optional[Dict[str, object]]:
    """v1.6.119 (#45) — match number-first bullet form like
    ``- 2624 ALMs`` / ``- 8 kCells`` / ``96 MHz``. Returns a single
    dict ``{metric, value, raw}`` or None if no metric was matched.

    Optional SI prefix (k / M / G) between value and metric scales
    the numeric value. ``GHz`` metric scales by 1000 to land in the
    canonical fmax_mhz unit.
    """
    m = _NUMBER_FIRST_RE.match(line)
    if not m:
        return None
    metric_token = m.group("metric").lower()
    canonical = _NUMBER_FIRST_METRIC_MAP.get(metric_token)
    if canonical is None:
        return None
    try:
        value: float = float(m.group("value"))
    except ValueError:
        return None
    si = (m.group("si") or "").lower()
    if si == "k":
        value *= 1e3
    elif si == "m":
        value *= 1e6
    elif si == "g":
        value *= 1e9
    if metric_token == "ghz":
        value *= 1000.0
    # Integer counters return as int when whole; floats otherwise.
    c0, c1 = _span_of(m)
    if canonical in ("luts", "regs", "alms", "les", "slices",
                     "rams", "dsps", "cycles") and value.is_integer():
        return {
            "metric": canonical,
            "value":  int(value),
            "raw":    m.group(0).strip(),
            "col_start": c0,
            "col_end":   c1,
        }
    return {
        "metric": canonical,
        "value":  value,
        "raw":    m.group(0).strip(),
        "col_start": c0,
        "col_end":   c1,
    }


def _parse_area_line(line: str) -> Optional[Dict[str, object]]:
    """v1.6.176 (#74) — match ASIC silicon-area bullet keys
    (``- Area: 14200 um2`` / ``- Aera: 520 x 520 um`` /
    ``- Die size: 0.142 mm2``).

    Returns a dict ``{area_um2, die_size_um?, raw}`` or None if the
    line is not an area line. Unit conversions:

      * ``um2`` / ``µm2`` / ``um^2`` / ``µm^2`` → scalar area_um2.
      * ``mm2`` → scalar area_um2 (value × 1e6).
      * Linear unit (``um`` / ``µm`` / ``mm``) requires the
        ``W x H`` form; emits ``die_size_um = '<W>x<H>'`` with
        both numbers converted to micron (mm → um × 1e3) AND a
        derived ``area_um2`` = W * H.

    chip-AGNOSTIC: pure ASIC-datasheet vocabulary.
    """
    m = _RE_AREA_KV.match(line)
    if not m:
        return None
    raw = m.group(0).strip()
    value_str = m.group("value").strip()
    unit_raw = m.group("unit").lower()
    # Normalise unit token (strip Unicode µ and `^`).
    unit = unit_raw.replace("µ", "u").replace("^", "")
    # Side-length-pair form?
    pair_match = re.search(
        r"([\d.]+)\s*[x×]\s*([\d.]+)", value_str)
    if pair_match:
        try:
            w = float(pair_match.group(1))
            h = float(pair_match.group(2))
        except ValueError:
            return None
        # Linear unit required for the pair form (`um` / `mm`).
        if unit == "mm":
            w *= 1000.0
            h *= 1000.0
            unit_norm = "um"
        elif unit == "um":
            unit_norm = "um"
        else:
            # Square unit with `W x H` is malformed; skip.
            return None
        area_um2 = w * h
        # Stringify W / H without trailing .0 noise.
        ws = str(int(w)) if w.is_integer() else str(w)
        hs = str(int(h)) if h.is_integer() else str(h)
        _c0, _c1 = _span_of(m)
        return {
            "area_um2":     int(area_um2) if area_um2.is_integer()
                             else area_um2,
            "die_size_um":  f"{ws}x{hs}",
            "raw":          raw,
            "col_start":    _c0,
            "col_end":      _c1,
        }
    # Scalar form.
    try:
        v = float(value_str)
    except ValueError:
        return None
    if unit in ("um2", "um2".replace("µ", "u")):
        area_um2 = v
    elif unit == "mm2":
        area_um2 = v * 1e6
    else:
        # Linear unit without `W x H` is ambiguous; skip.
        return None
    _c0, _c1 = _span_of(m)
    return {
        "area_um2": int(area_um2) if area_um2.is_integer() else area_um2,
        "raw":      raw,
        "col_start": _c0,
        "col_end":   _c1,
    }


def _parse_sub_block_line(line: str) -> Optional[Dict[str, object]]:
    """v1.6.139 (#53 Defect D) — match per-submodule resource counts
    like ``- aes_sbox: 160 ALUTs`` / ``- mixer: 22 ALMs``. Returns a
    single dict ``{name, canonical, value, raw}`` or None.

    The name is the identifier on the left of the colon; the unit
    determines which canonical sub-block count key (alut_count /
    alm_count / lut_count / ff_count / slice_count / cell_count /
    kcell_count / le_count) it maps to.
    """
    m = _SUB_BLOCK_RE.match(line)
    if not m:
        return None
    name = m.group("name").strip()
    if name.lower() in _SUB_BLOCK_NAME_DENY:
        return None
    unit_token = m.group("unit").lower()
    canonical = _SUB_BLOCK_UNIT_MAP.get(unit_token)
    if canonical is None:
        return None
    try:
        value: float = float(m.group("value"))
    except ValueError:
        return None
    c0, c1 = _span_of(m)
    if canonical.endswith("_count") and value.is_integer():
        return {
            "name":      name,
            "canonical": canonical,
            "value":     int(value),
            "raw":       m.group(0).strip(),
            "col_start": c0,
            "col_end":   c1,
        }
    return {
        "name":      name,
        "canonical": canonical,
        "value":     value,
        "raw":       m.group(0).strip(),
        "col_start": c0,
        "col_end":   c1,
    }


def _split_table_row_spans(
    line: str,
) -> Optional[List[Tuple[str, int, int]]]:
    """`| a | b |` -> [(text, col_start, col_end)], or None if not a row.

    One parser, two views: `_split_table_row` is this function with the
    offsets dropped. Splitting the row twice in two places is how the text a
    value came from and the span that is supposed to locate it drift apart.
    """
    m = _TABLE_ROW_RE.match(line)
    if not m:
        return None
    inner = m.group(1)
    base = m.start(1)
    out: List[Tuple[str, int, int]] = []
    off = 0
    for seg in inner.split("|"):
        lead = len(seg) - len(seg.lstrip())
        text = seg.strip()
        c0 = base + off + lead
        out.append((text, c0, c0 + len(text)))
        off += len(seg) + 1  # +1 for the `|` consumed by split
    return out


def _split_table_row(line: str) -> Optional[List[str]]:
    """Split `| a | b | c |` into ['a', 'b', 'c'] or None if not a row."""
    spans = _split_table_row_spans(line)
    if spans is None:
        return None
    return [t for t, _c0, _c1 in spans]


def _is_metric_header_cell(cell: str) -> Optional[str]:
    """If the cell text is a known PPA metric token (possibly with
    a unit suffix like `Fmax (MHz)`), return the canonical metric
    key. Otherwise None.
    """
    text = cell.strip().lower()
    text = re.sub(r"\s*\(.*?\)\s*$", "", text)  # drop "(MHz)" etc.
    text = text.replace("-", "_").replace(" ", "_")
    return _TOKEN_TO_METRIC.get(text)


def extract_implementation_results_from_readme(
    readme_text: Optional[str],
    _with_spans: bool = False,
) -> List[dict]:
    """Return per-platform PPA dicts found in the README.

    `_with_spans=True` additionally returns the `_spans` provenance sidecar
    that the hint layer needs. The default result is byte-for-byte the
    pre-v1.11 one: there is ONE parse, and the hint view and the legacy view
    are two views of it, so they cannot disagree about what was found. The
    legacy consumer (`phase1_doc_one_shot_runner`) copies picker fields
    WHOLESALE since v1.6.183, so a `_spans` key that leaked through would
    land in `L1.implementation_results` -- hence the strip below, and hence
    the test that pins it.

    The body deliberately stays under the PUBLIC name rather than moving to a
    private helper: `prose_polarity_baseline.json` grandfathers this
    function, and relocating the body would present it to that gate as a new
    unlisted prose extractor. Measured: the offender count went 3 -> 4 with
    the body under a private name, and back to 3 with it here.

    Each dict:

        {
            "platform":      "Cyclone V" | "TSMC 180nm" | None,
            "metrics":       {luts, regs, fmax_mhz, kcells, ...},
            "evidence_line": L,
            "source_form":   "markdown_table" | "inline_kv",
        }

    Empty list when no PPA evidence found. Chip-AGNOSTIC.
    """
    if not readme_text:
        return []

    lines = readme_text.split("\n")
    results: List[dict] = []
    platform_hint: Optional[str] = None

    # Two-pass scan: first pass detects markdown PPA tables (header
    # row of metric tokens + ≥1 data row); second pass picks up
    # inline `<metric>: <value>` lines outside of tables.
    consumed_lines: set = set()

    # ---------------------------------------------------------
    # Pass 1 — markdown tables.
    # ---------------------------------------------------------
    i = 0
    while i < len(lines):
        cell_spans = _split_table_row_spans(lines[i])
        cells = (None if cell_spans is None
                 else [t for t, _a, _b in cell_spans])
        if cells and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
            # This is the header row of a markdown table.
            header_cells = cells
            metric_cols: Dict[int, str] = {}
            for col_idx, cell in enumerate(header_cells):
                m = _is_metric_header_cell(cell)
                if m is not None:
                    metric_cols[col_idx] = m
            if not metric_cols:
                i += 1
                continue
            # Walk data rows after the separator.
            j = i + 2
            while j < len(lines):
                data_spans = _split_table_row_spans(lines[j])
                data_cells = (None if data_spans is None
                              else [t for t, _a, _b in data_spans])
                if not data_cells or _TABLE_SEP_RE.match(lines[j]):
                    break
                # First non-metric cell is the platform.
                platform = None
                for col_idx, cell in enumerate(data_cells):
                    if col_idx not in metric_cols:
                        if cell:
                            platform = cell
                            break
                metrics: Dict[str, object] = {}
                spans: Dict[str, dict] = {}
                for col_idx, metric_key in metric_cols.items():
                    if col_idx >= len(data_cells):
                        continue
                    cell = data_cells[col_idx]
                    nm = re.match(
                        r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z][\w/]{0,8})?",
                        cell,
                    )
                    if not nm:
                        continue
                    value = _normalise_value(metric_key, nm.group(1),
                                              nm.group(2))
                    if value is None:
                        continue
                    metrics[metric_key] = value
                    _t, _c0, _c1 = data_spans[col_idx]
                    spans[metric_key] = {
                        "line": j + 1, "col_start": _c0,
                        "col_end": _c1, "text": _t,
                    }
                if metrics:
                    results.append({
                        "platform":      platform,
                        "metrics":       metrics,
                        "evidence_line": j + 1,  # 1-indexed
                        "source_form":   "markdown_table",
                        "_spans":        spans,
                    })
                consumed_lines.add(j)
                j += 1
            i = j
            continue
        i += 1

    # ---------------------------------------------------------
    # Pass 2 — inline metric lines outside of tables.
    # Group consecutive inline-bearing lines under the most recent
    # heading-style line (`## Cyclone V` / `Platform: TSMC 180nm`).
    # ---------------------------------------------------------
    pending_metrics: Dict[str, object] = {}
    pending_spans: Dict[str, dict] = {}
    pending_sub_blocks: Dict[str, Dict[str, object]] = {}
    pending_first_line: Optional[int] = None
    # v1.6.141 (#55) — last heading-derived platform, kept so each
    # ``- <variant>`` sub-variant inherits ``<parent> / <variant>``.
    parent_platform: Optional[str] = None
    # v1.6.175 (#73) — vendor hint for the next-flushed entry. Set
    # when a `**Family**` bold sub-header is seen under a markdown
    # `### Vendor ###` heading; cleared on next heading.
    vendor_hint: Optional[str] = None
    # v1.6.175 (#73) — extraction strategy tag for the next-flushed
    # entry. Default None (legacy `source_form=inline_kv`); set to
    # `readme_vendor_bold_device_triplet` when the three-level form
    # was used to derive platform.
    extraction_strategy_hint: Optional[str] = None

    def _flush():
        if pending_metrics and pending_first_line is not None:
            entry: Dict[str, object] = {
                "platform":      platform_hint,
                "metrics":       dict(pending_metrics),
                "evidence_line": pending_first_line,
                "source_form":   "inline_kv",
            }
            if vendor_hint:
                entry["vendor"] = vendor_hint
            if extraction_strategy_hint:
                entry["extraction_strategy"] = extraction_strategy_hint
            if pending_sub_blocks:
                entry["sub_blocks"] = [
                    {"name": n, **{k: v for k, v in counts.items()
                                   if not k.startswith("_")}}
                    for n, counts in pending_sub_blocks.items()
                ]
            entry["_spans"] = dict(pending_spans)
            results.append(entry)

    for line_num, line in enumerate(lines, start=1):
        if (line_num - 1) in consumed_lines:
            continue
        h = _HEADING_RE.match(line)
        # v1.6.175 (#73) — when a bold sub-platform context is
        # active, a subsequent bulleted H2 prose-heading (e.g.
        # `- Device: EP4CE6F17C6`) is a per-entry ATTRIBUTE, not a
        # platform reset. Skip the H2 promotion and let the bullet
        # fall through to the metric/attribute parsers below. This
        # is gated on (a) bold-sub context active and (b) leading
        # bullet — markdown `#` headings (h1) still always reset.
        if (h and extraction_strategy_hint and h.group("h1") is None
                and re.match(r"^\s*[\-*+•·]\s+", line)):
            h = None
        if h:
            # Flush pending block under previous platform_hint.
            _flush()
            pending_metrics = {}
            pending_spans = {}
            pending_sub_blocks = {}
            pending_first_line = None
            platform_hint = (h.group("h1") or h.group("h2")
                              or h.group("h3") or "").strip()
            # v1.6.175 (#73) — defensive trailing-`#` strip in case
            # the heading regex still left them (also covers H2/H3
            # alt branches which don't have the `\s+#+` swallow).
            platform_hint = re.sub(r"\s*#+\s*$", "", platform_hint)
            parent_platform = platform_hint
            # Reset vendor / strategy hints on a fresh heading.
            vendor_hint = None
            extraction_strategy_hint = None
            continue
        # v1.6.175 (#73) — bold-emphasised sub-platform header
        # (`**Cyclone IV E**` / `***IGLOO2***`). Only treat as a
        # sub-platform when a markdown heading already established
        # a parent vendor — otherwise random bold text in body prose
        # would silently rewrite platform.
        bsh = _RE_PLATFORM_BOLD_SUBHEADER.match(line)
        if bsh and parent_platform:
            family = bsh.group("family").strip()
            # Filter generic foundry / vendor words so we don't
            # promote a bold reiteration of the vendor name itself.
            if family.lower() not in _SUB_BLOCK_NAME_DENY:
                _flush()
                pending_metrics = {}
                pending_spans = {}
                pending_sub_blocks = {}
                pending_first_line = None
                platform_hint = family
                vendor_hint = parent_platform
                extraction_strategy_hint = (
                    "readme_vendor_bold_device_triplet")
                continue
        # v1.6.141 (#55) — bullet-form sub-variant boundary.
        # v1.6.183 (#73 v2) — gate this branch when bold-sub-header
        # context is active. Real hash-core READMEs put the
        # device-code on its own bullet line (`- EP4CE6F17C6`)
        # under a `**Cyclone IV E**` bold sub-header; pre-v1.6.183
        # the bullet-subvariant path fired and OVERWROTE the bold
        # platform_hint back to `<parent>/<device_code>`, defeating
        # the v1.6.175 fix. When the bold-sub set extraction
        # strategy, treat bullet identifiers as device attributes
        # (folded into a `device` metric below) instead of
        # platform-reset boundaries.
        sv = _BULLET_SUBVARIANT_RE.match(line)
        # v1.6.183 (#73 v2) — when bold-sub context is active and
        # the letter-led `_BULLET_SUBVARIANT_RE` did not match,
        # also try a digit-allowed form so device codes like
        # `5CGXFC7D6F31C7` (Cyclone V) get captured as a `device`
        # metric. Outside bold context this would over-capture
        # numeric noise (`- 1234`), so the relaxed form is gated
        # on `extraction_strategy_hint`.
        if (not sv) and extraction_strategy_hint:
            sv = _RE_BULLET_DEVICE_CODE_ANY_LEAD.match(line)
        if sv and not extraction_strategy_hint:
            variant_name = sv.group("name").strip()
            # Filter generic vendor / foundry words — they belong in
            # `_HEADING_RE` territory, not as anonymous variants. Re-
            # use the sub-block deny list since the vocabulary is the
            # same family.
            if variant_name.lower() not in _SUB_BLOCK_NAME_DENY:
                _flush()
                pending_metrics = {}
                pending_spans = {}
                pending_sub_blocks = {}
                pending_first_line = None
                if parent_platform:
                    platform_hint = (
                        f"{parent_platform} / {variant_name}")
                else:
                    platform_hint = variant_name
                continue
        elif sv and extraction_strategy_hint:
            # Capture the device-code under the bold sub-header.
            variant_name = sv.group("name").strip()
            if variant_name.lower() not in _SUB_BLOCK_NAME_DENY:
                if pending_first_line is None:
                    pending_first_line = line_num
                pending_metrics.setdefault("device", variant_name)
                _c0, _c1 = _span_of(sv)
                pending_spans.setdefault("device", {
                    "line": line_num, "col_start": _c0,
                    "col_end": _c1, "text": sv.group(0).strip(),
                })
                continue
        hits = _parse_inline_line(line)
        if not hits:
            # v1.6.119 (#45) — fall through to number-first form.
            nf = _parse_number_first_line(line)
            if nf is not None:
                hits = [nf]
        if not hits:
            # v1.6.176 (#74) — fall through to area-kv form.
            ar = _parse_area_line(line)
            if ar is not None:
                hits = [{"metric": "area_um2",
                          "value":  ar["area_um2"],
                          "raw":    ar["raw"],
                          "col_start": ar["col_start"],
                          "col_end":   ar["col_end"]}]
                if "die_size_um" in ar:
                    hits.append({"metric": "die_size_um",
                                  "value":  ar["die_size_um"],
                                  "raw":    ar["raw"],
                                  "col_start": ar["col_start"],
                                  "col_end":   ar["col_end"]})
                # Tag this block's extraction strategy when no
                # stronger tag (e.g. bold-sub) was set first.
                if extraction_strategy_hint is None:
                    extraction_strategy_hint = "readme_area_metric_kv"
        if not hits:
            # v1.6.139 (#53 Defect D) — sub-block fallback.
            # Only emit when we already have a platform-level metric
            # in the current block; otherwise the line is ambient
            # prose unrelated to PPA.
            if pending_first_line is not None:
                sb = _parse_sub_block_line(line)
                if sb is not None:
                    bucket = pending_sub_blocks.setdefault(
                        sb["name"], {})
                    if sb["canonical"] not in bucket:
                        bucket[sb["canonical"]] = sb["value"]
                        pending_spans.setdefault(
                            "sub_blocks.%s.%s" % (sb["name"],
                                                  sb["canonical"]),
                            {"line": line_num,
                             "col_start": sb["col_start"],
                             "col_end": sb["col_end"],
                             "text": sb["raw"]})
            continue
        if pending_first_line is None:
            pending_first_line = line_num
        for hit in hits:
            if hit["metric"] in pending_metrics:
                continue
            pending_metrics[hit["metric"]] = hit["value"]
            pending_spans[hit["metric"]] = {
                "line": line_num,
                "col_start": hit["col_start"],
                "col_end": hit["col_end"],
                "text": hit["raw"],
            }

    _flush()

    if _with_spans:
        return results
    return [
        {k: v for k, v in entry.items() if not k.startswith("_")}
        for entry in results
    ]


__all__ = [
    "extract_implementation_results_from_readme",
    "extract_hints",
    "reconcile",
    "harvest_authority_from_l_doc",
    "harvest_authority_from_sdc",
    "main",
    "SCHEMA",
    "AUTHORITY_HINT",
]


# ======================================================================
# HINTS ONLY — the layer that makes a README number safe to carry around
# ======================================================================
#
# WHY THIS LAYER EXISTS
#
# A number printed in somebody else's README is evidence that somebody else
# once measured something. It is not evidence about THIS implementation. It
# was produced by another tool, at another corner, very often on another
# technology, and nothing in the file says which. Treated as a value it is a
# measurement; treated honestly it is a HINT, and the difference is the whole
# of this section.
#
# Two rules follow, and both are mechanical rather than advisory:
#
#   1. Every emitted value carries the SOURCE SPAN it was read from and a hash
#      of that span. `line[col_start:col_end] == text` always holds, so a
#      reader can go to the file and see the same characters the parser saw.
#      A provenance field that cannot be checked is decoration.
#
#   2. A hint NEVER overrides an L-doc or an SDC. When an authoritative value
#      exists for the same metric, this program compares and REPORTS; the
#      authority wins by construction -- `resolution` is a constant, not a
#      decision. Where the two are not shown to be comparable it says
#      UNDETERMINED rather than picking, because per PPA_INTERFACES.md §2 two
#      numbers are comparable only if their scope matches, and a README
#      almost never states one.
#
# EXIT CODES (PPA_INTERFACES.md §1)
#
#   0  the README was read; hints (possibly zero) emitted; no conflict
#   1  CONFLICT -- a hint contradicts an authoritative value at a MATCHED
#      scope. This is a finding about the design's own documents.
#   2  UNDETERMINED / NOT CHECKED -- the README could not be read, or
#      `--require-comparable` was asked for and a comparison could not be made
#   3  BAD INVOCATION
#
# "I could not read it" and "I read it and it was empty" must never produce
# the same verdict, so rc=0 always prints the file it read and that file's
# digest, and rc=2 always prints a `[CANNOT CHECK]` marker on stderr.

SCHEMA = "vibeic.ppa.readme_hint.v1"

#: How this program names its own output authority level. A consumer that sees
#: anything other than `HINT` here is not reading this program's output.
AUTHORITY_HINT = "HINT"

#: Authoritative sources, strongest first. A hint is not in this list and can
#: never be added to it.
AUTHORITY_ORDER = ("SDC", "L_DOC")

#: L-doc key names that carry an authoritative value for a canonical metric.
#: Chip-AGNOSTIC: these are flow vocabulary, not any IC's fields.
_AUTHORITY_KEY_ALIASES: Dict[str, str] = {
    "fmax_mhz": "fmax_mhz",
    "f_max_mhz": "fmax_mhz",
    "target_fmax_mhz": "fmax_mhz",
    "clock_frequency_mhz": "fmax_mhz",
    "frequency_mhz": "fmax_mhz",
    "clock_mhz": "fmax_mhz",
    "area_um2": "area_um2",
    "die_area_um2": "area_um2",
    "core_area_um2": "area_um2",
    "die_size_um": "die_size_um",
    "luts": "luts",
    "regs": "regs",
    "alms": "alms",
    "les": "les",
    "slices": "slices",
    "kcells": "kcells",
    "rams": "rams",
    "dsps": "dsps",
    "total_cells": "total_cells",
    "combinational_cells": "combinational_cells",
    "noncombinational_cells": "noncombinational_cells",
}

#: `create_clock ... -period <p>` — the one SDC construct that pins a
#: frequency. `-name` is optional and may be quoted or braced.
_SDC_CREATE_CLOCK_RE = re.compile(
    r"^\s*create_clock\b(?P<args>.*)$", re.MULTILINE)
_SDC_PERIOD_RE = re.compile(r"-period\s+(?P<p>[0-9]*\.?[0-9]+)")
_SDC_NAME_RE = re.compile(r"-name\s+(?P<n>\{[^}]*\}|\"[^\"]*\"|\S+)")

#: SDC time units expressed in nanoseconds.
_SDC_TIME_UNIT_NS: Dict[str, float] = {
    "ns": 1.0, "ps": 1e-3, "us": 1e3, "s": 1e9,
}


def _file_sha256(raw: bytes) -> str:
    """`sha256:<hex>` of the literal bytes on disk.

    Deliberately NOT `canonical_json.digest_of`: this is the digest of an
    artefact, not of a document we serialized, so it must be the number
    `sha256sum <file>` prints. A provenance hash a human cannot reproduce with
    a standard tool is a hash nobody checks. Structured records built by this
    program go through `canonical_json` -- see `_span_digest`.
    """
    import hashlib
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _span_digest(span: dict) -> str:
    """Identity of a source span, via the one serializer (§3)."""
    return _digest_of(span)


def _norm_platform(text: Optional[str]) -> Optional[str]:
    """Fold a platform label to the form scope-matching compares.

    Case, runs of whitespace and surrounding punctuation are presentation.
    Anything beyond that is content and is left alone -- this is a comparison
    key, not a normaliser that gets to decide two platforms are the same.
    """
    if text is None:
        return None
    t = re.sub(r"\s+", " ", str(text)).strip().strip("*#`_-").strip()
    return t.lower() or None


def extract_hints(readme_text: Optional[str],
                  readme_path: Optional[str] = None,
                  readme_sha256: Optional[str] = None) -> Dict[str, Any]:
    """Build the `vibeic.ppa.readme_hint.v1` document for one README.

    Every hint is one (platform, metric) pair with the span it came from. The
    document says `authoritative: false` in its own body so that a consumer
    which never read this docstring still cannot mistake it for a measurement.
    """
    entries = extract_implementation_results_from_readme(
        readme_text, _with_spans=True)
    hints: List[Dict[str, Any]] = []
    for entry in entries:
        spans = entry.get("_spans") or {}
        platform = entry.get("platform")
        for metric, value in sorted((entry.get("metrics") or {}).items()):
            span = spans.get(metric)
            hint: Dict[str, Any] = {
                "metric": metric,
                "value": value,
                "platform": platform,
                "platform_key": _norm_platform(platform),
                "authority": AUTHORITY_HINT,
                "authoritative": False,
                "source_form": entry.get("source_form"),
            }
            if entry.get("vendor"):
                hint["vendor"] = entry["vendor"]
            if entry.get("extraction_strategy"):
                hint["extraction_strategy"] = entry["extraction_strategy"]
            if span is None:
                # Never invent one. A hint whose span could not be recorded
                # says so and is still emitted -- dropping it would turn a
                # provenance gap into a silently smaller result set.
                hint["span"] = None
                hint["span_sha256"] = None
                hint["span_status"] = "NO_SPAN_RECORDED"
            else:
                hint["span"] = dict(span)
                hint["span_sha256"] = _span_digest(span)
                hint["span_status"] = "RECORDED"
            hints.append(hint)
        for name_key, span in sorted(spans.items()):
            if not name_key.startswith("sub_blocks."):
                continue
            _, block, canonical = name_key.split(".", 2)
            hints.append({
                "metric": canonical,
                "value": None,
                "platform": platform,
                "platform_key": _norm_platform(platform),
                "sub_block": block,
                "authority": AUTHORITY_HINT,
                "authoritative": False,
                "source_form": entry.get("source_form"),
                "span": dict(span),
                "span_sha256": _span_digest(span),
                "span_status": "RECORDED",
            })
    doc: Dict[str, Any] = {
        "schema": SCHEMA,
        "authority": AUTHORITY_HINT,
        "authoritative": False,
        "read": readme_text is not None,
        "source": {
            "path": readme_path,
            "sha256": readme_sha256,
            "parser": "readme_ppa_extractor.py",
        },
        "hints": hints,
        "conflicts": [],
        "agreements": [],
        "undetermined": [],
        "verdict": "OK",
    }
    return doc


def harvest_authority_from_l_doc(obj: Any, path_label: str) -> List[dict]:
    """Walk an L-doc and collect every authoritative PPA value it declares.

    A recursive key walk rather than a fixed set of pointers: the L-docs are
    27 layers with per-IC shape, and a hardcoded pointer list would silently
    harvest nothing on the first document that nests differently -- which is
    the failure where an unmeasured thing reads as a measured zero.
    """
    out: List[dict] = []

    def walk(node: Any, pointer: str, platform: Optional[str]) -> None:
        if isinstance(node, dict):
            here = node.get("platform") or node.get("target_platform")
            plat = here if isinstance(here, str) else platform
            for k, v in node.items():
                canonical = _AUTHORITY_KEY_ALIASES.get(str(k).lower())
                if canonical is not None and isinstance(
                        v, (int, float, str)) and not isinstance(v, bool):
                    out.append({
                        "metric": canonical,
                        "value": v,
                        "kind": "L_DOC",
                        "platform": plat,
                        "platform_key": _norm_platform(plat),
                        "source": {"path": path_label,
                                   "pointer": pointer + "/" + str(k)},
                    })
                walk(v, pointer + "/" + str(k), plat)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, pointer + "/" + str(i), platform)

    walk(obj, "", None)
    return out


def harvest_authority_from_sdc(text: str, path_label: str,
                               time_unit: str = "ns") -> List[dict]:
    """Turn every `create_clock -period` into an authoritative fmax.

    The period's unit is NOT in the SDC file -- it is the timing library's
    unit -- so it is an input here and it is recorded in the output next to
    the number. An assumed unit that is not written down is how a 1000x error
    becomes a confident comparison.
    """
    scale = _SDC_TIME_UNIT_NS.get(time_unit)
    if scale is None:
        raise ValueError("unsupported SDC time unit: %r" % (time_unit,))
    out: List[dict] = []
    for m in _SDC_CREATE_CLOCK_RE.finditer(text):
        args = m.group("args")
        pm = _SDC_PERIOD_RE.search(args)
        if not pm:
            continue
        try:
            period = float(pm.group("p"))
        except ValueError:
            continue
        if period <= 0:
            continue
        nm = _SDC_NAME_RE.search(args)
        clock = (nm.group("n").strip("{}\"") if nm else None)
        out.append({
            "metric": "fmax_mhz",
            "value": 1000.0 / (period * scale),
            "kind": "SDC",
            "platform": None,
            "platform_key": None,
            "clock": clock,
            "derived": {
                "formula": "fmax_mhz = 1000 / (period * time_unit_ns)",
                "period": period,
                "time_unit": time_unit,
            },
            "source": {"path": path_label,
                       "pointer": "create_clock -period %s" % pm.group("p")},
        })
    return out


def _values_differ(a: Any, b: Any, tolerance_pct: float) -> Optional[bool]:
    """True/False when both are numeric or both are strings; None otherwise.

    None means "these two things are not the same KIND of value", which is an
    UNDETERMINED comparison and never a conflict -- comparing a `520x520`
    string against a float is a category error, not a finding about silicon.
    """
    num = (int, float)
    if isinstance(a, bool) or isinstance(b, bool):
        return None
    if isinstance(a, num) and isinstance(b, num):
        if float(a) == float(b):
            return False
        if tolerance_pct > 0 and b != 0:
            return abs(float(a) - float(b)) / abs(float(b)) * 100.0 \
                > tolerance_pct
        return True
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().lower() != b.strip().lower()
    return None


def reconcile(doc: Dict[str, Any], authority: List[dict],
              tolerance_pct: float = 0.0,
              assume_scope_match: bool = False) -> Dict[str, Any]:
    """Compare every hint against every authoritative value for that metric.

    The authority wins unconditionally. There is no branch in this function
    where a hint replaces an authoritative value, which is the point: the
    guarantee is structural, not a rule somebody has to remember.
    """
    conflicts: List[dict] = []
    agreements: List[dict] = []
    undetermined: List[dict] = []
    by_metric: Dict[str, List[dict]] = {}
    for rec in authority:
        by_metric.setdefault(rec["metric"], []).append(rec)

    for hint in doc.get("hints", []):
        if hint.get("value") is None:
            continue
        for rec in by_metric.get(hint["metric"], []):
            pair = {
                "metric": hint["metric"],
                "hint_value": hint["value"],
                "hint_platform": hint.get("platform"),
                "hint_span": hint.get("span"),
                "hint_span_sha256": hint.get("span_sha256"),
                "authority_kind": rec["kind"],
                "authority_value": rec["value"],
                "authority_platform": rec.get("platform"),
                "authority_source": rec.get("source"),
                "resolution": "AUTHORITY_WINS",
                "hint_ignored": True,
            }
            if rec.get("derived"):
                pair["authority_derived"] = rec["derived"]
            comparable = (
                assume_scope_match
                or (hint.get("platform_key") is not None
                    and hint.get("platform_key") == rec.get("platform_key")))
            if not comparable:
                pair["reason"] = "SCOPE_NOT_SHOWN_TO_MATCH"
                pair["resolution"] = "UNDETERMINED"
                undetermined.append(pair)
                continue
            differ = _values_differ(hint["value"], rec["value"],
                                    tolerance_pct)
            if differ is None:
                pair["reason"] = "VALUE_KINDS_NOT_COMPARABLE"
                pair["resolution"] = "UNDETERMINED"
                undetermined.append(pair)
            elif differ:
                pair["reason"] = "VALUE_MISMATCH"
                conflicts.append(pair)
            else:
                pair["reason"] = "VALUE_MATCH"
                pair["resolution"] = "AGREE"
                agreements.append(pair)

    doc["conflicts"] = conflicts
    doc["agreements"] = agreements
    doc["undetermined"] = undetermined
    doc["verdict"] = "CONFLICT" if conflicts else "OK"
    return doc


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
#
# `skills/ppa-predict/SKILL.md` has declared this invocation as a MANDATORY
# DETERMINISTIC PREFLIGHT since v1.6.118:
#
#     python3 programs/readme_ppa_extractor.py \
#         --rtl-dir <rtl> --readme <README.md> --json /tmp/ppa_hints.json
#
# and told the agent to use the JSON as the FLOOR of any estimate it states.
# Until this section existed the file had no CLI at all: the command parsed
# nothing, wrote nothing, printed nothing and exited 0. The preflight that was
# supposed to anchor the estimate returned success having read no file, and
# the agent then stated a number with no floor. That is the shape this repo
# pays for most often -- an unmeasured thing reading as a measured zero -- so
# the rc=2 path below is the load-bearing one, not the happy path.


class _Rc3ArgumentParser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error. Here 2 means UNDETERMINED and a
    usage error is a BAD INVOCATION, which is 3. Same text, right code."""

    def error(self, message: str):  # pragma: no cover - exercised via CLI
        self.print_usage(_sys.stderr)
        _sys.stderr.write("[REFUSE] readme_ppa_extractor: %s\n" % message)
        raise SystemExit(3)


def _build_parser() -> argparse.ArgumentParser:
    ap = _Rc3ArgumentParser(
        prog="readme_ppa_extractor",
        description="Extract PPA HINTS from a README. Hints never override "
                    "an L-doc or an SDC; where they conflict this reports "
                    "the conflict and the authority wins.")
    ap.add_argument("--readme", required=True,
                    help="README / spec markdown to read (required)")
    ap.add_argument("--rtl-dir", default=None,
                    help="RTL directory. Recorded as run context only: this "
                         "program reads no RTL, and says so in the output "
                         "rather than implying it looked.")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the hint document here (atomic)")
    ap.add_argument("--l-doc", dest="l_docs", action="append", default=[],
                    help="authoritative L-doc JSON (repeatable)")
    ap.add_argument("--sdc", dest="sdcs", action="append", default=[],
                    help="authoritative SDC (repeatable)")
    ap.add_argument("--sdc-time-unit", default="ns",
                    choices=sorted(_SDC_TIME_UNIT_NS),
                    help="unit of the SDC -period number (default ns)")
    ap.add_argument("--tolerance-pct", type=float, default=0.0,
                    help="relative tolerance before a mismatch is a conflict")
    ap.add_argument("--assume-scope-match", action="store_true",
                    help="assert that the README's scope is this design's "
                         "scope. Without it a README number and an L-doc "
                         "number are UNDETERMINED, per PPA_INTERFACES.md §2.")
    ap.add_argument("--require-comparable", action="store_true",
                    help="exit 2 when any comparison could not be made")
    return ap


def _read_text_or_none(path: str) -> Tuple[Optional[bytes], Optional[str]]:
    """(bytes, error). Never conflates 'absent' with 'empty' -- b'' is a
    successful read of an empty file and returns (b'', None)."""
    p = _Path(path)
    if not p.exists():
        return None, "does not exist"
    if p.is_dir():
        return None, "is a directory"
    try:
        return p.read_bytes(), None
    except OSError as exc:
        return None, str(exc)


def _write_doc_or_refuse(path: str, text: str) -> Optional[int]:
    """Write the artefact, or return the rc to exit with.

    An unwritable `--json` path must never escape as an OSError: an uncaught
    exception exits 1, and 1 in this program means "a README number
    contradicts the SDC". A caller who named a path we cannot create gave a
    BAD INVOCATION, which is 3.
    """
    try:
        _atomic_write_text(path, text)
    except OSError as exc:
        _sys.stderr.write(
            "[REFUSE] readme_ppa_extractor: cannot write --json %s: %s\n"
            % (path, exc))
        return 3
    return None


def main(argv: Optional[List[str]] = None) -> int:
    import json as _json
    ap = _build_parser()
    args = ap.parse_args(argv)

    raw, err = _read_text_or_none(args.readme)
    if raw is None:
        _sys.stderr.write(
            "[CANNOT CHECK] readme_ppa_extractor: --readme %s: %s. "
            "No hints were produced; this is NOT a clean result.\n"
            % (args.readme, err))
        if args.json_out:
            _bad = _write_doc_or_refuse(args.json_out, _json.dumps({
                "schema": SCHEMA,
                "authority": AUTHORITY_HINT,
                "authoritative": False,
                "read": False,
                "source": {"path": args.readme, "sha256": None,
                           "parser": "readme_ppa_extractor.py"},
                "hints": [], "conflicts": [], "agreements": [],
                "undetermined": [],
                "verdict": "CANNOT_CHECK",
                "reason": "readme unreadable: %s" % err,
            }, indent=2, ensure_ascii=False) + "\n")
            if _bad is not None:
                return _bad
        return 2

    text = raw.decode("utf-8", errors="replace")
    doc = extract_hints(text, readme_path=args.readme,
                        readme_sha256=_file_sha256(raw))
    doc["inputs"] = {
        "rtl_dir": args.rtl_dir,
        "rtl_read": False,
        "l_docs": list(args.l_docs),
        "sdcs": list(args.sdcs),
        "tolerance_pct": args.tolerance_pct,
        "assume_scope_match": bool(args.assume_scope_match),
        "sdc_time_unit": args.sdc_time_unit,
    }

    authority: List[dict] = []
    for path in args.l_docs:
        blob, aerr = _read_text_or_none(path)
        if blob is None:
            _sys.stderr.write(
                "[CANNOT CHECK] readme_ppa_extractor: --l-doc %s: %s\n"
                % (path, aerr))
            return 2
        try:
            authority.extend(harvest_authority_from_l_doc(
                _json.loads(blob.decode("utf-8", errors="replace")), path))
        except ValueError as exc:
            _sys.stderr.write(
                "[CANNOT CHECK] readme_ppa_extractor: --l-doc %s is not "
                "JSON: %s\n" % (path, exc))
            return 2
    for path in args.sdcs:
        blob, aerr = _read_text_or_none(path)
        if blob is None:
            _sys.stderr.write(
                "[CANNOT CHECK] readme_ppa_extractor: --sdc %s: %s\n"
                % (path, aerr))
            return 2
        authority.extend(harvest_authority_from_sdc(
            blob.decode("utf-8", errors="replace"), path,
            args.sdc_time_unit))

    doc["authority_records"] = authority
    reconcile(doc, authority, tolerance_pct=args.tolerance_pct,
              assume_scope_match=args.assume_scope_match)
    doc["document_sha256"] = _digest_of(
        {k: v for k, v in doc.items() if k != "document_sha256"})

    if args.json_out:
        _bad = _write_doc_or_refuse(
            args.json_out, _json.dumps(doc, indent=2,
                                       ensure_ascii=False) + "\n")
        if _bad is not None:
            return _bad

    # stdout: the human summary. It always names the file it read and that
    # file's digest, so a zero-hint run can never be mistaken for a run that
    # never opened anything.
    print("readme_ppa_extractor: read %s (%s, %d bytes)"
          % (args.readme, doc["source"]["sha256"], len(raw)))
    print("  hints=%d  authority_records=%d  conflicts=%d  agreements=%d  "
          "undetermined=%d"
          % (len(doc["hints"]), len(authority), len(doc["conflicts"]),
             len(doc["agreements"]), len(doc["undetermined"])))
    print("  authority=HINT — every value above is a HINT and never "
          "overrides an L-doc or an SDC.")
    if args.rtl_dir is not None:
        print("  rtl_dir=%s (recorded as context; NO RTL was read)"
              % args.rtl_dir)
    if args.json_out:
        print("  json=%s" % args.json_out)

    for c in doc["conflicts"]:
        _sys.stderr.write(
            "[CONFLICT] %s: README hint %r (%s) contradicts %s %r from %s — "
            "%s wins, hint ignored.\n"
            % (c["metric"], c["hint_value"], c.get("hint_platform"),
               c["authority_kind"], c["authority_value"],
               (c.get("authority_source") or {}).get("path"),
               c["authority_kind"]))
    if doc["conflicts"]:
        return 1
    if args.require_comparable and doc["undetermined"]:
        _sys.stderr.write(
            "[CANNOT CHECK] readme_ppa_extractor: %d comparison(s) could "
            "not be made (--require-comparable).\n"
            % len(doc["undetermined"]))
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    # An uncaught exception exits 1, and 1 here is a claim about the design:
    # "a README number contradicts the SDC". An internal error is not that.
    # Measured 2026-08-21 elsewhere in this tree: two shipped gates refused
    # with a bare SystemExit("...") and reported a hard finding for a run
    # that never opened its input.
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as _exc:  # noqa: BLE001 - deliberate catch-all
        _sys.stderr.write(
            "[REFUSE] readme_ppa_extractor: internal error, no finding is "
            "claimed: %r\n" % (_exc,))
        raise SystemExit(3)
