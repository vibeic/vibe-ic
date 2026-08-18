#!/usr/bin/env python3
"""spec_test_debug_extract.py — PROGRAM-FIRST structural extractor for the L7
TEST/DEBUG facet of a design doc / prompt.

A large family of design docs (L-docs, datasheets, CVDP / VerilogEval prompts)
state test-and-debug INFRASTRUCTURE EXPLICITLY: a scan chain (DFT), a JTAG/TAP
debug port, a built-in self-test (BIST), or a dedicated test/debug MODE pin.
The hidden scoring testbench — and the silicon sign-off — exercise exactly that
stated infra, so a verification gap on a design that NAMES one of these is, per
the spec-coverage doctrine, almost always one of OUR OWN extraction gaps (a
stated test/debug feature we never read out / never covered), not an unfixable
floor.

This program does the DETERMINISTIC, chip-AGNOSTIC, PROGRAM-FIRST half of that
job: given a prompt, it extracts the STRUCTURAL TEST/DEBUG skeleton — one
ChecklistItem per stated, anchored test/debug feature — so the downstream
coverage attribution (`spec_coverage_check.py` / the TB self-check) can verify
every stated test/debug requirement is exercised.

WHAT COUNTS (the §4.05 no-leak boundary)
  The extractor keys ONLY on an EXPLICIT, test/debug-SPECIFIC token (matched at a
  word boundary), one of four kinds:

    * scan_chain — a STATED scan / DFT infrastructure. Anchor: "scan enable",
      "scan_en", "scan chain", "scan_in", "scan_out", "scan mode", "DFT".
      A BARE verb "scan" ("scan the input bus") is NOT an anchor — only the
      DFT-specific tokens above fire, so ordinary "scan" prose never leaks.
    * jtag_tap — a STATED JTAG / TAP debug port. Anchor: requires at least one
      EXACT standard / signal token — "JTAG", "TAP controller", "TMS", "TCK",
      "TDI", "TDO".
    * bist — a STATED built-in self-test. Anchor: "BIST", "MBIST", "LBIST",
      "built-in self-test", "self-test".
    * test_mode — a STATED test/debug MODE pin or signal. Anchor: "test mode",
      "test_mode", "debug mode", "debug port", "test_en", "debug_en".

  It NEVER fabricates a requirement out of free prose: `extract("design a
  counter")` returns `[]`. Each emitted item is anchored to its own specific
  token. chip-AGNOSTIC: every matcher is generic DFT/debug vocabulary — NO chip /
  vendor / SKU / problem-id literal (enforced by
  `programs/source_chip_agnostic_check.py .`).

CONTRACT
  def extract(prompt_text: str) -> List[dict]
  Each emitted dict is shaped to seed a `spec_coverage_check.ChecklistItem`:
    {
      "kind":            "scan_chain" | "jtag_tap" | "bist" | "test_mode",
      "requirement":     human-readable testable requirement,
      "evidence":        the EXACT line / token it came from,
      "coverage_tokens": [tokens a TB / sign-off must touch to cover it],
      "provenance":      "STRUCTURAL"   (default),
      "block_eligible":  True,
    }

CLI
    python3 spec_test_debug_extract.py <prompt.txt> [--json]
    cat prompt.txt | python3 spec_test_debug_extract.py -
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Anchor grammar (chip-AGNOSTIC, pure DFT/debug vocabulary)
# ---------------------------------------------------------------------------
# Each kind keys on a list of word-boundary-anchored, test/debug-SPECIFIC tokens.
# The tokens are deliberately NARROW so an ordinary English word (the bare verb
# "scan", a generic "test" / "mode" word) can NEVER mint a requirement — only the
# DFT/debug-specific forms below fire. This IS the §4.05 no-leak boundary.

# (1) scan_chain — STATED scan / DFT infrastructure. A bare "scan" is excluded by
#     design: every alternative below carries a DFT-specific qualifier (enable /
#     chain / _in / _out / mode) or is the literal DFT acronym.
_SCAN_RE = re.compile(
    r"\b("
    r"scan[ _]?en(?:able)?"          # "scan enable", "scan_en", "scan_enable"
    r"|scan[ _]?chains?"             # "scan chain", "scan_chain", "scan chains"
    r"|scan[ _]?in\b|scan[ _]?out"   # "scan_in" / "scan in" / "scan_out"
    r"|scan[ _]?mode"                # "scan mode", "scan_mode"
    r"|DFT"                          # the DFT acronym
    r")\b",
    re.IGNORECASE)

# (2) jtag_tap — STATED JTAG / TAP debug port. Requires an EXACT standard / signal
#     token. "TAP" alone is too generic (a generic "tap" appears in clock/water
#     prose), so it must be "TAP controller"; the four JTAG wire names (TMS/TCK/
#     TDI/TDO) and the literal "JTAG" are each self-anchoring.
_JTAG_RE = re.compile(
    r"\b("
    r"JTAG"                          # the JTAG standard
    r"|TAP[ _]?controller"           # "TAP controller" (bare TAP excluded)
    r"|TMS|TCK|TDI|TDO"              # the four JTAG wire signals
    r")\b")

# (3) bist — STATED built-in self-test.
_BIST_RE = re.compile(
    r"\b("
    r"[ML]?BIST"                     # BIST, MBIST, LBIST
    r"|built[ _-]?in[ _-]?self[ _-]?test"
    r"|self[ _-]?test"
    r")\b",
    re.IGNORECASE)

# (4) test_mode — STATED test/debug MODE pin or signal. Each form ties the word
#     "test"/"debug" to a MODE / PORT / enable signal, so a bare "test" / "mode"
#     in unrelated prose ("test the design", "burst mode") never fires.
_TEST_MODE_RE = re.compile(
    r"\b("
    r"test[ _]?mode"                 # "test mode", "test_mode"
    r"|debug[ _]?mode"               # "debug mode", "debug_mode"
    r"|debug[ _]?port"               # "debug port", "debug_port"
    r"|test[ _]?en(?:able)?\b"       # "test_en", "test enable"
    r"|debug[ _]?en(?:able)?\b"      # "debug_en", "debug enable"
    r")\b",
    re.IGNORECASE)


# ---------------------------------------------------------------------------
# Comment stripping (so a `// JTAG` Verilog comment never seeds a feature)
# ---------------------------------------------------------------------------
def _strip_block_and_line_comments(src: str) -> str:
    out, i, n = [], 0, len(src)
    while i < n:
        two = src[i:i + 2]
        if two == "/*":
            end = src.find("*/", i + 2)
            if end == -1:
                break
            out.append(" " * (end + 2 - i))
            i = end + 2
        elif two == "//":
            end = src.find("\n", i)
            if end == -1:
                break
            out.append(" " * (end - i))
            i = end
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Empty-JSON-field blanking (a SCHEMA KEY is not a STATEMENT)
# ---------------------------------------------------------------------------
# A skeleton L-doc carries the FULL schema, so `"scan_chain": []`,
# `"jtag_tap": null`, `"dft_present": false` are present in EVERY design —
# including designs with NO DFT at all. Matching the KEY therefore FABRICATED a
# scan/JTAG/BIST requirement for every such design, contradicting this module's
# own no-fabrication promise. A requirement may only be minted from a key that
# carries a NON-EMPTY, TRUTHY VALUE — an actually-declared scan chain / TAP /
# BIST block. chip-AGNOSTIC: pure JSON shape, no design literal.
#
# `"key": <empty>` is blanked (key AND value replaced by spaces, so character
# offsets — and therefore evidence lines — are preserved). Blanking the value
# too lets a PARENT container become empty in turn (`"dft": {"scan_chain": []}`
# -> `"dft": {              }`), so the pass is applied to a FIXPOINT and a
# nested all-empty subtree cannot leave its parent key alive.
_JSON_EMPTY_FIELD_RE = re.compile(
    r'"(?:[^"\\]|\\.)*"\s*:\s*'                     # "key":
    r'(?:\[[\s,]*\]|\{[\s,]*\}|null|false|""'       # [] {} null false ""
    r'|0+(?:\.0+)?(?=\s*[,\}\]\r\n]|\s*$))',        # a zero count
    re.IGNORECASE)


def _blank_empty_json_fields(src: str) -> str:
    """Blank every `"key": <empty/false/null/zero>` JSON field, to a fixpoint.

    Length-preserving (each removed run becomes spaces) so evidence line/offset
    reporting is unaffected. Text that is not JSON is left alone: prose does not
    contain `"key": null` forms."""
    prev = None
    cur = src
    for _ in range(12):                     # fixpoint, bounded (no runaway)
        if cur == prev:
            break
        prev = cur
        cur = _JSON_EMPTY_FIELD_RE.sub(lambda m: " " * len(m.group(0)), cur)
    return cur


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------
def _evidence_line(text: str, pos: int) -> str:
    """The trimmed line of `text` containing character offset `pos` — the exact
    line the anchor token came from. chip-AGNOSTIC."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return text[start:end].strip()


def _first_match(rx: re.Pattern, text: str):
    """Return (matched_token, evidence_line) for the FIRST anchor match of `rx`
    in `text`, or None when there is no anchor (the §4.05 return-[] discipline)."""
    m = rx.search(text)
    if not m:
        return None
    return m.group(1), _evidence_line(text, m.start())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def extract(prompt_text: str) -> List[Dict]:
    """Extract the stated L7 TEST/DEBUG features from `prompt_text`.

    Returns a list of dicts (each shaped for `spec_coverage_check.ChecklistItem`):
    one item per stated, anchored test/debug feature (scan_chain / jtag_tap /
    bist / test_mode).

    §4.05 no-leak: each kind fires ONLY on its own test/debug-SPECIFIC anchor
    token (a bare verb "scan" / generic "test"/"mode" never fires). When no
    anchor is present, returns [] (no fabrication). chip-AGNOSTIC: keys on DFT /
    debug vocabulary, never a problem id."""
    if not prompt_text or not prompt_text.strip():
        return []

    # strip verilog comments so a commented-out token never seeds a feature; the
    # remaining text carries markdown + prose + live code, all of which the
    # word-boundary anchors are robust against.
    text = _strip_block_and_line_comments(prompt_text)
    # A schema KEY whose VALUE is empty/false/null states NOTHING — blank it so
    # a skeleton L-doc can never mint a scan/JTAG/BIST requirement for a design
    # that declares no DFT (the no-fabrication invariant).
    text = _blank_empty_json_fields(text)

    items: List[Dict] = []

    # (1) scan_chain
    hit = _first_match(_SCAN_RE, text)
    if hit is not None:
        tok, ev = hit
        items.append({
            "kind": "scan_chain",
            "requirement": "The design states scan / DFT test infrastructure ("
                           + tok + "); the RTL must implement the scan path and "
                           + "the TB / DFT sign-off must exercise it.",
            "evidence": ev,
            "coverage_tokens": ["scan_en", "scan_in", "scan_out", "scan_chain",
                                "DFT"],
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })

    # (2) jtag_tap
    hit = _first_match(_JTAG_RE, text)
    if hit is not None:
        tok, ev = hit
        items.append({
            "kind": "jtag_tap",
            "requirement": "The design states a JTAG / TAP debug port (" + tok
                           + "); the RTL must implement the TAP controller and "
                           + "the TB must exercise the JTAG interface.",
            "evidence": ev,
            "coverage_tokens": ["JTAG", "TAP", "TMS", "TCK", "TDI", "TDO"],
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })

    # (3) bist
    hit = _first_match(_BIST_RE, text)
    if hit is not None:
        tok, ev = hit
        items.append({
            "kind": "bist",
            "requirement": "The design states built-in self-test (" + tok
                           + "); the RTL must implement the BIST controller and "
                           + "the TB must exercise its run / done / pass-fail.",
            "evidence": ev,
            "coverage_tokens": ["BIST", "MBIST", "LBIST", "self-test"],
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })

    # (4) test_mode
    hit = _first_match(_TEST_MODE_RE, text)
    if hit is not None:
        tok, ev = hit
        items.append({
            "kind": "test_mode",
            "requirement": "The design states a test / debug mode signal (" + tok
                           + "); the RTL must implement the mode pin and the TB "
                           + "must drive the design through it.",
            "evidence": ev,
            "coverage_tokens": ["test_mode", "debug_mode", "debug_port",
                                "test_en", "debug_en"],
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })

    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="PROGRAM-FIRST structural extractor for the L7 TEST/DEBUG "
                    "facet (scan_chain / jtag_tap / bist / test_mode). "
                    "chip-AGNOSTIC, §4.05 no-leak.")
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
        print("NO STATED TEST/DEBUG FEATURE (no scan/JTAG/BIST/test-mode anchor) "
              "-> [] (no fabrication)")
        return 0

    print("TEST/DEBUG FEATURES (" + str(len(items)) + "):")
    for it in items:
        print("  - " + it["kind"] + "   [" + it["evidence"][:70] + "]")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
