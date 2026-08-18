#!/usr/bin/env python3
"""spec_calibration_extract.py — PROGRAM-FIRST structural extractor for the
L13 LAB CALIBRATION / TRIM facet of a design doc / prompt.

A large family of analog / mixed-signal (and some digital) design prompts state
a CALIBRATION or TRIM facet EXPLICITLY: a trim CODE / register / field that the
design exposes, and/or an ordered calibration PROCEDURE (a numbered step
sequence the part runs to calibrate itself). The hidden scoring testbench (and
the L13 spec-conformance layer) exercise exactly those calibration fields and
procedure steps, so a verification FAILURE on a calibratable design is — per the
spec-coverage doctrine — almost always one of OUR OWN extraction gaps (a stated
trim field we never read out / a calibration step we never covered), not an
unfixable floor.

This program does the DETERMINISTIC, chip-AGNOSTIC, PROGRAM-FIRST half of that
job: given a prompt, it extracts the STRUCTURAL calibration skeleton —

  * one `calibration_field`     ChecklistItem per stated trim/cal CODE / register
                                / field that carries a STRUCTURAL qualifier, and
  * one `calibration_procedure` ChecklistItem per stated, ORDERED calibration
                                STEP / sequence / phase / routine

— anchored to a real cal/trim TOKEN plus real STRUCTURE, so the downstream
coverage attribution (`spec_coverage_check.py` / the TB self-check) can verify
every stated trim field and calibration step is exercised.

WHAT COUNTS AS A "STATED CALIBRATION" (the §4.05 no-leak boundary)
  The extractor keys ONLY on an explicit calibration / trim TOKEN
  ("calibration", "trim code", "trim register", "trim value", "cal code",
  "cal register", "calibrate", "calibration step/sequence/phase/routine",
  "during calibration") PLUS real STRUCTURE:

    calibration_field — a cal/trim token AND a structural qualifier:
      a named field/register (`trim_code`, `osc_trim`, `OSC_TRIM register`)
      OR a bit width (`8-bit`)  OR an offset (`0x4`)  OR a step/range
      (`0..255`, `4 LSB step`). A bare "calibration" with NO structural
      qualifier yields NOTHING.

    calibration_procedure — a cal token tied to an ORDERED/step structure:
      "calibration step 1", "calibration sequence", "calibration phase 2",
      "calibration routine", "during calibration <step>".

  It NEVER fabricates a requirement out of free prose: "compute the average"
  returns []; "trim trailing whitespace" returns [] (the cal/trim token must
  mean calibration-trim — it is admitted only with a real qualifier, never a
  bare "trim the string"). chip-AGNOSTIC: every matcher is generic calibration
  grammar — NO chip / vendor / SKU / problem-id literal (enforced by
  `programs/source_chip_agnostic_check.py .`).

CONTRACT
  Each emitted dict is shaped to seed a `spec_coverage_check.ChecklistItem`:
    {
      "kind":        "calibration_field" | "calibration_procedure",
      "requirement": human-readable testable requirement,
      "evidence":    the EXACT cal/trim line it came from,
      "coverage_tokens": [tokens a TB must touch to cover it],
      "provenance":  "STRUCTURAL"  (default),
      "block_eligible": True,
    }

CLI
    python3 spec_calibration_extract.py <prompt.txt> [--json]
    cat prompt.txt | python3 spec_calibration_extract.py -
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Calibration / trim ANCHOR grammar (chip-AGNOSTIC, pure structural shape)
# ---------------------------------------------------------------------------
# The cal/trim ANCHOR token. "trim" alone is ambiguous (it also means
# "trim a string"), so a bare "trim" is NOT an anchor on its own — it anchors
# only in a calibration sense: "trim code/register/value/bit(s)/setting" or as a
# verb against a calibratable circuit element. The strong, unambiguous anchors
# ("calibration", "cal code/register", "calibrate") stand on their own.
#   * UNAMBIGUOUS cal anchors: calibration / calibrate / cal code / cal register.
#   * QUALIFIED trim anchors:  trim code / trim register / trim value / trim
#     setting / trim bit(s) / trim field — the noun pins it to calibration-trim.
_CAL_ANCHOR_RE = re.compile(
    r"\b("
    r"calibrat(?:e|es|ed|ing|ion)"                  # calibrate / calibration
    r"|cal\s+(?:code|register|reg|value|word|field|bits?)"  # cal code / cal register
    r"|trim\s+(?:code|register|reg|value|word|field|setting|bits?)"  # trim code / ...
    r"|(?:[A-Za-z_]\w*_)?trim(?:_[A-Za-z_]\w*)?\b"  # *_trim / trim_* identifier (osc_trim, trim_code)
    r")\b",
    re.IGNORECASE)

# A BARE "trim" used as an English verb on text/strings — the §4.05 negative
# guard. "trim the string", "trim trailing whitespace", "trim leading zeros".
# When the ONLY trim token in the text matches this AND there is no other cal
# anchor, the text has no calibration facet. chip-AGNOSTIC English grammar.
_STRING_TRIM_RE = re.compile(
    r"\btrim(?:s|med|ming)?\s+(?:the\s+|leading\s+|trailing\s+|off\s+|away\s+)?"
    r"(?:white\s*space|whitespace|spaces?|zeros?|chars?|characters?|"
    r"string|text|edges?|padding|blanks?)\b",
    re.IGNORECASE)


# ---------------------------------------------------------------------------
# Structural QUALIFIER grammar — what proves a cal anchor names a real field
# ---------------------------------------------------------------------------
# (1) A named field / register identifier — a snake_case / ALL_CAPS identifier
#     that carries a trim/cal token, or an identifier explicitly followed by the
#     word "register"/"field" near a cal anchor. chip-AGNOSTIC identifier shape.
_FIELD_IDENT_RE = re.compile(
    r"\b([A-Za-z_]\w*(?:trim|cal)\w*|(?:trim|cal)\w*[A-Za-z_]\w*)\b",
    re.IGNORECASE)
# The bare cal-ANCHOR words themselves ("calibration"/"calibrate"/"trim"/"cal"
# and their inflections) are NOT field NAMES — they match _FIELD_IDENT_RE's
# `cal\w*` arm but carry no real identifier. A field name must be a STRUCTURED
# identifier (a `_`-joined or longer trim/cal-bearing token), not the lone
# anchor. This is the §4.05 guard so "The chip supports calibration." (bare
# anchor, no field) and a stray "calibration sequence" do not mint a field.
_BARE_ANCHOR_WORDS: Set[str] = {
    "trim", "trims", "trimmed", "trimming",
    "cal", "calibrate", "calibrates", "calibrated", "calibrating",
    "calibration", "calibrations",
}


def _is_field_name(tok: str) -> bool:
    """A real trim/cal field IDENTIFIER, not a bare anchor word. chip-AGNOSTIC:
    requires a structured identifier (underscore-joined or a compound trim/cal
    token), so the lone words calibration/calibrate/trim/cal are rejected."""
    t = _norm(tok)
    if t.lower() in _BARE_ANCHOR_WORDS:
        return False
    return bool(_FIELD_IDENT_RE.fullmatch(t))
# a `<NAME> register`/`<NAME> field` mention (the noun proves it is a field).
_NAMED_REG_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s+(?:register|reg|field)\b", re.IGNORECASE)

# (2) A bit width: "8-bit", "8 bit", "N-bit", "width of 8". chip-AGNOSTIC.
_BITWIDTH_RE = re.compile(
    r"\b(\d{1,3})\s*[-\s]?bit\b|\bwidth\s+of\s+(\d{1,3})\b",
    re.IGNORECASE)

# (3) An offset / address: "0xNN", "offset 0x4", "at address 0x10". The hex
#     literal is the structural qualifier (a real register lives at an offset).
_OFFSET_RE = re.compile(
    r"\b(?:offset|address|addr|@)\s*(?:of\s*)?(0x[0-9A-Fa-f]+|\d+)\b"
    r"|\b(0x[0-9A-Fa-f]+)\b",
    re.IGNORECASE)

# (4) A step / range qualifier: "0..255", "0 to 255", "range 0-31", "step of 4",
#     "4 LSB step", "increment of 1". A real trim code has a settable range/step.
_RANGE_STEP_RE = re.compile(
    r"\b(\d+)\s*(?:\.\.|\.\.\.|to|-|–|through)\s*(\d+)\b"     # 0..255 / 0 to 255
    r"|\b(?:step|increment|granularity|resolution)\s+(?:of\s+)?"
    r"(\d+)\s*(?:LSB|lsb|mV|uV|µV|%)?\b"                      # step of 4 LSB
    r"|\b(\d+)\s*(?:LSB|lsb)\s+(?:step|increment|resolution)\b",  # 4 LSB step
    re.IGNORECASE)


# ---------------------------------------------------------------------------
# Calibration PROCEDURE grammar — an ordered step / sequence / phase / routine
# ---------------------------------------------------------------------------
# An explicit ordered calibration step / sequence / phase / routine. The cal
# token is BOUND to an ordering structure (a step number, the words
# "sequence"/"routine", or "during calibration" tied to an ordered step). The
# capturing group is the ordering token (number / "sequence" / "routine").
_CAL_PROC_RE = re.compile(
    r"\bcalibration\s+(?:step|phase|stage)\s*#?\s*(\d+)\b"     # calibration step 1
    r"|\bcalibration\s+(sequence|routine|procedure|algorithm)\b"  # calibration sequence
    r"|\bstep\s*#?\s*(\d+)\b[^\n.]{0,60}?\bcalibrat"           # step 1 ... calibrate
    r"|\bduring\s+calibration\b[^\n.]{0,40}?\b(step|phase|stage)\s*#?\s*(\d+)\b",  # during cal, step 2
    re.IGNORECASE)


def _norm(s: str) -> str:
    return s.strip().strip("`*").strip()


def _line_of(text: str, pos: int) -> str:
    """The full source line containing offset `pos` (trimmed). Used as evidence."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return text[start:end].strip()


def _has_cal_anchor(window: str) -> bool:
    """A real cal/trim anchor in `window`, NOT a bare string-trim verb. The
    string-trim guard only fires when the matched trim is the string-trim shape
    AND no unambiguous cal anchor co-occurs. chip-AGNOSTIC."""
    if not _CAL_ANCHOR_RE.search(window):
        return False
    # if the only trim token is a string-trim, and there is no standalone
    # calibration/calibrate/cal-code anchor, it is not a calibration window.
    strong = re.search(
        r"\bcalibrat(?:e|es|ed|ing|ion)\b"
        r"|\bcal\s+(?:code|register|reg|value|word|field|bits?)\b"
        r"|\b[A-Za-z_]*trim(?:_\w+)?\b\s*(?:register|reg|field|code|value)?",
        window, re.IGNORECASE)
    if _STRING_TRIM_RE.search(window) and not strong:
        return False
    return True


def _structural_qualifier(window: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (qualifier_kind, qualifier_text) for the FIRST structural qualifier
    found in `window`, else (None, None). Qualifier kinds: 'field', 'width',
    'offset', 'range'. chip-AGNOSTIC — pure structural shape, no design literal."""
    # named field / register identifier carrying trim/cal, or `<NAME> register`.
    # Only a STRUCTURED identifier qualifies — the bare anchor words
    # (calibration/calibrate/trim/cal) are rejected by _is_field_name so a
    # bare cal mention does not self-qualify (§4.05 no-leak).
    for m in _FIELD_IDENT_RE.finditer(window):
        if _is_field_name(m.group(1)):
            return "field", _norm(m.group(1))
    m = _NAMED_REG_RE.search(window)
    if m and re.search(r"\b(?:trim|cal|calibrat)", _norm(m.group(1)), re.IGNORECASE) \
            and _is_field_name(_norm(m.group(1))):
        return "field", _norm(m.group(1))
    # bit width
    m = _BITWIDTH_RE.search(window)
    if m:
        w = m.group(1) or m.group(2)
        return "width", w + "-bit"
    # offset / address
    m = _OFFSET_RE.search(window)
    if m:
        off = m.group(1) or m.group(2)
        return "offset", "offset " + off
    # step / range
    m = _RANGE_STEP_RE.search(window)
    if m:
        return "range", _norm(m.group(0))
    return None, None


# ---------------------------------------------------------------------------
# Field collection
# ---------------------------------------------------------------------------
def _collect_fields(text: str) -> List[Tuple[str, str, str, List[str]]]:
    """Return (name, qualifier_text, evidence, coverage_tokens) for every stated
    trim/cal FIELD — a cal anchor co-located with a structural qualifier on the
    SAME line. De-duplicated by (name, qualifier). chip-AGNOSTIC, §4.05 no-leak:
    a bare cal anchor with no qualifier emits nothing."""
    out: List[Tuple[str, str, str, List[str]]] = []
    seen: Set[Tuple[str, str]] = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        if not _has_cal_anchor(line):
            continue
        kind, qual = _structural_qualifier(line)
        if kind is None:
            continue   # cal anchor but NO structural qualifier → no leak
        # pick a name: a real trim/cal-bearing field IDENTIFIER if present, else
        # a generic "calibration_field" label tagged by its qualifier (the bare
        # anchor words never become the name).
        name = None
        for nm_m in _FIELD_IDENT_RE.finditer(line):
            if _is_field_name(nm_m.group(1)):
                name = _norm(nm_m.group(1))
                break
        if name is None:
            nreg = _NAMED_REG_RE.search(line)
            if nreg and _is_field_name(_norm(nreg.group(1))):
                name = _norm(nreg.group(1))
        if name is None:
            name = "calibration_field"
        key = (name.lower(), qual.lower())
        if key in seen:
            continue
        seen.add(key)
        tokens = sorted({name} | ({qual} if kind == "field" else set()))
        out.append((name, qual, line.strip(), tokens))
    return out


# ---------------------------------------------------------------------------
# Procedure collection
# ---------------------------------------------------------------------------
def _collect_procedures(text: str) -> List[Tuple[str, str, List[str]]]:
    """Return (step_label, evidence, coverage_tokens) for every stated, ORDERED
    calibration step / sequence / phase / routine. De-duplicated by label.
    chip-AGNOSTIC, §4.05 no-leak: anchored to the cal-procedure grammar only."""
    out: List[Tuple[str, str, List[str]]] = []
    seen: Set[str] = set()
    for m in _CAL_PROC_RE.finditer(text):
        # group layout: 1=step-num, 2=sequence-word, 3=step-num(step..calibrate),
        # 4=during-cal step-word, 5=during-cal step-num.
        num = m.group(1) or m.group(3) or m.group(5)
        word = m.group(2) or m.group(4)
        if num is not None:
            label = "calibration_step_" + str(int(num))
        elif word:
            label = "calibration_" + word.lower()
        else:
            continue
        if label in seen:
            continue
        seen.add(label)
        ev = _line_of(text, m.start())
        out.append((label, ev, [label]))
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def extract(prompt_text: str) -> List[Dict]:
    """Extract the stated L13 calibration / trim facet from `prompt_text`.

    Returns a list of dicts (each shaped for `spec_coverage_check.ChecklistItem`):
    one `calibration_field` item per stated trim/cal field that carries a
    structural qualifier (named field/register, bit width, offset, or step/range)
    and one `calibration_procedure` item per stated ordered calibration step /
    sequence / phase / routine.

    §4.05 no-leak gate: every emit is anchored to an explicit cal/trim token PLUS
    real structure — a bare "calibration" with no qualifier, "compute the
    average", and "trim the string" all return []. chip-AGNOSTIC: keys on
    calibration grammar (cal/trim token + field/width/offset/range or
    step/sequence structure), never a problem id."""
    if not prompt_text or not prompt_text.strip():
        return []

    fields = _collect_fields(prompt_text)
    procedures = _collect_procedures(prompt_text)

    items: List[Dict] = []

    for name, qual, ev, tokens in fields:
        items.append({
            "kind": "calibration_field",
            "requirement": "The design exposes a calibration/trim field "
                           + name + " (" + qual + "); the design must implement "
                           + "it and the TB must drive and read it back.",
            "evidence": ev,
            "coverage_tokens": tokens,
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })

    for label, ev, tokens in procedures:
        items.append({
            "kind": "calibration_procedure",
            "requirement": "The design follows a calibration procedure ("
                           + label + "); the TB must exercise this calibration "
                           + "step/sequence.",
            "evidence": ev,
            "coverage_tokens": tokens,
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })

    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="PROGRAM-FIRST structural extractor for the L13 calibration "
                    "/ trim facet (fields + procedure). chip-AGNOSTIC, §4.05 "
                    "no-leak.")
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
        print("NO STATED CALIBRATION (no cal/trim anchor + structural qualifier) "
              "-> [] (no fabrication)")
        return 0

    fields = [it for it in items if it["kind"] == "calibration_field"]
    procs = [it for it in items if it["kind"] == "calibration_procedure"]
    print("CALIBRATION FIELDS (" + str(len(fields)) + "):")
    for it in fields:
        print("  - " + it["coverage_tokens"][0]
              + "   [" + it["evidence"][:70] + "]")
    print("CALIBRATION PROCEDURE (" + str(len(procs)) + "):")
    for it in procs:
        print("  - " + it["coverage_tokens"][0])
        print("      evidence: " + it["evidence"][:90])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
