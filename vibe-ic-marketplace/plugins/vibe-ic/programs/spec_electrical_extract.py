#!/usr/bin/env python3
"""spec_electrical_extract.py — PROGRAM-FIRST structural extractor for stated
CLOCK-FREQUENCY + ELECTRICAL specs (chip-AGNOSTIC, §4.05 no-leak).

WHY THIS EXISTS
---------------
A design doc / datasheet / L-doc / CVDP prompt frequently pins the chip's
ELECTRICAL operating point EXPLICITLY: a clock rate ("the core runs at
100 MHz"), a supply rail ("from a 1.8 V supply"), a current budget ("drawing
5 mA"), an operating temperature range ("-40 to 125 °C"), an output slew rate
("2 V/ns"). These are testable, parameter-bearing requirements: the downstream
constraint / conformance / corner machinery must honor exactly those numbers
(an SDC clock period, a PVT corner, an IO drive setting). A FAILURE on one of
these is — per the spec-coverage doctrine — almost always one of OUR OWN
extraction gaps (a stated number we never read out), not an unfixable floor.

This program does the DETERMINISTIC, chip-AGNOSTIC, PROGRAM-FIRST half of that
job: given a prompt, it extracts the STRUCTURAL electrical skeleton — one
ChecklistItem per EXPLICITLY-stated number+unit electrical fact:

    kind="clock_frequency"  — a stated clock rate (N Hz/kHz/MHz/GHz + clock ctx)
    kind="supply_voltage"   — a stated supply/IO/core rail (N V/mV + supply ctx)
    kind="current_spec"     — a stated current draw  (N A/mA/uA/µA + current ctx)
    kind="temperature_range"— a stated operating temp range (LO to HI °C/C)
    kind="slew_rate"        — a stated slew rate ("slew rate" + N V/ns or V/us)

WHAT COUNTS (the §4.05 no-leak boundary)
  Each kind fires ONLY on a REAL number+unit PLUS its SPECIFIC qualifier:

  * clock_frequency: a number+freq-unit (N Hz / N kHz / N MHz / N GHz, decimals +
    underscores/commas allowed) AND a clock context word ("clock"/"clk"/
    "frequency"/"operating frequency"/"f_clk"/"runs at"). A BARE number with no
    clock/frequency context yields NOTHING. A baud rate is still emitted (it IS a
    stated rate) but the requirement notes "baud".
  * supply_voltage: a number+volt-unit (N V / N mV) AND a supply context
    ("supply"/"VDD"/"VDDIO"/"operating voltage"/"core voltage"/"rail"). A bare
    "1.2 V" with no supply context yields NOTHING (e.g. a Vref / threshold handled
    elsewhere) — supply context is mandatory.
  * current_spec: a number+current-unit (N mA / N uA / N A / N µA) AND a current
    context ("current"/"draw"/"consumption"/"Idd").
  * temperature_range: a stated RANGE ("-40 to 125 °C" / "-40°C to +85°C" /
    "0 to 70 C") AND a temperature/operating context. A lone temperature with no
    range yields NOTHING.
  * slew_rate: the phrase "slew rate" AND a number with V/ns or V/us.

  A vague "design a multiplier" — no number, no unit — yields `[]` (no
  fabrication). chip-AGNOSTIC: every matcher is generic electrical grammar
  (number + SI unit + qualifier word); NO chip / vendor / SKU / problem-id
  literal (enforced by `programs/source_chip_agnostic_check.py .`).

CONTRACT
  Each emitted dict is shaped to seed a checklist item:
    {
      "kind":        one of the five kinds above,
      "requirement": human-readable testable requirement,
      "evidence":    the EXACT phrase it came from,
      "coverage_tokens": [the value+unit tokens a check must touch],
      "provenance":  "STRUCTURAL",
      # kind-specific structured fields (value/unit/lo/hi) are also included.
    }

CLI
    python3 spec_electrical_extract.py <prompt.txt> [--json]
    cat prompt.txt | python3 spec_electrical_extract.py -
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Shared number grammar (chip-AGNOSTIC, pure structural shape)
# ---------------------------------------------------------------------------
# A decimal number, allowing an optional leading sign, thousands separators
# (commas / underscores: 12,000 / 12_000) and a decimal fraction (1.8, 0.05).
# The separators are stripped before float() by _to_float().
_NUM = r"[+-]?\d[\d_,]*(?:\.\d+)?"


def _to_float(tok: str) -> Optional[float]:
    """Parse a captured number token (commas / underscores allowed) to float."""
    try:
        return float(tok.replace(",", "").replace("_", ""))
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# (1) CLOCK FREQUENCY
# ---------------------------------------------------------------------------
# A number + a frequency unit. The unit group preserves the SI prefix so the
# requirement can report "100 MHz" verbatim. Anchored on a real unit token so a
# bare integer never qualifies. chip-AGNOSTIC.
_FREQ_RE = re.compile(
    r"\b(" + _NUM + r")\s*(GHz|MHz|kHz|KHz|Hz)\b")
# Clock CONTEXT that must be present (anywhere in the prompt) for a freq number
# to be read as a CLOCK frequency rather than some unrelated rate. chip-AGNOSTIC.
_CLOCK_CTX_RE = re.compile(
    r"\b(clock|clk|frequency|operating\s+frequency|f_?clk|runs?\s+at|"
    r"clocked\s+at|sample\s+rate|baud)\b", re.IGNORECASE)
# A baud-rate hint — when present, the requirement notes the rate is a baud rate.
_BAUD_RE = re.compile(r"\bbaud\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# (2) SUPPLY VOLTAGE
# ---------------------------------------------------------------------------
# A number + a volt unit (V / mV). Anchored on the unit; supply CONTEXT is
# enforced separately so a bare "1.2 V" (e.g. a Vref / threshold owned elsewhere)
# does NOT mint a supply item. The trailing negative lookahead `(?!\s*/)` rejects
# a "V/" rate unit ("2 V/ns" is a SLEW rate, not a supply voltage). chip-AGNOSTIC.
_VOLT_RE = re.compile(
    r"\b(" + _NUM + r")\s*(mV|V)\b(?!\s*/)")
# Supply CONTEXT that must be present for a voltage number to be read as a supply
# rail. Covers prose ("supply"/"rail"/"operating voltage"/"core voltage") and the
# canonical rail identifiers (VDD / VDDIO / VCC). chip-AGNOSTIC.
_SUPPLY_CTX_RE = re.compile(
    r"\b(supply|VDDIO|VDDA|VDD|VCCIO|VCC|operating\s+voltage|core\s+voltage|"
    r"io\s+voltage|power\s+rail|rail)\b", re.IGNORECASE)
# A REFERENCE voltage context (Vref / bandgap / a `REF` pin / "reference") within
# the short window before a volt value — that value is a reference, not a supply
# rail (precision guard). Searched (not anchored) so an intervening pin name
# ("bandgap `REF` = 2.048 V") still triggers the skip. chip-AGNOSTIC.
_REF_CTX_RE = re.compile(r"(V[_ ]?REF\w*|band[\s-]?gap|\bREF\b|reference)",
                         re.IGNORECASE)


# ---------------------------------------------------------------------------
# (3) CURRENT
# ---------------------------------------------------------------------------
# A number + a current unit (A / mA / uA / µA). The micro sign appears as both
# the ASCII "u" and the Unicode "µ" (U+00B5) / "μ" (U+03BC). chip-AGNOSTIC.
_CURRENT_RE = re.compile(
    r"\b(" + _NUM + r")\s*(mA|[uµμ]A|nA|A)\b")
# Current CONTEXT that must be present for a current number to be read as a
# current spec ("current"/"draw"/"consumption"/"Idd"). chip-AGNOSTIC.
_CURRENT_CTX_RE = re.compile(
    r"\b(current|draw(?:s|ing|n)?|consumption|consume[sd]?|Idd|Iddq|"
    r"quiescent)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# (4) TEMPERATURE RANGE
# ---------------------------------------------------------------------------
# A stated LO-to-HI temperature range. Both endpoints carry an optional sign; the
# degree unit (°C / C / degC) may appear on the high endpoint only ("-40 to 125
# °C") or on both ("-40°C to +85°C"). The connective is "to" or a dash. The
# trailing unit is mandatory so a bare numeric range ("0 to 70") never qualifies.
# chip-AGNOSTIC.
_TEMP_RANGE_RE = re.compile(
    r"([+-]?\d{1,3}(?:\.\d+)?)\s*(?:°\s*C|degC|deg\s*C|C\b)?\s*"
    r"(?:to|–|—|-|\.\.\.?|through)\s*"
    r"([+-]?\d{1,3}(?:\.\d+)?)\s*(?:°\s*C|degC|deg\s*C|C\b)",
    re.IGNORECASE)
# Temperature / operating CONTEXT that must be present for a numeric range to be
# read as an operating-temperature range (vs an unrelated numeric span). The
# degree-unit alternatives (°C / degC) are kept OUTSIDE word boundaries — `°` is
# not a word char, so a `\b` before it would never match.
_TEMP_CTX_RE = re.compile(
    r"\b(?:temperature|temp\b|operating|junction|ambient|celsius)\b"
    r"|°\s*C|\bdegC\b|\bdeg\s*C\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# (5) SLEW RATE
# ---------------------------------------------------------------------------
# A slew rate: the phrase "slew rate" AND a number with V/ns or V/us (µs). The
# phrase is the anchor; the number+unit is the value. chip-AGNOSTIC.
_SLEW_PHRASE_RE = re.compile(r"\bslew[ \-]?rate\b", re.IGNORECASE)
_SLEW_VALUE_RE = re.compile(
    r"\b(" + _NUM + r")\s*V\s*/\s*([nµμu]s)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# (6) MARKDOWN SPEC-TABLE ROWS — `| param | value | range | unit | note |`
# ---------------------------------------------------------------------------
# Real datasheets state most electricals in a TABLE where the parameter name, the
# numeric value, and the SI unit live in SEPARATE cells, so the prose number+unit
# passes (which need adjacency) miss them. This pass reads a markdown table row,
# binds the first non-empty cell as the PARAMETER NAME, finds a numeric cell and a
# unit cell, and maps the unit -> facet. §4.05: a row mints an item ONLY when a
# real number cell AND a real unit cell AND a name cell are all present.
_CELL_NUM_RE = re.compile(r"^[≤≥~<>]?\s*([+-]?\d+(?:\.\d+)?)$")
_CELL_FREQ_U = re.compile(r"^(GHz|MHz|kHz|KHz|Hz)$")
_CELL_VOLT_U = re.compile(r"^(mV|V)$")
_CELL_CURR_U = re.compile(r"^(mA|[uµμ]A|nA|A)$")
# a supply-rail PARAMETER name (vs a Vref / threshold, which the analog extractor
# owns) — the voltage-row facet only fires for a supply-ish name. chip-AGNOSTIC.
_SUPPLY_NAME_RE = re.compile(
    r"\b(vdd|vcc|vddio|vccio|vin|vout|vldo|core|supply|rail|iovdd|avdd|dvdd)\b",
    re.IGNORECASE)
# a FULL-SCALE / input-range qualifier on a voltage row -> a signal range, NOT a
# supply rail (e.g. an ADC `Vin (FS, diff)` full-scale input). chip-AGNOSTIC.
_FS_NAME_RE = re.compile(r"\b(fs|full[\s-]?scale|input\s+range)\b", re.IGNORECASE)


def _table_cells(line: str):
    """Cells of a markdown table row (outer pipes stripped), or None if the line
    is not a `|`-delimited data row (header separators `|---|` are skipped)."""
    if line.count("|") < 2:
        return None
    if re.fullmatch(r"\s*\|?[\s:|+-]+\|?\s*", line):   # |---|---| separator
        return None
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") else inner
    return [c.strip().strip("`* ") for c in inner.split("|")]


def _table_items(text: str) -> List[dict]:
    """Electrical items recovered from markdown spec-table rows (clock / supply /
    current). Temperature ranges are handled by the slash-list pass. The doc-wide
    context gates still apply (enforced by the caller)."""
    out: List[dict] = []
    for line in text.splitlines():
        cells = _table_cells(line)
        if not cells or len(cells) < 2:
            continue
        name = next((c for c in cells if c), "")
        if not name:
            continue
        num = next((m.group(1) for c in cells
                    for m in [_CELL_NUM_RE.match(c)] if m), None)
        if num is None:
            continue
        for c in cells:
            if _CELL_FREQ_U.match(c):
                out.append({"kind": "clock_frequency", "value": _to_float(num),
                            "unit": c, "disp": num + " " + c, "evidence": line.strip()[:120],
                            "name": name})
                break
            if _CELL_VOLT_U.match(c):
                # "Vin" names a rail (LDO input) OR an ADC FULL-SCALE INPUT range —
                # the latter is a signal range, not a supply. Exclude a full-scale /
                # input-range row (precision). chip-AGNOSTIC.
                if _SUPPLY_NAME_RE.search(name) and not _FS_NAME_RE.search(name):
                    out.append({"kind": "supply_voltage", "value": _to_float(num),
                                "unit": c, "disp": num + " " + c,
                                "evidence": line.strip()[:120], "name": name})
                break
            if _CELL_CURR_U.match(c):
                out.append({"kind": "current_spec", "value": _to_float(num),
                            "unit": c, "disp": num + " " + c, "evidence": line.strip()[:120],
                            "name": name})
                break
    return out


# A slash / comma LIST of corner temperatures with a single trailing unit:
# "−40/27/125 °C", "-40, 27, 125 degC". The operating range is min..max of the
# list. chip-AGNOSTIC (the value list + a degree unit).
_TEMP_LIST_RE = re.compile(
    r"([+-]?\d{1,3}(?:\s*[/,]\s*[+-]?\d{1,3}){1,5})\s*(?:°\s*C|degC|deg\s*C)",
    re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def extract(prompt_text: str) -> List[dict]:
    """Extract stated clock-frequency + electrical checklist items from a prompt.

    Returns a list of dicts (one per EXPLICIT number+unit electrical fact):
    clock_frequency | supply_voltage | current_spec | temperature_range |
    slew_rate. Each fires ONLY on a real number+unit + its specific qualifier
    context.

    §4.05 no-leak: a number with no unit, or a unit with no qualifying context,
    emits NOTHING; `extract("design a multiplier")` returns []. chip-AGNOSTIC:
    keys on number + SI unit + qualifier word, never a problem id."""
    if not prompt_text or not isinstance(prompt_text, str):
        return []
    # Normalize the Unicode MINUS SIGN (U+2212, common in datasheets: "−40 °C")
    # to ASCII '-' so a signed value parses. The EN-DASH (U+2013 '–') is LEFT
    # intact — it is the numeric RANGE separator ("0.1–10") and must not become a
    # sign. chip-AGNOSTIC.
    text = prompt_text.replace("−", "-")
    items: List[dict] = []

    # --- (1) Clock frequency: a freq number, gated on clock context -----------
    if _CLOCK_CTX_RE.search(text):
        is_baud = bool(_BAUD_RE.search(text))
        seen_freq = set()
        for m in _FREQ_RE.finditer(text):
            val = _to_float(m.group(1))
            if val is None or val <= 0:
                continue
            unit = m.group(2)
            disp = m.group(1).strip() + " " + unit
            if disp in seen_freq:
                continue
            seen_freq.add(disp)
            baud_note = " (stated as a baud rate)" if is_baud else ""
            items.append({
                "kind": "clock_frequency",
                "requirement": ("clock frequency: " + disp + baud_note
                                + "; constraints / TB must honor this rate."),
                "evidence": m.group(0).strip(),
                "value": val,
                "unit": unit,
                "is_baud": is_baud,
                "coverage_tokens": [m.group(1).strip(), unit],
                "provenance": "STRUCTURAL",
            })

    # --- (2) Supply voltage: a volt number, gated on supply context -----------
    if _SUPPLY_CTX_RE.search(text):
        seen_v = set()
        for m in _VOLT_RE.finditer(text):
            val = _to_float(m.group(1))
            if val is None:
                continue
            # PRECISION: a voltage that is a REFERENCE (Vref / bandgap) is owned by
            # the analog reference_voltage facet, NOT a supply rail. Skip a volt
            # whose preceding context — WITHIN THE CURRENT CLAUSE (after the last
            # ;/|/newline, ≤40 chars) — names a reference. The clause bound stops a
            # `REF` in a PRIOR clause from suppressing a real later supply rail.
            _lo = max(text.rfind(";", max(0, m.start() - 40), m.start()),
                      text.rfind("|", max(0, m.start() - 40), m.start()),
                      text.rfind("\n", max(0, m.start() - 40), m.start()),
                      m.start() - 40, 0)
            if _REF_CTX_RE.search(text[_lo:m.start()]):
                continue
            unit = m.group(2)
            disp = m.group(1).strip() + " " + unit
            if disp in seen_v:
                continue
            seen_v.add(disp)
            items.append({
                "kind": "supply_voltage",
                "requirement": ("supply voltage: " + disp
                                + "; the design must operate at this rail."),
                "evidence": m.group(0).strip(),
                "value": val,
                "unit": unit,
                "coverage_tokens": [m.group(1).strip(), unit],
                "provenance": "STRUCTURAL",
            })

    # --- (3) Current: a current number, gated on current context --------------
    if _CURRENT_CTX_RE.search(text):
        seen_i = set()
        for m in _CURRENT_RE.finditer(text):
            val = _to_float(m.group(1))
            if val is None or val < 0:
                continue
            unit = m.group(2)
            disp = m.group(1).strip() + " " + unit
            if disp in seen_i:
                continue
            seen_i.add(disp)
            items.append({
                "kind": "current_spec",
                "requirement": ("current spec: " + disp
                                + "; the design must meet this current budget."),
                "evidence": m.group(0).strip(),
                "value": val,
                "unit": unit,
                "coverage_tokens": [m.group(1).strip(), unit],
                "provenance": "STRUCTURAL",
            })

    # --- (4) Temperature range: LO-to-HI °C, gated on temp/operating context --
    if _TEMP_CTX_RE.search(text):
        seen_t = set()
        for m in _TEMP_RANGE_RE.finditer(text):
            lo = _to_float(m.group(1))
            hi = _to_float(m.group(2))
            if lo is None or hi is None:
                continue
            if lo > hi:
                lo, hi = hi, lo
            key = (lo, hi)
            if key in seen_t:
                continue
            seen_t.add(key)
            lo_s = m.group(1).strip()
            hi_s = m.group(2).strip()
            items.append({
                "kind": "temperature_range",
                "requirement": ("operating temperature range: " + lo_s
                                + " to " + hi_s + " °C; corners must cover it."),
                "evidence": m.group(0).strip(),
                "lo": lo,
                "hi": hi,
                "unit": "C",
                "coverage_tokens": [lo_s, hi_s],
                "provenance": "STRUCTURAL",
            })

    # --- (5) Slew rate: the phrase + a V/ns or V/us value ---------------------
    if _SLEW_PHRASE_RE.search(text):
        seen_s = set()
        for m in _SLEW_VALUE_RE.finditer(text):
            val = _to_float(m.group(1))
            if val is None or val <= 0:
                continue
            unit = "V/" + m.group(2).replace("µ", "u").replace("μ", "u")
            disp = m.group(1).strip() + " " + unit
            if disp in seen_s:
                continue
            seen_s.add(disp)
            items.append({
                "kind": "slew_rate",
                "requirement": ("output slew rate: " + disp
                                + "; the IO drive must meet this slew."),
                "evidence": m.group(0).strip(),
                "value": val,
                "unit": unit,
                "coverage_tokens": [m.group(1).strip(), unit],
                "provenance": "STRUCTURAL",
            })

    # --- (6) markdown spec-TABLE rows (param | value | … | unit) --------------
    # value and unit live in separate cells, so the prose passes above miss them.
    # The same doc-wide context gate decides whether a table number is in-facet.
    _present = {(it["kind"], it.get("value"), it.get("unit")) for it in items}
    for ti in _table_items(text):
        if ti["kind"] == "clock_frequency" and not _CLOCK_CTX_RE.search(text):
            continue
        if ti["kind"] == "current_spec" and not _CURRENT_CTX_RE.search(text):
            continue
        if (ti["kind"], ti["value"], ti["unit"]) in _present:
            continue
        _present.add((ti["kind"], ti["value"], ti["unit"]))
        label = {"clock_frequency": "clock frequency", "supply_voltage": "supply voltage",
                 "current_spec": "current spec"}[ti["kind"]]
        items.append({
            "kind": ti["kind"],
            "requirement": (label + " (" + ti["name"] + "): " + ti["disp"]
                            + "; from the spec table — constraints/TB must honor it."),
            "evidence": ti["evidence"], "value": ti["value"], "unit": ti["unit"],
            "coverage_tokens": [ti["name"], ti["disp"]], "provenance": "STRUCTURAL",
        })

    # --- (7) slash/comma corner-temperature LIST ("−40/27/125 °C") ------------
    if _TEMP_CTX_RE.search(text):
        seen_tl = {(it.get("lo"), it.get("hi")) for it in items
                   if it["kind"] == "temperature_range"}
        for m in _TEMP_LIST_RE.finditer(text):
            nums = [_to_float(x) for x in re.split(r"[/,]", m.group(1))]
            nums = [n for n in nums if n is not None]
            if len(nums) < 2:
                continue
            lo, hi = min(nums), max(nums)
            if (lo, hi) in seen_tl:
                continue
            seen_tl.add((lo, hi))
            items.append({
                "kind": "temperature_range",
                "requirement": ("operating temperature range: " + str(lo) + " to "
                                + str(hi) + " °C (corner list); corners must cover it."),
                "evidence": m.group(0).strip(), "lo": lo, "hi": hi, "unit": "C",
                "coverage_tokens": [str(lo), str(hi)], "provenance": "STRUCTURAL",
            })

    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="PROGRAM-FIRST structural extractor for stated clock-"
                    "frequency + electrical specs. chip-AGNOSTIC, §4.05 no-leak.")
    ap.add_argument("prompt", help="prompt file ('-' for stdin)")
    ap.add_argument("--json", action="store_true",
                    help="emit the raw checklist-item list as JSON")
    args = ap.parse_args(argv)

    try:
        if args.prompt == "-":
            text = sys.stdin.read()
        else:
            with open(args.prompt, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
    except OSError as e:
        print("error: cannot read prompt: " + str(e), file=sys.stderr)
        return 2

    items = extract(text)
    if args.json:
        print(json.dumps(items, indent=2))
        return 0

    if not items:
        print("NO STATED ELECTRICAL SPEC (no number+unit+qualifier) "
              "-> [] (no fabrication)")
        return 0

    for it in items:
        print("- " + it["kind"] + ": " + it["requirement"])
        print("    evidence: " + it["evidence"][:90])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
