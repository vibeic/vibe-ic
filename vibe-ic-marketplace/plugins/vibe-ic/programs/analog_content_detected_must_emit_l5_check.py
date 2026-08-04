#!/usr/bin/env python3
"""analog_content_detected_must_emit_l5_check.py — Wave 47 / v0.120.1

Prevents silent ``L5_ADI_SPEC.json analog_blocks: []`` SKIP when
``input/docs/`` (or ``input_doc/``) clearly documents analog
content (oscillator, LDO, bandgap, POR, pull-up/down, ESD, charge-
pump, OTA / op-amp, OTP trim register, ...).

Closes the v0.120 fresh-agent failure mode where the agent wrote
``analog_blocks: []`` and ``A0_skip_decision.json: SKIPPED-CONDITION``
even though ``AS3616_Short_Datasheet_0v06.txt`` documented:
  - 4 MHz oscillator with FREQ_TRIM ±6%
  - RPD_WAKE 80-120 kΩ pull-down
  - RMPD_0/1/OFF analog pull-down switch network
  - DP / DM ESD protection
  - TRIM_VBG / TRIM_LDO / TRIM_OSC OTP registers

Algorithm (chip-AGNOSTIC):
  1. Scan every text doc under ``input/docs/`` and ``input_doc/``
     for analog keyword classes.
  2. Skip lines that explicitly negate analog content (``no analog``,
     ``digital only``, ``沒有類比``).
  3. Build ``analog_keywords_found[]`` with file:line citations and
     classify each hit into one of 8 keyword classes.
  4. Read L5_ADI_SPEC.json (if present) and L4 OTP trim registers.
  5. For each keyword class with hits, check that L5.analog_blocks[]
     OR L4.otp_layout.trim_registers contains a matching entry per
     the (chip-AGNOSTIC) mapping rules below.
  6. FAIL when keywords found but no matching L5/L4 entry, with an
     explicit list of (keyword_class, hits, missing_l5_pattern).
  7. PASS when every detected keyword class maps to an L5/L4 entry
     OR no keywords found in docs.
  8. Honors waiver
     ``analog_block_in_docs_intentionally_omitted_from_l5`` (>=40
     chars per omitted block).

Mapping rules (each keyword class → required L5 / L4 pattern):
  oscillator   → L5 type matches /osc|oscillator/i
  ldo          → L5 type matches /ldo|regulator/i
  bandgap      → L5 type matches /bandgap|reference|vref|vbg/i
  por          → L5 type matches /por|brownout|reset|bor/i
  pull         → L5 type matches /pull|switch/i
  esd          → L5 type matches /esd|clamp/i
  charge_pump  → L5 type matches /charge.?pump|level.?shift|comparator|ota|op.?amp/i
  trim         → L5 type matches /trim/i
                 OR L4.otp_layout.trim_registers has any entry

WHY "NO ANALOG KEYWORDS" EXITS 2 AND NOT 0 (#833)
-------------------------------------------------
This gate is registered in ``flow_compliance_check._STRUCTURAL_RTL_GATES``.
The driver for that tuple, ``_run_structural_rtl_gates``, reads the EXIT
CODE and nothing else:

    rc 0 -> a PASS gate record, counted by ``_p0_passed_count``
    rc 1 -> FAIL
    rc 2 -> a SKIP record, ``skip_kind: input-missing``

The gate printed ``[SKIP] ... no analog keywords found`` and returned 0, so
"there was no analog content to check" was credited in the executed-PASS
numerator, indistinguishable from "the docs describe analog content and
every class of it is recorded in L5". ``gate_skip_routing_check`` had this
exact skip path in its published unrouted inventory.

Three states, and the third is not the first:

    analog content found and recorded in L5 / L4   -> PASS  (rc 0)
    analog content found and NOT recorded          -> FAIL  (rc 1)
    nothing to compare                             -> rc 2, never a PASS

"Nothing to compare" has two shapes and the disclosure names which one
happened, because they are different facts about the project: no scannable
input document existed at all, or documents were read and none mentions
analog content. Both are vacuous for THIS gate — its subject is the
correspondence between doc evidence and the L5 record, and with no doc
evidence there is no correspondence to judge.

Usage:
    python3 analog_content_detected_must_emit_l5_check.py <project_dir>

Exit codes:
    0 = PASS (analog content found and mapped to L5 / L4, or waived)
    1 = FAIL (analog content but L5 missing matching entry)
    2 = VACUOUS_PASS — examined nothing (no input doc, or no analog keyword
        in the docs that were read). Also the rc for an unusable project
        argument, the same overload every gate routed through
        ``_vacuous_exit`` carries; ``_gate_invocation`` separates a genuine
        command-line rejection from a verdict by the callee's own error
        protocol.

        (The word for the stdlib argument parser is deliberately not written
        anywhere in this file: ``gate_skip_routing_check.argument_shape``
        classifies a module by a bare substring search over its whole source,
        so a mention in prose would move this gate into a bucket describing a
        parser it does not use. That column is reported, never used to select
        — but a reported column that a comment can falsify is still wrong.)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import _vacuous_exit as _vx

_GATE = "analog_content_detected_must_emit_l5_check"


WAIVER_KEY = "analog_block_in_docs_intentionally_omitted_from_l5"
WAIVER_MIN = 40


# Chip-AGNOSTIC keyword classes. Each entry maps a short class id to
# (regex matching at least one analog keyword variant, human label).
# Patterns intentionally tolerate punctuation/casing and common ASCII
# vendor encodings (band-gap, low-dropout, etc.).
_KEYWORD_CLASSES: Dict[str, Tuple[re.Pattern, str]] = {
    "oscillator": (
        re.compile(
            r"\b("
            r"oscillator|oscillat|RC[\s-]?osc|crystal|fOSC|tOSC|"
            r"FREQ_TRIM|FREQ_INIT|FREQ_ALL|"
            r"clock\s+source|內部時脈|振盪器"
            r")\b",
            re.IGNORECASE,
        ),
        "oscillator / fOSC / FREQ_TRIM",
    ),
    "ldo": (
        re.compile(
            r"\b("
            r"LDO|low[\s.\-]?dropout|regulator|VDDA|VDD_LDO|VREG"
            r")\b",
            re.IGNORECASE,
        ),
        "LDO / regulator",
    ),
    "bandgap": (
        re.compile(
            r"\b("
            r"bandgap|band[\s.\-]?gap|VBG|VREF|voltage\s+reference|"
            r"BG[\s_]?ref"
            r")\b",
            re.IGNORECASE,
        ),
        "bandgap / VBG / voltage reference",
    ),
    "por": (
        re.compile(
            r"\b("
            r"POR|power[\s.\-]?on[\s.\-]?reset|BOR|brown[\s.\-]?out|"
            r"上電復位"
            r")\b",
            re.IGNORECASE,
        ),
        "POR / BOR / brownout",
    ),
    "pull": (
        re.compile(
            r"\b("
            r"pull[\s.\-]?up|pull[\s.\-]?down|RPD|RPU|RMPD|"
            r"pulldown\s+resistor|pullup\s+resistor|pull[\s.\-]?down\s+switch|"
            r"下拉|上拉"
            r")\b",
            re.IGNORECASE,
        ),
        "pull-up / pull-down / RPD / RMPD",
    ),
    "esd": (
        re.compile(
            r"\b("
            r"ESD|ESD\s+protection|clamp\s+diode|靜電防護"
            r")\b",
            re.IGNORECASE,
        ),
        "ESD / clamp diode",
    ),
    "charge_pump": (
        re.compile(
            r"\b("
            r"charge[\s.\-]?pump|level[\s.\-]?shifter|comparator|"
            r"OTA|op[\s.\-]?amp|operational\s+amplifier|"
            r"電荷泵|位準轉換"
            r")\b",
            re.IGNORECASE,
        ),
        "charge-pump / level-shifter / OTA / op-amp",
    ),
    "trim": (
        re.compile(
            r"\b("
            r"TRIM_[A-Z0-9_]+|trim\s+register|trim\s+code|"
            r"TRIM_VBG|TRIM_LDO|TRIM_OSC|trim\s+bits"
            r")\b",
            re.IGNORECASE,
        ),
        "trim register (TRIM_VBG / TRIM_LDO / TRIM_OSC / ...)",
    ),
}


# Negation patterns — when a line declares "no analog content",
# "digital only", "沒有類比" etc., suppress all keyword classifications
# for that line. Conservative: any match anywhere on the line drops
# the line.
_NEGATION_RE = re.compile(
    r"\b("
    r"no\s+analog|digital[\s\-]only|純數位|沒有類比|"
    r"no\s+analog\s+content|fully\s+digital|all[\s\-]digital"
    r")\b",
    re.IGNORECASE,
)


# v1.6.523 — per-keyword negation/exclusion awareness. A keyword that
# appears ONLY inside a negation ("does not need a DAC", "no DAC",
# "without analog", "❌ LDO", "~~bandgap~~") must NOT count as analog
# content and must NOT force the spec layer to declare analog blocks.
# These markers are matched in the LOCAL window immediately preceding
# the keyword hit (a few words back) plus crossed-out / strikethrough
# markers adjacent to it. Chip-AGNOSTIC.
#
# Negation lead-ins that appear *before* the keyword. We allow up to a
# few short filler words (articles / adjectives like "an", "any",
# "analog", "the", "real") between the negation token and the keyword,
# anchored to the end of the preceding window.
_FILLER = r"(?:\s+(?:an?|any|the|a|real|extra|on-?chip|internal|external|dedicated|separate|additional|analog|digital)\b){0,3}"
_PRE_NEGATION_RE = re.compile(
    r"\b("
    r"no|without|w/o|not\s+need(?:ed|s)?|do(?:es)?\s+not\s+need|"
    r"does\s+not\s+(?:have|require|use|include|contain)|"
    r"don'?t\s+need|never\s+need|"
    r"not\s+(?:required|needed|used|present|applicable)|"
    r"excludes?|excluding|omit(?:s|ted)?|"
    r"無需|不需要|沒有|無|不含"
    r")" + _FILLER + r"\s*$",
    re.IGNORECASE,
)
# Crossed-out / strikethrough / explicit-removal markers adjacent to the
# keyword (e.g. "❌ DAC", "~~LDO~~", "[removed] bandgap", "× oscillator").
_STRIKE_MARKER_RE = re.compile(
    r"(❌|✗|✘|×|~~|\[removed\]|\[deleted\]|<del>|<s>|\bN/?A\b\s*[:\-])",
    re.IGNORECASE,
)


def _keyword_is_negated(line: str, match_start: int, match_end: int) -> bool:
    """True iff the keyword hit at [match_start:match_end] in ``line``
    appears only inside a negation / exclusion / crossed-out context.

    Looks at the ~40-char window immediately before the keyword for a
    negation lead-in, and at strike markers adjacent on either side.
    Conservative: only suppresses when an explicit negation token is
    found local to the hit — a positive mention elsewhere on the same
    line is unaffected (per-hit, not per-line).
    """
    win_start = max(0, match_start - 40)
    pre = line[win_start:match_start]
    if _PRE_NEGATION_RE.search(pre):
        return True
    # Strike markers immediately before (within 6 chars) or wrapping.
    near_pre = line[max(0, match_start - 6):match_start]
    near_post = line[match_end:match_end + 4]
    if _STRIKE_MARKER_RE.search(near_pre) or _STRIKE_MARKER_RE.search(near_post):
        return True
    # "~~keyword~~" strikethrough wrapping both sides.
    if "~~" in line[max(0, match_start - 2):match_start] and \
       "~~" in line[match_end:match_end + 2]:
        return True
    return False


# Mapping rule — how each keyword class is satisfied by an L5
# analog_blocks entry. Matches against entry["type"] OR entry["name"]
# OR entry["spec"].
_L5_TYPE_PATTERNS: Dict[str, re.Pattern] = {
    "oscillator": re.compile(r"osc|oscillator|crystal|clock", re.IGNORECASE),
    "ldo":        re.compile(r"ldo|regulator", re.IGNORECASE),
    "bandgap":    re.compile(r"bandgap|band[-_ ]?gap|reference|vref|vbg",
                              re.IGNORECASE),
    "por":        re.compile(r"por|reset|bor|brown", re.IGNORECASE),
    "pull":       re.compile(r"pull|switch|rpd|rpu|rmpd|pulldown|pullup",
                              re.IGNORECASE),
    "esd":        re.compile(r"esd|clamp|diode", re.IGNORECASE),
    "charge_pump": re.compile(
        r"charge.?pump|level.?shift|comparator|ota|op.?amp",
        re.IGNORECASE,
    ),
    "trim":       re.compile(r"trim", re.IGNORECASE),
}


_DOC_DIRS = (
    "input/docs",
    "phase1/input_doc",
)

_L5_GLOBS = (
    "phase1/generated_docs/L5_ADI_SPEC.json",
    "phase1/generated_docs/L5*.json",
    "**/L5_ADI_SPEC.json",
)

_L4_GLOBS = (
    "phase1/generated_docs/L4_REGMAP.json",
    "phase1/generated_docs/L4*.json",
    "**/L4_REGMAP.json",
)

_L1_GLOBS = (
    "phase1/generated_docs/L1_DATASHEET.json",
    "phase1/generated_docs/L1*.json",
    "**/L1_DATASHEET.json",
)

_L9_GLOBS = (
    "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
    "phase1/generated_docs/L9*.json",
    "**/L9_INTEGRATION_SPEC.json",
)

# ───────────────────────────────────────────────────────────────────────────
# ORGANIC #633 — external-reference-pin discriminator for the bandgap class.
#
# The bandgap keyword class matches `VREF`/`VBG`/`voltage reference`. For a
# data-converter / mixed-signal IC whose reference is supplied EXTERNALLY (the
# modulator reference comes in off-chip on VREF/VHI/VLO pins) there is NO
# on-chip bandgap/reference BLOCK to spec, so demanding an L5.analog_blocks[]
# entry false-FAILs the entire class of externally-referenced analog ICs. The
# extractor already discriminates block-vs-prose (ORGANIC #466 R3
# spurious_analog_blocks); this gate must likewise honor reference-PIN-vs-
# bandgap-BLOCK. chip-AGNOSTIC: pure pin-declaration + on-chip-descriptor
# structure, no chip/vendor/SKU literal.
#
# An ON-CHIP bandgap signal (explicit `bandgap` / `BG_ref` / `on-chip
# reference` / `voltage reference circuit|block|generator`) STILL requires an
# L5 entry — the suppression fires ONLY when every bandgap-class hit is a bare
# external-reference-pin mention.
_ONCHIP_BANDGAP_RE = re.compile(
    r"bandgap|band[\s.\-]?gap|\bBG[\s_]?ref\b|on[\s\-]?chip\s+(?:voltage\s+)?"
    r"reference|(?:voltage\s+)?reference\s+(?:generator|circuit|block|core|"
    r"cell)|reference\s+generator",
    re.IGNORECASE)
# Short reference-PIN tokens (an externally-supplied reference rail).
_REF_PIN_TOKEN_RE = re.compile(
    r"\bV(?:REF|BG|HI|LO|RH|RL|REFP|REFN|REFH|REFL|CM)\b", re.IGNORECASE)
# Explicit external-reference-pin context on the hit line itself.
_EXTERNAL_REF_CONTEXT_RE = re.compile(
    r"reference\s+pins?|external(?:ly)?[\s-]*(?:supplied|provided|driven)?"
    r"[\s\w]*reference|reference\s*\([^)]*[-−][^)]*\)|off[\s-]?chip\s+reference"
    r"|supplied\s+off[\s-]?chip",
    re.IGNORECASE)


def _external_ref_pin_names(project: Path) -> set:
    """Uppercase names declared as TOP/EXTERNAL pins in L1.pin_table and
    L9.top_ports/ports — the design's own statement that a token is an
    externally-supplied pin, not an internal block."""
    names: set = set()
    p1 = _find_first(project, _L1_GLOBS)
    if p1 is not None:
        try:
            d = json.loads(p1.read_text())
            for row in (d.get("pin_table") or d.get("pins") or []):
                nm = row.get("name") if isinstance(row, dict) else row
                if isinstance(nm, str):
                    names.add(nm.strip().upper())
        except Exception:
            pass
    p9 = _find_first(project, _L9_GLOBS)
    if p9 is not None:
        try:
            d = json.loads(p9.read_text())
            for row in (d.get("top_ports") or d.get("ports") or []):
                nm = row.get("name") if isinstance(row, dict) else row
                if isinstance(nm, str):
                    names.add(nm.strip().upper())
        except Exception:
            pass
    return names


def _bandgap_external_only(project: Path, hit_lines: List[str]) -> bool:
    """ORGANIC #633 — True iff EVERY bandgap-class hit is a bare external-
    reference-pin mention (no on-chip bandgap descriptor), AND the reference is
    positively externally supplied (a reference token declared as an external
    pin in L1/L9, OR an explicit external-reference-pin context on a hit line).
    Fail-closed: a bare ambiguous `VREF` with NO external evidence keeps the
    requirement (returns False)."""
    # Any on-chip bandgap descriptor → NOT external-only (keep the L5 demand).
    if any(_ONCHIP_BANDGAP_RE.search(ln) for ln in hit_lines):
        return False
    ext_pins = _external_ref_pin_names(project)
    for ln in hit_lines:
        if _EXTERNAL_REF_CONTEXT_RE.search(ln):
            return True
        for tm in _REF_PIN_TOKEN_RE.finditer(ln):
            if tm.group(0).strip().upper() in ext_pins:
                return True
    return False


def _waiver_count(project: Path) -> int:
    """Count valid waiver entries (>=40 chars).

    Accepts either a single string under the canonical key (legacy) or
    a list of strings — every string ≥40 chars counts as 1 omitted
    block. Returns 0 if no waivers.json or invalid.
    """
    p = project / "waivers.json"
    if not p.exists():
        return 0
    try:
        d = json.loads(p.read_text())
    except Exception:
        return 0
    v = d.get(WAIVER_KEY)
    if isinstance(v, str):
        return 1 if len(v.strip()) >= WAIVER_MIN else 0
    if isinstance(v, list):
        return sum(1 for s in v
                   if isinstance(s, str) and len(s.strip()) >= WAIVER_MIN)
    return 0


def _scannable_docs(project: Path) -> List[Path]:
    """Every input document this gate would read, in stable order.

    #833 — extracted from `_scan_docs` (which used to inline the same walk)
    so the gate can state its DENOMINATOR when it finds nothing: "no input
    document existed" and "12 documents were read and none mentions analog"
    are different facts about the project, and a skip that does not say
    which one happened is unreviewable. Behaviour of `_scan_docs` is
    unchanged — it now iterates this list instead of rebuilding it.
    """
    seen: set = set()
    out: List[Path] = []
    for sub in _DOC_DIRS:
        d = project / sub
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if not f.is_file():
                continue
            if f.suffix.lower() not in (".txt", ".md", ".json"):
                continue
            if f in seen:
                continue
            seen.add(f)
            out.append(f)
    return out


def _scan_docs(project: Path) -> Dict[str, List[Tuple[str, int, str]]]:
    """Scan docs for analog keywords; return {class_id: [(file, line, text)]}."""
    hits: Dict[str, List[Tuple[str, int, str]]] = {
        cid: [] for cid in _KEYWORD_CLASSES
    }
    for f in _scannable_docs(project):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel = str(f.relative_to(project))
        for i, line in enumerate(text.splitlines(), start=1):
            if _NEGATION_RE.search(line):
                continue
            for cid, (pat, _) in _KEYWORD_CLASSES.items():
                # v1.6.523 — per-keyword negation awareness. A hit is
                # only counted if at least one OCCURRENCE on the line
                # is NOT inside a negation / exclusion / crossed-out
                # context. A keyword that appears only as "no DAC" /
                # "does not need" / "❌ LDO" / "~~bandgap~~" does not
                # count and must not force an L5 analog block.
                positive_hit = False
                for m in pat.finditer(line):
                    if not _keyword_is_negated(line, m.start(), m.end()):
                        positive_hit = True
                        break
                if positive_hit:
                    if len(hits[cid]) < 50:
                        hits[cid].append((rel, i, line.strip()[:120]))
    return hits


def _find_first(project: Path, globs) -> Optional[Path]:
    for pat in globs:
        for h in project.glob(pat):
            if h.is_file():
                return h
    return None


def _load_l5_blocks(project: Path) -> List[dict]:
    p = _find_first(project, _L5_GLOBS)
    if p is None:
        return []
    try:
        d = json.loads(p.read_text())
    except Exception:
        return []
    blocks = d.get("analog_blocks")
    if isinstance(blocks, list):
        return [b for b in blocks if isinstance(b, dict)]
    return []


def _load_l4_trim_registers(project: Path) -> List[dict]:
    p = _find_first(project, _L4_GLOBS)
    if p is None:
        return []
    try:
        d = json.loads(p.read_text())
    except Exception:
        return []
    # Look for L4.otp_layout.trim_registers OR L4.trim_registers
    otp = d.get("otp_layout") or {}
    if isinstance(otp, dict):
        tr = otp.get("trim_registers")
        if isinstance(tr, list):
            return [t for t in tr if isinstance(t, dict)]
    tr = d.get("trim_registers")
    if isinstance(tr, list):
        return [t for t in tr if isinstance(t, dict)]
    return []


def _block_matches(block: dict, pat: re.Pattern) -> bool:
    for k in ("type", "name", "spec", "spec_summary", "block_type"):
        v = block.get(k)
        if isinstance(v, str) and pat.search(v):
            return True
    return False


def _l5_blocks_detected_flag(project: Path) -> Optional[bool]:
    p = _find_first(project, _L5_GLOBS)
    if p is None:
        return None
    try:
        d = json.loads(p.read_text())
    except Exception:
        return None
    v = d.get("analog_blocks_detected")
    if isinstance(v, bool):
        return v
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: analog_content_detected_must_emit_l5_check "
              "<project_dir>", file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"ERROR: {project} not a directory", file=sys.stderr)
        return 2

    docs = _scannable_docs(project)
    hits = _scan_docs(project)
    classes_with_hits = [cid for cid, lst in hits.items() if lst]

    if not classes_with_hits:
        # #833 — the gate examined nothing it can compare. Before this it
        # returned 0, and the P0 structural umbrella (which reads the exit
        # code and nothing else) recorded a full executed PASS for a run
        # that compared no doc evidence against any L5 record.
        #
        # The reason token names WHICH vacuity happened, with the
        # denominator: a project with no input document at all is a
        # different fact from a project whose documents were read and
        # describe no analog content.
        where = " / ".join(_DOC_DIRS)
        if not docs:
            reason = "no-input-doc"
            detail = f"no scannable input document under {where}"
        else:
            reason = f"no-analog-keyword-in-{len(docs)}-doc(s)"
            detail = (f"{len(docs)} input document(s) scanned under "
                      f"{where}; none carries a positive analog keyword")
        print(f"[SKIP] {_GATE}: {detail} — nothing to compare against "
              f"L5.analog_blocks[] / L4.otp_layout.trim_registers")
        # Both channels from the one conclusion: the line-start sentinel
        # `flow_compliance_check._stdout_signals_vacuous` matches, and the
        # rc the P0 umbrella actually reads.
        _vx.announce_vacuous(_GATE, reason)
        return _vx.exit_code(passed=True, skipped=True)

    l5_blocks = _load_l5_blocks(project)
    l4_trim = _load_l4_trim_registers(project)

    # Map each detected class to L5/L4 evidence.
    missing: List[Tuple[str, int, str]] = []
    matched: List[Tuple[str, int, str]] = []
    for cid in classes_with_hits:
        pat = _L5_TYPE_PATTERNS[cid]
        n_hits = len(hits[cid])
        # Special case: trim is satisfied by L4 trim_registers OR L5 trim entry.
        if cid == "trim":
            if l4_trim or any(_block_matches(b, pat) for b in l5_blocks):
                matched.append((cid, n_hits,
                                _KEYWORD_CLASSES[cid][1]))
                continue
        # Generic: at least one L5 entry must match the class pattern.
        if any(_block_matches(b, pat) for b in l5_blocks):
            matched.append((cid, n_hits, _KEYWORD_CLASSES[cid][1]))
            continue
        # ORGANIC #633 — bandgap/reference class: an EXTERNAL reference
        # (VREF/VHI/VLO supplied off-chip) is not an on-chip bandgap BLOCK and
        # needs no L5 entry. Suppress the requirement ONLY when every bandgap-
        # class hit is a bare external-reference-pin mention (no on-chip
        # descriptor) AND the reference is positively externally supplied. A
        # genuine on-chip bandgap keyword still demands an L5 entry (no-leak).
        if cid == "bandgap" and _bandgap_external_only(
                project, [t for (_f, _ln, t) in hits[cid]]):
            matched.append((
                cid, n_hits,
                _KEYWORD_CLASSES[cid][1] +
                " [external reference pins only — no on-chip bandgap block "
                "required (#633)]"))
            continue
        missing.append((cid, n_hits, _KEYWORD_CLASSES[cid][1]))

    waiver_n = _waiver_count(project)
    detected_flag = _l5_blocks_detected_flag(project)

    if not missing:
        print(f"[PASS] analog_content_detected_must_emit_l5_check: "
              f"{len(classes_with_hits)} analog keyword class(es) "
              f"detected, all mapped to L5.analog_blocks[] "
              f"({len(l5_blocks)} block(s)) "
              f"or L4.otp_layout.trim_registers ({len(l4_trim)} reg)")
        return 0

    # FAIL — but check if waivers cover all missing classes.
    if waiver_n >= len(missing):
        print(f"[PASS_WITH_WAIVER] "
              f"analog_content_detected_must_emit_l5_check: "
              f"{len(missing)} class(es) missing from L5 but "
              f"{waiver_n} waiver(s) under "
              f"'{WAIVER_KEY}' (>= {WAIVER_MIN} chars each)")
        return 0

    sample_lines = []
    for cid, n, label in missing[:5]:
        first_hit = hits[cid][0]
        sample_lines.append(
            f"{cid} ({n} hits, e.g. {first_hit[0]}:{first_hit[1]}) — "
            f"need L5 entry matching /{_L5_TYPE_PATTERNS[cid].pattern}/"
        )

    detect_note = ""
    if detected_flag is False and any(hits[c] for c in classes_with_hits):
        detect_note = (" L5.analog_blocks_detected=false contradicts "
                       "doc evidence.")

    print(f"[FAIL] analog_content_detected_must_emit_l5_check: "
          f"{len(missing)}/{len(classes_with_hits)} analog keyword "
          f"class(es) detected in docs but NOT mapped to "
          f"L5.analog_blocks[] (currently {len(l5_blocks)} block(s)).{detect_note} "
          f"Add at least minimal entry per missing class. "
          f"Examples: {'; '.join(sample_lines)}. "
          f"To intentionally omit, add waiver "
          f"'{WAIVER_KEY}' (string or list of strings, "
          f">={WAIVER_MIN} chars each).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
