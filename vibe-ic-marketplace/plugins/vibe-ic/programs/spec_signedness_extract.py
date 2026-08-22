#!/usr/bin/env python3
"""spec_signedness_extract.py — PROGRAM-FIRST per-SIGNAL signedness extractor
(chip-AGNOSTIC, §4.05 no-leak).

WHY THIS EXISTS
---------------
`spec_coverage_check.py` already carries a COARSE prose-heuristic checklist kind
for the signedness topic:

  * kind="signedness" — a single keyword hit on
        signed | unsigned | two's complement
    (one item per spec, NO named signal, NO per-operand binding, NO polarity).

That answers "is the topic MENTIONED?". It does NOT record the STRUCTURE the
author actually has to implement: WHICH specific signal/operand is signed, or
the explicit `signed` range declaration that ties a width to a NAMED port. A
verification FAILURE on an arithmetic design is — per the spec-coverage doctrine
— almost always one of OUR OWN extraction gaps (a signed operand we never read
out / never sign-extended / compared with the wrong relational operator), not
an unfixable floor: a `>` on two operands the spec called signed must be a
SIGNED comparison, and the hidden testbench exercises exactly that.

This module is the STRUCTURAL extension. It returns richer items keyed on a new
kind so a downstream consumer (or `spec_coverage_check`'s checklist) can demand
TB coverage of the *specific* signed operand rather than the topic in general:

    kind="signed_operand" — a NAMED signal/operand bound to a signedness
                            polarity (signed / unsigned), anchored to either a
                            Verilog `signed` range declaration tied to a name or
                            an explicit prose statement "<name> is signed".

EXTEND-NOT-DUPLICATE
--------------------
We do NOT re-emit the bare `signedness` keyword item — `spec_coverage_check`
still OWNS that coarse topic. We only emit the STRUCTURAL refinement it lacks: a
PER-SIGNAL signedness fact tied to a NAMED signal (or an explicit `signed` range
declaration). A consumer can union our items with spec_coverage_check's
checklist; a bare "signed arithmetic" with NO named signal yields NOTHING here
(that bare topic remains spec_coverage_check's coarse kind, not ours).

WHAT COUNTS (the §4.05 no-leak boundary)
  We emit ONLY when a NAMED signal is bound to a signedness polarity:
    * a Verilog `signed` range tied to a name — `signed [N:0] name`,
      `input signed [15:0] coeff`, or `name` declared with the `signed`
      keyword;
    * prose binding a name to signedness — "signed input X", "X is a signed
      value", "signed operand X", "treat X as signed", "two's complement X" /
      "X in two's complement".
  We do NOT emit for "unsigned" DEFAULTS — unsigned is the convention, so only a
  POSITIVE signed declaration is a fact worth carrying — EXCEPT when prose
  EXPLICITLY contrasts "X is unsigned" against a signed sibling: there the
  unsigned word is itself a deliberate, named polarity statement and MAY be
  emitted with the unsigned polarity captured. We stay conservative: an explicit
  signed/unsigned WORD must be tied to a NAME. A bare "signed arithmetic" /
  "perform a signed multiply" with NO named operand returns []. So does
  `extract("add two numbers")`.

  chip-AGNOSTIC: pure signedness grammar (the `signed` keyword shape, a
  signedness adjective bound to an identifier); NO chip / vendor / SKU /
  problem-id literal (enforced by `programs/source_chip_agnostic_check.py .`).

CONTRACT
  Each emitted dict is shaped to seed a `spec_coverage_check.ChecklistItem`:
    {
      "kind":            "signed_operand",
      "requirement":     human-readable testable requirement,
      "evidence":        the EXACT declaration / prose phrase it came from,
      "coverage_tokens": [the signal NAME, ...],   # always carries the name
      "provenance":      "STRUCTURAL",             # (default)
      "signal":          <the named signal>,
      "polarity":        "signed" | "unsigned",
      "block_eligible":  True,                     # (optional)
    }

CLI
    python3 spec_signedness_extract.py <prompt.txt> [--json]
    cat prompt.txt | python3 spec_signedness_extract.py -
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Identifier / deny-set grammar (chip-AGNOSTIC, pure structural shape)
# ---------------------------------------------------------------------------
# A signal/operand NAME: a Verilog identifier (letter/underscore start). We do
# NOT require a particular case so din / coeff / acc_q / DATA_IN all qualify.
_IDENT = r"[A-Za-z_]\w*"
_IDENT_RE = re.compile(_IDENT)

# Tokens that look like an identifier in the `signed <NAME>` slot but are NOT a
# signal name — Verilog type/qualifier words and signedness words themselves, so
# `signed integer`, `signed logic`, `signed reg`, `signed value` (no following
# name) never mint a phantom signal. chip-AGNOSTIC (generic Verilog/English).
_NON_SIGNAL_WORDS = {
    "signed", "unsigned", "integer", "int", "logic", "reg", "wire", "bit",
    "byte", "shortint", "longint", "time", "real", "value", "values", "number",
    "numbers", "operand", "operands", "input", "inputs", "output", "outputs",
    "data", "result", "arithmetic", "comparison", "multiply", "multiplication",
    "addition", "subtraction", "type", "format", "representation", "vector",
    "and", "or", "the", "a", "an", "two", "twos", "complement",
}


def _is_signal_name(tok: str) -> bool:
    """A real signal-name token: identifier-shaped, >=1 char, NOT a Verilog
    type/qualifier or a signedness word. chip-AGNOSTIC — generic deny-set, no
    design literal. This is the §4.05 guard that keeps `signed value` /
    `signed integer` from minting a phantom operand."""
    if not tok:
        return False
    if not _IDENT_RE.fullmatch(tok):
        return False
    return tok.lower() not in _NON_SIGNAL_WORDS


def _declared_signal(name: str, text: str) -> bool:
    """True iff `name` is corroborated as a REAL declared/used signal in the doc:
    a Verilog port/signal declaration, a backtick `name`, or a bus-index `name[..`.

    §4.05 NO-LEAK: a deny-set alone cannot enumerate every English noun, so a
    PROSE signedness phrase ("unsigned integers", "the unsigned add result") would
    otherwise mint a phantom operand from a common word that merely follows
    signed/unsigned. Requiring the captured token to ALSO appear as a declared /
    bracket-indexed / backtick signal kills that leak: `add`/`integers` are not
    declared signals; `coeff`/`acc`/`din` are. A Verilog `signed [..] name`
    declaration is self-corroborating and bypasses this gate (it IS a decl)."""
    esc = re.escape(name)
    return bool(
        re.search(r"`\s*" + esc + r"\s*`", text) or                       # backtick
        re.search(r"\b" + esc + r"\s*\[", text) or                        # name[..]
        re.search(r"(?:input|output|inout|wire|reg|logic)\b[^\n;]*\b"
                  + esc + r"\b", text, re.I))                              # port decl


# ---------------------------------------------------------------------------
# (A) Verilog `signed` RANGE DECLARATION tied to a NAMED signal.
# ---------------------------------------------------------------------------
# Forms (the `signed` keyword + an eventual identifier on the same declaration):
#   "signed [15:0] coeff"
#   "input signed [7:0] din"
#   "input wire signed [N-1:0] a"
#   "output reg signed [WIDTH-1:0] acc"
#   "logic signed [3:0] x"
# The range is OPTIONAL (a `signed` scalar `input signed s` is still a signed
# operand). We capture the FIRST identifier that follows `signed` (+ optional
# range + optional type/qualifier words), skipping type/qualifier deny-words.
# §4.05: the `signed` keyword MUST be present and bound to a real name.
_SIGNED_DECL_RE = re.compile(
    r"\bsigned\b"
    r"(?:\s*\[[^\]\n]*\])?"          # optional packed range [hi:lo]
    r"\s+"
    r"(" + _IDENT + r")",            # the candidate name immediately after
    re.IGNORECASE)

# Also catch the `<qualifier> signed <range> <name>` where a type word sits
# BEFORE `signed` (input/output/wire/reg/logic signed ...). The name capture is
# the same as above (it sits after `signed`), so _SIGNED_DECL_RE already covers
# it — this comment documents the coverage; no extra pattern needed.

# A name declared signed with the keyword AFTER the name is rare in Verilog but
# appears in prose-y skeletons: "coeff is declared signed", "acc, signed,".
# Handled by the prose patterns below, not here.


# ---------------------------------------------------------------------------
# (B) PROSE binding a NAME to a signedness polarity.
# ---------------------------------------------------------------------------
# (B1) "signed <kind> <NAME>" / "signed <NAME>" — adjective BEFORE the name:
#        "signed input din", "signed operand acc", "a signed value coeff".
#      We allow up to two intervening type/role words (input/operand/value/...)
#      then capture the name; the intervening words are bounded by the deny-set
#      so we land on the real identifier.
_PROSE_ADJ_BEFORE_RE = re.compile(
    r"\b(signed|unsigned)\s+"
    r"(?:(?:input|output|operand|value|number|data|port|signal|reg|wire|"
    r"logic|bus|vector)\s+){0,2}"
    r"(" + _IDENT + r")\b",
    re.IGNORECASE)

# (B2) "<NAME> is (a/an) signed ..." / "<NAME> is unsigned" — the name BEFORE an
#      "is ... signed/unsigned" predicate:
#        "operand acc is treated as two's complement",
#        "din is a signed value", "X is unsigned".
#      Capture the LAST identifier before the `is ... signed/unsigned` so a role
#      word ("operand acc is signed") lands on `acc`, not `operand`.
_PROSE_IS_SIGNED_RE = re.compile(
    r"\b(" + _IDENT + r")\s+is\s+"
    r"(?:(?:a|an|the)\s+)?"
    r"(?:(?:value|number|signal|operand|input|output)\s+)?"
    r"(?:treated\s+as\s+|interpreted\s+as\s+|represented\s+(?:as|in)\s+)?"
    r"(?:(?:a|an|the)\s+)?"
    r"(signed|unsigned|two'?s\s+complement)\b",
    re.IGNORECASE)

# (B3) "treat <NAME> as signed" / "interpret <NAME> as two's complement":
_PROSE_TREAT_RE = re.compile(
    r"\b(?:treat|interpret|consider|regard)\s+"
    r"(?:(?:the|a|an)\s+)?"
    r"(?:(?:value|operand|input|output|signal|port)\s+)?"
    r"(" + _IDENT + r")\s+as\s+"
    r"(?:(?:a|an|the)\s+)?"
    r"(signed|unsigned|two'?s\s+complement)\b",
    re.IGNORECASE)

# (B4) "two's complement <NAME>" / "<NAME> in two's complement" — two's
#      complement is a signed representation; the NAMED operand it qualifies is a
#      signed operand.
_PROSE_TWOS_BEFORE_RE = re.compile(
    r"\btwo'?s\s+complement\s+"
    r"(?:(?:input|output|operand|value|number|signal)\s+){0,2}"
    r"(" + _IDENT + r")\b",
    re.IGNORECASE)
_PROSE_TWOS_AFTER_RE = re.compile(
    r"\b(" + _IDENT + r")\s+(?:is\s+|are\s+|,\s*)?"
    r"in\s+two'?s\s+complement\b",
    re.IGNORECASE)


def _norm_polarity(word: str) -> str:
    """Map a matched signedness word to a normalized polarity tag. Two's
    complement is a SIGNED representation. chip-AGNOSTIC."""
    w = word.strip().lower()
    if w.startswith("unsigned"):
        return "unsigned"
    return "signed"   # "signed" or "two's complement"


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------
def _collect(text: str) -> List[Tuple[str, str, str]]:
    """Return [(signal_name, polarity, evidence)] for every EXPLICIT per-signal
    signedness binding. De-duplicated by (signal, polarity); the FIRST evidence
    is kept. §4.05: only a NAMED signal bound to a signedness word is emitted —
    a bare topic mention with no name yields nothing here."""
    found: Dict[Tuple[str, str], str] = {}

    def _add(name: str, polarity: str, evidence: str,
             corroborate: bool = False) -> None:
        nm = name.strip().strip("`*")
        if not _is_signal_name(nm):
            return
        # §4.05: a PROSE-derived name must be corroborated as a real declared/used
        # signal (a Verilog `signed [..] name` decl is self-corroborating and
        # passes corroborate=False). This drops phantom common-noun operands
        # ("unsigned integers", "the unsigned add") that no deny-set can enumerate.
        if corroborate and not _declared_signal(nm, text):
            return
        key = (nm, polarity)
        if key not in found:
            found[key] = evidence.strip()[:140]

    # (A) Verilog `signed [range] name` declarations — always signed polarity
    #     (the keyword `signed` is, by definition, a positive signed assertion).
    #     Self-corroborating: the match IS a declaration.
    for m in _SIGNED_DECL_RE.finditer(text):
        _add(m.group(1), "signed", m.group(0))

    # (B1..B4) PROSE bindings — corroborate the captured NAME against a real decl.
    # (B1) "signed/unsigned <role> <name>"
    for m in _PROSE_ADJ_BEFORE_RE.finditer(text):
        _add(m.group(2), _norm_polarity(m.group(1)), m.group(0), corroborate=True)

    # (B2) "<name> is ... signed/unsigned/two's complement"
    for m in _PROSE_IS_SIGNED_RE.finditer(text):
        _add(m.group(1), _norm_polarity(m.group(2)), m.group(0), corroborate=True)

    # (B3) "treat/interpret <name> as signed/unsigned/two's complement"
    for m in _PROSE_TREAT_RE.finditer(text):
        _add(m.group(1), _norm_polarity(m.group(2)), m.group(0), corroborate=True)

    # (B4) "two's complement <name>" / "<name> in two's complement"
    for m in _PROSE_TWOS_BEFORE_RE.finditer(text):
        _add(m.group(1), "signed", m.group(0), corroborate=True)
    for m in _PROSE_TWOS_AFTER_RE.finditer(text):
        _add(m.group(1), "signed", m.group(0), corroborate=True)

    return [(nm, pol, ev) for (nm, pol), ev in found.items()]


# ===========================================================================
# Public API
# ===========================================================================
def extract(prompt_text: str) -> List[dict]:
    """Extract structural PER-SIGNAL signedness facts from a CVDP-style prompt.

    Returns a list of dicts (one per explicit named-signal signedness binding).
    Each dict carries: kind, requirement, evidence, coverage_tokens (the signal
    NAME), provenance (default "STRUCTURAL"), signal, polarity, block_eligible.

    §4.05 no-leak: emits ONLY when a NAMED signal is bound to a signedness
    polarity (a `signed` range declaration tied to a name, or explicit prose
    "<name> is signed" / "treat <name> as signed" / "two's complement <name>").
    A bare "signed arithmetic" with NO named signal returns [] (that coarse
    topic is spec_coverage_check's kind="signedness", not ours). chip-AGNOSTIC.
    """
    if not prompt_text or not isinstance(prompt_text, str):
        return []

    items: List[dict] = []
    for name, polarity, evidence in _collect(prompt_text):
        req = (f"operand {name} is declared {polarity}; the design must treat "
               f"{name} as a {polarity} value (sign-extension / "
               f"{'signed' if polarity == 'signed' else 'unsigned'} "
               f"comparison / arithmetic) and the TB must exercise it with "
               f"{polarity}-relevant stimulus"
               + (" (negative / sign-boundary values)"
                  if polarity == "signed" else "") + ".")
        items.append({
            "kind": "signed_operand",
            "requirement": req,
            "evidence": evidence,
            "coverage_tokens": [name],
            "provenance": "STRUCTURAL",
            "signal": name,
            "polarity": polarity,
            "block_eligible": True,
        })
    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="PROGRAM-FIRST per-signal signedness extractor "
                    "(named signed/unsigned operands). chip-AGNOSTIC, "
                    "§4.05 no-leak.")
    ap.add_argument("prompt", help="prompt file ('-' for stdin)")
    ap.add_argument("--json", action="store_true",
                    help="emit the raw checklist-item list as JSON")
    args = ap.parse_args(argv)

    try:
        if args.prompt == "-":
            text = sys.stdin.read()
        else:
            with open(args.prompt, "r", encoding="utf-8",
                      errors="replace") as fh:
                text = fh.read()
    except OSError as e:
        print("error: cannot read prompt: " + str(e), file=sys.stderr)
        return 2

    items = extract(text)
    if args.json:
        print(json.dumps(items, indent=2))
        return 0

    if not items:
        print("NO PER-SIGNAL SIGNEDNESS (no named signal bound to "
              "signed/unsigned) -> [] (no fabrication; bare 'signed "
              "arithmetic' is spec_coverage_check's coarse kind)")
        return 0

    print("SIGNED OPERANDS (" + str(len(items)) + "):")
    for it in items:
        print("  - " + it["signal"] + " [" + it["polarity"] + "]   ["
              + it["evidence"][:70] + "]")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
