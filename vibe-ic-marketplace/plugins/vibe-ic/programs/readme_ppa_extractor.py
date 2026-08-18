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

import re
from typing import Dict, List, Optional

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
        out.append({
            "metric":      metric,
            "value":       value,
            "raw":         m.group(0).strip(),
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
    if canonical in ("luts", "regs", "alms", "les", "slices",
                     "rams", "dsps", "cycles") and value.is_integer():
        return {
            "metric": canonical,
            "value":  int(value),
            "raw":    m.group(0).strip(),
        }
    return {
        "metric": canonical,
        "value":  value,
        "raw":    m.group(0).strip(),
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
        return {
            "area_um2":     int(area_um2) if area_um2.is_integer()
                             else area_um2,
            "die_size_um":  f"{ws}x{hs}",
            "raw":          raw,
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
    return {
        "area_um2": int(area_um2) if area_um2.is_integer() else area_um2,
        "raw":      raw,
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
    if canonical.endswith("_count") and value.is_integer():
        return {
            "name":      name,
            "canonical": canonical,
            "value":     int(value),
            "raw":       m.group(0).strip(),
        }
    return {
        "name":      name,
        "canonical": canonical,
        "value":     value,
        "raw":       m.group(0).strip(),
    }


def _split_table_row(line: str) -> Optional[List[str]]:
    """Split `| a | b | c |` into ['a', 'b', 'c'] or None if not a row."""
    m = _TABLE_ROW_RE.match(line)
    if not m:
        return None
    cells = [c.strip() for c in m.group(1).split("|")]
    return cells


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
) -> List[dict]:
    """Return per-platform PPA dicts found in the README.

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
        cells = _split_table_row(lines[i])
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
                data_cells = _split_table_row(lines[j])
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
                if metrics:
                    results.append({
                        "platform":      platform,
                        "metrics":       metrics,
                        "evidence_line": j + 1,  # 1-indexed
                        "source_form":   "markdown_table",
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
                    {"name": n, **counts}
                    for n, counts in pending_sub_blocks.items()
                ]
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
                          "raw":    ar["raw"]}]
                if "die_size_um" in ar:
                    hits.append({"metric": "die_size_um",
                                  "value":  ar["die_size_um"],
                                  "raw":    ar["raw"]})
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
                    bucket.setdefault(sb["canonical"], sb["value"])
            continue
        if pending_first_line is None:
            pending_first_line = line_num
        for hit in hits:
            pending_metrics.setdefault(hit["metric"], hit["value"])

    _flush()

    return results


__all__ = [
    "extract_implementation_results_from_readme",
]
