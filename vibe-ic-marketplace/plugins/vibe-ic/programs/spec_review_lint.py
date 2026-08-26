#!/usr/bin/env python3
"""spec_review_lint.py — deterministic structural presence lint for a NL spec.

since v0.2.14.

ENFORCEMENT: advisory

Wiring
------
ADVISORY at flow step D1, invoked as
``spec_review_lint --strict input/docs/*.md input/docs/*.rst input/*.md``.

Two parts of that invocation are load-bearing and must not be "simplified":

  * ``--strict`` — without it every finding is a WARN and the program exits 0
    unconditionally, so a gate wired without it could never fail. It is
    therefore wired strict AND advisory, never non-strict and blocking.
  * the GLOB LIST, never a directory — measured, ``spec_review_lint .`` exits 2
    forever (a directory is not a file), which the flow reads as a permanent
    VACUOUS_PASS. Wired somewhere it can never execute is the same defect as
    not being wired.

WHY ADVISORY, AND WHAT THE PROMOTION PRECONDITION NOW MEASURES
Measured over the 16 published runs before wiring: 12 red under ``--strict``,
0 red without it, 4 vacuous (no ``input/`` at all). Of 422 WARNs, 329 (78%)
were ``corner-case-uncovered``, because that check WAS evaluated PER FILE: a
spec split across 18 chapter files scored up to 72 of them even when all four
corner cases ARE addressed by the corpus as a whole. The header named the fix
as the promotion precondition — "that check must aggregate per CORPUS rather
than per file, followed by a re-measurement".

FIXED. The corner-case checklist is now evaluated ONCE over the whole set of
documents in the invocation (`_check_corner_cases_corpus`): an item is COVERED
when ANY document addresses it, and is reported ONCE, attributed to "(corpus)"
and naming every document searched, when NO document does. Every OTHER check
keeps its per-file attribution, because only this one asks a question about the
spec as a whole. Applicability (`_CORNER_CASE_APPLICABILITY`) is judged over the
same corpus text, so an opcode table in chapter 3 gives chapter 9 an encoded
input space too. Documents are joined by a separator no checklist pattern can
match across, so two files each holding half a phrase do not cover an item.

RE-MEASUREMENT (the second half of the precondition), gate run the way the flow
runs it — ``--strict input/docs/*.md input/docs/*.rst input/*.md``, cwd = the
cell — over the nine published corpus cells, before -> after this change:

    cell                     findings   WARN    rc        cause of remainder
    caravel_user_project     36 -> 4   27 -> 4  1 -> 1    3 real, 1 tm
    edge_llm_accel           32 -> 2   24 -> 2  1 -> 1    2 real
    edge_llm_matmul_accel     4 -> 4    3 -> 3  1 -> 1    single file, unchanged
    ibex                     80 -> 20  65 -> 19 1 -> 1    17 modes, 1 real, 1 tm
    opentitan_aes            54 -> 34  50 -> 34 1 -> 1    22 modes, 8 tm, 2 sig,
    sha256                   40 -> 8   34 -> 8  1 -> 1    6 modes, 2 real
    spm                      34 -> 2   25 -> 1  1 -> 1    1 tm
    subservient              39 -> 7   30 -> 6  1 -> 1    3 real, 3 tm
    u_hawaii_adc             12 -> 4    9 -> 3  1 -> 1    3 real
    TOTAL                   331 -> 85 267 -> 80           cc-uncovered 206 -> 19

(opentitan_aes also carries 2 uncovered checklist items.  tm =
`timing-no-ref-edge`, sig = `signal-missing-attr`, modes = mode-missing-
entry/exit.)  "real" = a checklist item that NO document of that corpus addresses; the check
still says no. EIGHT OF THE NINE CELLS STILL EXIT 1, so this program stays
ADVISORY at flow step D1: the precondition for promotion is now met, but the
measurement it demanded does not license blocking — it shows the remaining red
is real, on other checks and on genuinely uncovered items.

THEN the blockquote fix below landed on top of that table, re-measured the same
way, and moved exactly two cells:

    cell          findings   WARN     rc        what went
    spm            2 -> 1    1 -> 0   1 -> 0    the blockquote status line
    subservient    7 -> 4    6 -> 3   1 -> 1    three decimal-split fragments of
                                                ONE blockquote status line
    (the other seven cells: byte-identical, and they hold no blockquote line in
    any linted document.)

spm is the first cell of the corpus to exit 0.  subservient's tm count went to
zero WITHOUT the decimal-split defect being fixed — all three of its fragments
came from one quoted line, so that defect merely lost its input here and is
still live and still recorded below.  One residual class in the remainder is a
program defect of its own, NOT a design gap, and is recorded here rather than
tuned away to make cells green:
  * `timing-no-ref-edge` on fragments produced by splitting a sentence at the
    "." inside a decimal ("slack -0.226 ns" -> "226 ns, …").  No corpus cell
    still SHOWS this one, but it is unfixed: nothing in the sentence splitter
    changed.
  * `_TIMING_STMT` treats "a latency of N clock cycles" as a timing statement
    needing a reference edge (opentitan_aes: 8 of its 34 WARNs). A latency in
    cycles has nowhere for an edge to go.
Those are separate defects with separate controls; fixing them here would be
tuning until the cells go green.

The `spec-review` skill screens a natural-language hardware spec for defects
BEFORE `/spec-to-rtl` turns the defects into RTL. Most of that review is genuine
AI judgment (ambiguity wording, suggested rewrites, internal-consistency of prose).
But the skill's checklist *also* contains a purely STRUCTURAL part — "is this
attribute declared at all?" — that is mechanical and must run identically every
time. This program extracts exactly that structural part so the agent never has
to eyeball it, and so the same spec always yields the same machine findings.

It implements EXACTLY the presence/structure items enumerated in
`skills/spec-review/SKILL.md`:

  Dimension 1 (Unambiguous)
    • every DECLARED signal has {direction, width, polarity, clock, reset}
    • every timing statement has a reference (clock) edge
  Dimension 3 (Testable)
    • every DECLARED mode has an entry AND an exit condition
  Dimension 4 (Complete corner cases) — checklist coverage, CORPUS-scoped
    (asked once of the whole set of documents in the invocation, not per file)
    • reset during operation
    • back-to-back transactions
    • full / empty / overflow / underflow
    • illegal inputs — defined vs undefined behaviour

It does NOT attempt the judgment dimensions (ambiguous-sentence detection,
suggested rewrites, prose internal-consistency, protocol/non-functional review) —
those stay with the agent per the wired SKILL.md.

Findings (verdict tiers):
  WARN (reported; fails the gate only with --strict):
    signal-missing-attr   : a declared signal is missing one of
                            {direction,width,polarity,clock,reset}.
    timing-no-ref-edge    : a timing statement has no reference clock edge.
    mode-missing-entry    : a declared mode has no entry condition.
    mode-missing-exit     : a declared mode has no exit condition.
    corner-case-uncovered : a corner-case checklist item is not addressed by
                            ANY document of the spec. Reported once for the
                            corpus, attributed to "(corpus)", naming every
                            document searched.
  INFO (reported; by construction cannot move the exit code):
    corner-case-not-applicable
                          : a corner-case checklist item did not run because
                            the structure it is about is absent from the whole
                            corpus
                            (e.g. "illegal inputs" on a design with no command /
                            opcode / encoding layer). Reported, never silent —
                            a silent skip is indistinguishable from a pass.
    spec-corpus-partial   : spec-shaped siblings were not linted.

LANGUAGE: the checks are structural, so they must recognise the FACT, not one
spelling of it. Corner-case and reference-edge detection accept the English and
the Traditional-Chinese statement of the same fact, and accept wrap semantics
stated as modulo arithmetic. A spec written in Chinese is not under-specified;
an English-only regex over it is just blind.

NO-FALSE-ALERT contract (this is a lint, not an opinion):
  • Per-signal attribute findings fire ONLY for signals that are actually
    DECLARED in an interface list (a real declaration to check against). A pure
    prose spec with no interface list yields ZERO signal findings (reported as
    SKIP), never a flood.
  • `width` is only required for signals whose declaration shows them as a vector
    (an explicit `[msb:lsb]` / "(N bits)") OR is REPORTED-PRESENT when a scalar;
    a 1-bit scalar is never flagged for "missing width".
  • `polarity` / `clock` / `reset` attributes are only required for the signal
    classes for which they are meaningful — they are detected from the signal's
    OWN declaration text and the reset/clock context, never invented.
  • Timing / mode / corner-case checks only fire when the corresponding STRUCTURE
    is present (a timing statement exists; a mode is named) — a spec that simply
    doesn't have timing or modes is not penalised for their attributes; the
    corner-case checklist is the one always-applicable coverage list, it is asked
    of the CORPUS once rather than of each file, and each uncovered item is at
    most one WARN however many files the spec is split across.
  • Unreadable / empty spec  -> MISSING (exit 2), never a crash.

chip-AGNOSTIC: detection is purely textual/structural over the spec — no IC-,
bus-, vendor-, or protocol-specific literals. Spec may be a natural-language
prompt (.txt/.md), a JSON contract (.json), or a markdown verilog header (.v/.sv).

CLI:
    python3 spec_review_lint.py <spec.md|spec.txt|spec.json|hdr.v> ...
    python3 spec_review_lint.py --spec <file> [--strict] [--json OUT]

Exit codes:
    0 = PASS   1 = (with --strict) any WARN finding   2 = no spec / parse error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from _specrtl_common import (Port, extract_spec_contract, strip_comments,
                                 _NL_PORT)
except ImportError:  # allow running from another cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _specrtl_common import (Port, extract_spec_contract, strip_comments,
                                 _NL_PORT)


# ── attribute / class detectors (chip-AGNOSTIC, structural) ─────────────────
# A clock-shaped signal name (its own declaration tells us it is a clock; clocks
# do not themselves need a clock/reset/polarity attribute).
_CLOCK_NAME = re.compile(r'\b(clk|clock|sclk|hclk|pclk|aclk|mclk|gclk)\b', re.I)
# A reset-shaped signal name (resets carry polarity but not their own clock).
_RESET_NAME = re.compile(r'\b(rst|reset|clr|clear|por|nrst|arst|srst|resetn|rst_n)\b', re.I)
# Polarity declared for a (reset / control) signal: active-high/low or _n suffix.
_POLARITY_DECL = re.compile(r'active[\s_-]*(?:high|low)|\b\w+_n\b|inverted|negated', re.I)
# A clock-domain reference in prose: "clocked by", "on the rising edge of clk", …
_CLOCK_REF = re.compile(
    r'\bclock(?:ed|\s+domain)\b|\b(?:rising|falling|posedge|negedge|positive|negative)\s+edge\b'
    r'|\bon\s+(?:the\s+)?\w*\s*(?:edge|clock|clk)\b'
    r'|\b(?:synchronous|sampled|registered)\b', re.I)
# Reference-edge for a TIMING statement.
# The spec corpus is not English-only: a reference edge stated in Traditional
# Chinese ("於上升沿取樣") is the SAME structural fact as "sampled on the rising
# edge", so both spellings must satisfy the same check. An English-only regex
# does not make a Chinese spec under-specified, it makes the checker blind.
_CJK_EDGE = (r'(?:上升|下降|正|負|前|後)(?:沿|緣)'
             r'|時脈(?:邊)?(?:沿|緣)|時鐘(?:邊)?(?:沿|緣)')
_REF_EDGE = re.compile(
    r'\b(?:rising|falling|posedge|negedge|positive|negative)\s+edge\b'
    r'|\bposedge\b|\bnegedge\b'
    r'|\b(?:on|after|relative\s+to|with\s+respect\s+to)\s+(?:the\s+)?(?:\w+\s+)?'
    r'(?:edge|clock|clk)\b'
    r'|\bclock\s+(?:edge|cycle)\b'
    + '|' + _CJK_EDGE, re.I)

# FIX 4b — DOCUMENT-LEVEL reference edge.
# `_check_signal_attrs` already honours a single global clock-domain statement
# (`clock_ref_global`) instead of demanding one per signal; a timing statement
# is governed the same way. When a document DECLARES its reference edge once —
# an explicit edge phrase, or an SDC `create_clock` that defines the timing
# reference for everything constrained against it — every timing statement in
# that document already has a reference edge, and repeating it per sentence is
# style, not structure.
#
# This is deliberately TIGHTER than `_REF_EDGE`: only an explicit edge
# declaration or an SDC clock definition anchors a whole document. Loose
# members of `_REF_EDGE` (e.g. a bare "3 clock cycles") must never anchor it,
# or one latency figure would silence the check for the entire file.
_REF_EDGE_DOC = re.compile(
    r'\b(?:rising|falling|positive|negative)\s+edge\b'
    r'|\bposedge\b|\bnegedge\b'
    r'|\bcreate_clock\b'
    + '|' + _CJK_EDGE, re.I)
# A sentence is a TIMING statement when it states a quantified timing requirement.
# NOTE: bare "hold"/"setup" are NOT timing terms (they are also plain verbs:
# "hold result", "setup the FIFO"). They only count as timing when used as the
# nouns "setup time" / "hold time" / "setup-and-hold" / "<n> ns setup", to avoid
# false-flagging an ordinary sentence that happens to contain the word.
_TIMING_STMT = re.compile(
    r'\b(?:setup|hold)\b[\s-]*(?:time|window|requirement|constraint|margin|of)\b'
    r'|\b(?:setup|hold)[\s-]+and[\s-]+(?:setup|hold)\b'
    r'|\b\d+(?:\.\d+)?\s*(?:ns|ps|us|ms)\b\s*(?:setup|hold)?'
    r'|\b(?:t_?su|t_?h|t_?co|t_?pd)\b'
    r'|\bpropagation\s+delay\b'
    r'|\b\d+(?:\.\d+)?\s*clock\s+cycles?\b'
    r'|\b(?:within|after|before)\s+\d+\s*(?:ns|ps|us|ms|clock\s+cycles?|cycles?)\b'
    r'|\b(?:propagation|setup|hold|clock-to-q)\s+latency\b', re.I)


# ── corner-case checklist (EXACTLY the four SKILL.md "Complete corner cases") ─
# Each entry: (id, human label, [synonyms each item may be addressed by]).
# A checklist item is COVERED when any synonym appears as a whole word.
#
# FIX 1 / FIX 2 — the synonym sets recognise the SUBSTANCE, not one spelling of
# it. Two ways a spec can state a checklist item that the original English-only
# word list could not see:
#   * Traditional Chinese. "reset 在計算進行中 assert" states reset-during-
#     operation exactly as "reset asserted mid-computation" does, and
#     "連續多筆乘法計算" states back-to-back transactions. A corpus written in
#     Chinese was structurally unable to cover these items — the item was
#     UNCOVERABLE, which is a checker defect, not a design gap.
#   * Mathematics. A design whose product is defined as `p = (x × y) mod 2^N`
#     has STATED its wrap semantics — modulo arithmetic IS the definition of
#     what happens on overflow. Demanding the word "overflow" beside a modulo
#     definition asks for a synonym, not for information.
# Everything added below is a different SPELLING of a fact the checklist item
# asks for. Nothing added below lets a spec that is silent on the item pass:
# each pattern still requires the item's own subject matter to be present.
_CORNER_CASES: List[Tuple[str, str, List[str]]] = [
    ("reset-during-operation", "reset during operation",
     [r"reset\s+during", r"reset\s+(?:while|in)\s+\w*\s*operation",
      r"reset\s+(?:mid|in[\s-]*flight)", r"asserted\s+during",
      r"reset\s+(?:is\s+)?(?:asserted|applied).{0,40}(?:operation|transaction|transfer|run)",
      # zh-Hant: a reset token and an operation-in-progress token, in either
      # order and close together. Both halves are required, so a spec that
      # merely mentions reset, or merely mentions "計算中", still fails.
      r"(?:reset|重置|復位|歸零)[^\n]{0,24}"
      r"(?:計算|運算|操作|傳輸|轉換|執行)[^\n]{0,4}(?:進行中|中途|途中|期間|中)",
      r"(?:計算|運算|操作|傳輸|轉換|執行)[^\n]{0,4}(?:進行中|中途|途中|期間)"
      r"[^\n]{0,24}(?:reset|重置|復位|assert|拉起)"]),
    ("back-to-back", "back-to-back transactions",
     [r"back[\s-]*to[\s-]*back", r"consecutive\s+(?:transaction|transfer|request|cycle)",
      r"(?:no|zero)\s+(?:idle|gap)\s+(?:cycle|between)", r"successive\s+\w+",
      r"pipelined?\s+(?:transaction|request|transfer)",
      # zh-Hant: a "consecutive/adjacent" token followed by the thing being
      # repeated. "連續多筆乘法計算" and "連續輸入" both match; a bare "連續"
      # with no transaction noun does not.
      r"(?:連續|接續|背靠背|相鄰|緊接)[^\n]{0,6}"
      r"(?:交易|傳輸|傳送|請求|運算|乘法|計算|輸入|輸出|操作|週期|cycle|transaction)",
      r"(?:無|零)\s*(?:間隔|空檔|idle|gap)"]),
    ("full-empty-overflow-underflow", "full / empty / overflow / underflow",
     [r"\boverflow\b", r"\bunderflow\b", r"\bfull\b", r"\bempty\b",
      r"\bsaturat", r"\bwrap[\s-]*around\b",
      # modulo arithmetic: the wrap semantics stated as mathematics.
      # `mod 2^N`, `mod 2**N`, `modulo 2^N`, `(mod 256)`, `modulo arithmetic`.
      r"\bmod(?:ulo|ulus)?\b\s*\.?\s*2\s*(?:\^|\*\*)\s*\w+",
      r"\bmodulo\s+(?:arithmetic|\d+)",
      r"\bmod\s+\d+\b",
      # zh-Hant spellings of the same statement.
      r"(?:模|取模|模數)\s*(?:運算)?\s*2\s*(?:\^|\*\*)",
      r"(?:對|以)\s*2\s*(?:\^|\*\*)\s*\w+\s*(?:取模|取餘)",
      r"模\s*2\s*(?:\^|\*\*)", r"截斷至\s*\w*\s*位元", r"回繞|環繞"]),
    ("illegal-inputs", "illegal inputs (defined vs undefined behaviour)",
     [r"\billegal\b", r"\binvalid\b", r"undefined\s+behaviou?r", r"\breserved\b",
      r"out[\s-]*of[\s-]*range", r"don'?t[\s-]*care", r"unsupported",
      r"非法|不合法|無效|保留(?:值|欄位|編碼)|未定義行為|超出範圍"]),
]


# ── FIX 3 — applicability of the illegal-inputs checklist item ───────────────
# "illegal inputs — defined vs undefined behaviour" presupposes that some input
# value CAN be illegal, i.e. that the design has an encoded input space in which
# only a subset of the code points are legal: a command word, an opcode, an
# instruction, an encoding table, a register field with enumerated values.
#
# For a design with no such layer — a pure datapath where every bit pattern of
# every data operand is a legal operand, e.g. a modulo multiplier — there is no
# illegal input to define behaviour for. Reporting the item there does not ask
# the design for missing information; it asks the design to INVENT an illegal
# input so a checker can find the word. That is a fabricated requirement, and a
# spec author who complies has made the spec worse.
#
# So the item SELF-SKIPS when the encoding layer is absent — and the skip is
# REPORTED, at INFO (which by construction cannot move the exit code), naming
# the item and the reason. A silent skip would be indistinguishable from a pass
# and would hide the fact that one quarter of the checklist did not run.
#
# Applicability is deliberately evidence-based rather than keyword-based: the
# document must both NAME an encoding layer and SHOW code points for it (a hex /
# binary / sized literal within the same neighbourhood). Naming alone is not
# enough — measured, a chapter titled "Command / Protocol Layer" whose entire
# body states that the design HAS no command layer would otherwise be judged to
# have one. A design that really does have an opcode layer enumerates its
# opcodes, and that enumeration is the evidence.
_ENCODING_LAYER_NOUN = re.compile(
    r'\bop[\s_-]?code\b'
    r'|\bcommand[\s_/-]*(?:word|code|field|byte|set|table|encoding|format|'
    r'protocol|interface|register|decoder|parser|id)\b'
    r'|\binstruction[\s_/-]*(?:set|word|encoding|format|opcode|table)\b'
    r'|\bencoding\s+table\b|\bfield\s+encoding\b'
    r'|操作碼|指令(?:集|碼|字|表|編碼)|命令(?:字|碼|集|表|編碼)|編碼表', re.I)
# A concrete code point: hex, binary, or a sized HDL literal.
_CODE_POINT = re.compile(r"0x[0-9a-f]+|0b[01]+|\b\d+'[bhdo][0-9a-fx_z]+", re.I)
# How far apart the layer noun and its code points may sit and still count as
# the same declaration.
_ENCODING_EVIDENCE_WINDOW = 400


def _has_encoded_input_layer(text: str) -> bool:
    """True when the spec DECLARES an encoded input space — a layer noun with
    concrete code points beside it. See _CORNER_CASE_APPLICABILITY."""
    points = [m.start() for m in _CODE_POINT.finditer(text)]
    if not points:
        return False
    for m in _ENCODING_LAYER_NOUN.finditer(text):
        lo = m.start() - _ENCODING_EVIDENCE_WINDOW
        hi = m.end() + _ENCODING_EVIDENCE_WINDOW
        if any(lo <= q <= hi for q in points):
            return True
    return False


# checklist id -> (applicability predicate, why-it-was-skipped wording)
_CORNER_CASE_APPLICABILITY = {
    "illegal-inputs": (
        _has_encoded_input_layer,
        "the spec declares no command / opcode / encoding layer (no encoded "
        "input space with illegal code points), so there is no illegal input "
        "for it to define behaviour for"),
}


# ── mode detection ──────────────────────────────────────────────────────────
# A declared MODE: "<Name> mode" / "in <Name> mode" / a "Mode: NAME" header.
_MODE_DECL = re.compile(
    r'\b([A-Z][A-Za-z0-9_]*(?:[\s_-][A-Z]?[A-Za-z0-9_]+)?)\s+mode\b'
    r'|\bmode\s*[:=]\s*([A-Za-z0-9_]+)', re.M)
_ENTRY = re.compile(r'\benter(?:s|ed|ing)?\b|\bentry\b|\bupon\b|\bwhen\b|\benters?\s+\w*\s*mode\b'
                    r'|\bactivat|\btransition(?:s)?\s+(?:to|into)\b|\bswitch(?:es)?\s+to\b', re.I)
_EXIT = re.compile(r'\bexit(?:s|ed|ing)?\b|\bleave(?:s)?\b|\bdeactivat'
                   r'|\btransition(?:s)?\s+(?:out|from|back)\b|\breturn(?:s)?\s+to\b'
                   r'|\buntil\b|\bclears?\b|\bdisabl', re.I)

_MIN_SPEC_CHARS = 20   # length-floor: below this there is nothing to lint

# ── denominator disclosure ──────────────────────────────────────────────────
# A caller reaches this program through a GLOB (the flow gate passes
# `input/docs/*.md input/docs/*.rst input/*.md`). A glob that matches one file
# in a directory holding eighteen spec chapters still produces a verdict, and
# the old output — "[1 spec(s) linted]" — read exactly like a verdict over the
# whole corpus. MEASURED: one published run ships 17 `.rst` spec chapters plus
# 2 `.md`; a `*.md`-only glob linted 1 of them and reported a verdict.
#
# This is a DISCLOSURE, not a threshold: the unread siblings are reported at
# INFO severity, which by construction cannot move the exit code (only ERROR,
# and WARN under --strict, do). It exists so a verdict can never again hide
# how much of the corpus produced it.
_SPEC_SUFFIXES = {".md", ".rst", ".txt", ".json", ".v", ".sv"}


@dataclass
class Finding:
    code: str
    severity: str
    message: str


# --- per-signal attribute checks -------------------------------------------
def _signal_declaration_spans(text: str) -> Dict[str, str]:
    """For each NL-declared signal, return the raw text of its declaration line
    (the structural anchor we are allowed to check attributes against). Returns
    {} when there is no interface bullet list — the no-false-alert guard that
    keeps a pure-prose spec from yielding signal findings."""
    spans: Dict[str, str] = {}
    for m in _NL_PORT.finditer(text):
        name = m.group(2)
        line_start = text.rfind('\n', 0, m.start()) + 1
        line_end = text.find('\n', m.end())
        line_end = line_end if line_end != -1 else len(text)
        spans[name] = text[line_start:line_end]
    return spans


def _check_signal_attrs(text: str, contract) -> List[Finding]:
    findings: List[Finding] = []
    spans = _signal_declaration_spans(text)
    if not spans:
        return findings  # SKIP: no interface list to check (graceful)

    low_full = text.lower()
    by_name = {p.name: p for p in contract.ports}

    # Does the spec name a clock and a reset signal anywhere? (domain anchors)
    has_named_clock = bool(_CLOCK_NAME.search(low_full))
    has_named_reset = bool(_RESET_NAME.search(low_full))
    # global clock-domain prose (covers single-domain designs once)
    clock_ref_global = bool(_CLOCK_REF.search(text))

    for name, decl in spans.items():
        port = by_name.get(name)
        decl_low = decl.lower()
        is_clock = bool(_CLOCK_NAME.search(name))
        is_reset = bool(_RESET_NAME.search(name))

        missing: List[str] = []

        # direction — required for every signal; present iff parsed as a Port.
        if port is None or not (port.direction or "").strip():
            missing.append("direction")

        # width — only meaningful/required for VECTOR (multi-bit) signals; a scalar
        # 1-bit control/clock/reset is COMPLETE without an explicit width and is
        # NEVER flagged. A signal is treated as a vector only when its name or
        # declaration carries unambiguous multi-bit intent (a "bus"/"data"/"addr"/
        # "word" component, or an opened-but-empty range) yet states NO width.
        width_present = (port is not None and port.width and port.width > 1) \
            or bool(re.search(r'\(\s*\d+\s*bits?\s*\)|\[\s*\d+\s*:\s*\d+\s*\]', decl_low))
        name_says_vector = bool(re.search(
            r'(?:^|_)(?:bus|data|addr|address|word|payload|vector|dout|din|count|cnt)'
            r'(?:_|$)', name, re.I))
        decl_says_vector = name_says_vector or bool(re.search(r'\[\s*\d', decl_low))
        if decl_says_vector and not is_clock and not is_reset and not width_present:
            missing.append("width")

        # polarity — required for signals whose meaning depends on it: reset and
        # any signal explicitly described elsewhere as active-high/low or _n.
        if is_reset:
            pol_here = bool(_POLARITY_DECL.search(decl)) or bool(name.endswith("_n"))
            # also accept polarity stated in reset context anywhere in the spec
            pol_ctx = bool(re.search(
                r'(?:%s)[^\n.]{0,60}(?:active[\s_-]*(?:high|low))'
                r'|(?:active[\s_-]*(?:high|low))[^\n.]{0,60}(?:%s)'
                % (re.escape(name), re.escape(name)), low_full))
            if not (pol_here or pol_ctx
                    or contract.reset_polarity):
                missing.append("polarity")

        # clock — every signal lives in a clock domain. A clock signal itself is
        # its own domain (skip). A reset's clock matters only for sync resets, but
        # we require the spec to state SOME clock-domain anchor for sampled signals.
        if not is_clock:
            # signal-local clock-domain mention, OR a global single-domain anchor
            sig_clock = bool(re.search(
                r'(?:%s)[^\n.]{0,80}(?:clock|clk|edge|domain|sampled|registered)'
                % re.escape(name), low_full))
            if not (has_named_clock and (sig_clock or clock_ref_global)):
                missing.append("clock")

        # reset — every stateful signal has a reset domain. We require the spec to
        # name a reset (or state the signal/domain is reset) for non-clock signals.
        if not is_clock:
            sig_reset = bool(re.search(
                r'(?:%s)[^\n.]{0,80}(?:reset|cleared|initial(?:ized|ised)?|defaults?\s+to)'
                % re.escape(name), low_full))
            if not (has_named_reset or sig_reset or is_reset
                    or contract.reset_mode or contract.reset_signal):
                missing.append("reset")

        for attr in missing:
            findings.append(Finding(
                "signal-missing-attr", "WARN",
                f"declared signal '{name}' is missing its {attr} declaration "
                f"(SKILL.md Unambiguous: every signal needs "
                f"direction/width/polarity/clock/reset)."))
    return findings


# --- timing reference-edge check -------------------------------------------
def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r'(?<=[.\n])', text) if s.strip()]


# FIX 4a — markdown block structures are not prose sentences.
# `_split_sentences` splits on "." and "\n", so every row of a markdown table
# becomes a "sentence". A PPA table row such as
#   | `sky130_fd_sc_hd` | 10 ns | met | met |
# then reads as a timing statement with no reference edge — but it is a CELL in
# a table, not a claim about when something happens, and there is nowhere in it
# for a reference edge to go. The same is true of a fenced code block (an SDC or
# HDL fragment) and of an ATX heading, which a "." inside a section number even
# splits into fragments ("### 7.4.1 Baseline …" -> "1 Baseline …").
# Dropping these lines removes a whole class of finding that no edit to the
# document could ever clear; it does NOT touch prose, where the check keeps
# firing exactly as before.
_FENCE = re.compile(r'^\s*(?:```|~~~)')
_TABLE_ROW = re.compile(r'^\s*\|')
_TABLE_RULE = re.compile(r'^\s*\|?\s*:?-{2,}')
_ATX_HEADING = re.compile(r'^\s{0,3}#{1,6}\s')
# A markdown BLOCKQUOTE is a CONTAINER for annotation, not a sentence of the
# spec: measured over the whole published corpus, every quoted line in a linted
# document is an editorial callout on the normative text above it — a baseline
# status line, a rationale, a clarification, a quoted source — never the place a
# requirement is first stated.  It is dropped for the same reason a table row and
# an ATX heading are: the marker declares the line is structure, not prose.
_BLOCKQUOTE = re.compile(r'^\s{0,3}>')


def _prose_lines_only(text: str) -> str:
    """Return `text` with the markdown block structures that are not prose
    sentences removed: fenced code blocks, table rows/rules, ATX headings,
    blockquotes.

    COST, recorded rather than hidden: a genuine requirement that happens to be
    written INSIDE a blockquote is no longer linted either.  That is the price
    of the rule, it is pinned by a test, and it is accepted because a blockquote
    is where this corpus puts annotation ABOUT a requirement, not where it
    states one."""
    out: List[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if (_TABLE_ROW.match(line) or _TABLE_RULE.match(line)
                or _ATX_HEADING.match(line) or _BLOCKQUOTE.match(line)):
            continue
        out.append(line)
    return "\n".join(out)


def _check_timing_ref_edges(text: str) -> List[Finding]:
    findings: List[Finding] = []
    # FIX 4b — a document that DECLARES its reference edge once has stated it
    # for every timing statement it contains (mirrors `clock_ref_global` in
    # `_check_signal_attrs`, which accepts one global clock-domain statement
    # instead of demanding one per signal).
    if _REF_EDGE_DOC.search(text):
        return findings
    for sent in _split_sentences(_prose_lines_only(text)):
        if _TIMING_STMT.search(sent) and not _REF_EDGE.search(sent):
            # length-floor / structural: must be a real prose sentence, not a
            # one-token fragment, before we flag it.
            if len(sent.split()) >= 4:
                snippet = sent if len(sent) <= 90 else sent[:87] + "..."
                findings.append(Finding(
                    "timing-no-ref-edge", "WARN",
                    f"timing statement has no reference clock edge: \"{snippet}\" "
                    f"(SKILL.md Unambiguous: every timing statement needs a "
                    f"reference edge)."))
    return findings


# --- mode entry/exit check --------------------------------------------------
_GENERIC_MODE = {"this", "the", "a", "an", "each", "any", "no", "single", "one",
                 "normal", "operation", "operating"}


def _declared_modes(text: str) -> List[str]:
    modes: List[str] = []
    seen = set()
    for m in _MODE_DECL.finditer(text):
        nm = (m.group(1) or m.group(2) or "").strip()
        if not nm:
            continue
        key = nm.lower()
        # deny-list: drop generic words that are not real mode names
        if key in _GENERIC_MODE or key in seen:
            continue
        # length-floor: a mode name is at least 2 chars and not a bare article
        if len(key) < 2:
            continue
        seen.add(key)
        modes.append(nm)
    return modes


def _check_modes(text: str) -> List[Finding]:
    findings: List[Finding] = []
    modes = _declared_modes(text)
    if not modes:
        return findings  # SKIP: no modes declared (graceful)
    for mode in modes:
        # window = sentences that mention this mode by name
        ctx = " ".join(s for s in _split_sentences(text)
                       if re.search(r'\b' + re.escape(mode) + r'\b', s, re.I))
        if not ctx:
            continue
        if not _ENTRY.search(ctx):
            findings.append(Finding(
                "mode-missing-entry", "WARN",
                f"mode '{mode}' has no stated entry condition "
                f"(SKILL.md Testable: every mode needs an entry condition)."))
        if not _EXIT.search(ctx):
            findings.append(Finding(
                "mode-missing-exit", "WARN",
                f"mode '{mode}' has no stated exit condition "
                f"(SKILL.md Testable: every mode needs an exit condition)."))
    return findings


# --- corner-case checklist coverage (CORPUS-scoped) -------------------------
# The other four checks ask a question about ONE document — "is this signal's
# width declared?", "does this timing sentence name an edge?" — so each keeps
# its per-file attribution. The corner-case checklist is the one item that asks
# a question about THE SPEC: "does this design say what happens on reset during
# operation?" A spec split into chapters answers that in whichever chapter owns
# the subject, and asking every chapter the same question turns one design
# question into N of them (MEASURED, see the module header).
#
# So it is evaluated ONCE over the whole set of documents in the invocation.
# An item is COVERED when ANY document addresses it; it is reported ONCE, for
# the corpus, when NO document does. Applicability (`_CORNER_CASE_APPLICABILITY`)
# is judged over the same corpus text for the same reason: an opcode table in
# chapter 3 gives chapter 9 an encoded input space too.
#
# Attribution is the corpus, and the finding names every document searched, so
# "not addressed" can never be read as "not looked for".

# Documents are joined by a separator that no checklist pattern can match
# across: the patterns are bounded either by `[^\n]` or by `\s`, and this
# separator contains a non-space, non-word character on its own line, so no
# match can begin in one document and end in the next.
_CORPUS_DOC_SEPARATOR = "\n\n%%%\n\n"


def _corpus_text(docs: List[Tuple[str, str]]) -> str:
    """The searchable text of the whole corpus: every document's cleaned text,
    joined so that no pattern can straddle a document boundary."""
    return _CORPUS_DOC_SEPARATOR.join(t for _, t in docs)


def _searched_note(docs: List[Tuple[str, str]]) -> str:
    names = [n for n, _ in docs]
    shown = ", ".join(names[:12]) + (" …" if len(names) > 12 else "")
    return f"searched all {len(names)} document(s) of the spec corpus: {shown}"


def _check_corner_cases_corpus(docs: List[Tuple[str, str]]) -> List[Finding]:
    """Evaluate the four-item checklist ONCE over the whole corpus.

    `docs` is [(display_name, cleaned_text), ...] for every linted document.
    Returns at most one finding per checklist item, whatever the file count."""
    findings: List[Finding] = []
    if not docs:
        return findings
    text = _corpus_text(docs)
    low = text.lower()
    where = _searched_note(docs)
    for cid, label, syns in _CORNER_CASES:
        # COVERED when ANY document of the corpus addresses it.
        covered = any(re.search(s, low) for s in syns)
        # An item whose PRECONDITION is absent from the WHOLE corpus self-skips,
        # VISIBLY. Coverage is still decided FIRST: a corpus that addresses the
        # item has thereby shown the item applies to it, and is never downgraded
        # to a skip. The skip is reported at INFO — which by construction cannot
        # move the exit code — naming the item and the reason, so the checklist
        # can never quietly shrink.
        applic = _CORNER_CASE_APPLICABILITY.get(cid)
        if not covered and applic is not None and not applic[0](text):
            findings.append(Finding(
                "corner-case-not-applicable", "INFO",
                f"corner case '{label}' was NOT CHECKED: {applic[1]} "
                f"({where}) "
                f"(SKILL.md Complete-corner-cases checklist item '{cid}' — "
                f"not applicable to this spec, not covered by it)."))
            continue
        if not covered:
            findings.append(Finding(
                "corner-case-uncovered", "WARN",
                f"corner case '{label}' is not addressed by any document of "
                f"the spec ({where}) "
                f"(SKILL.md Complete-corner-cases checklist item '{cid}')."))
    return findings


def _check_corner_cases(text: str) -> List[Finding]:
    """Single-document entry point, kept so a one-file spec is linted exactly
    as before: a corpus of one document."""
    return _check_corner_cases_corpus([("(spec)", text)])


# --- top-level ---------------------------------------------------------------
def lint_spec(text: str, is_json: bool = False,
              corner_cases: bool = True) -> List[Finding]:
    """Run the full structural presence lint on ONE document.

    `corner_cases=False` withholds the corner-case checklist so the caller can
    evaluate it once over the whole corpus (`_check_corner_cases_corpus`); the
    per-document checks are unaffected and keep their per-file attribution.
    The default keeps the single-document behaviour intact."""
    findings: List[Finding] = []
    contract = extract_spec_contract(text, is_json=is_json, confirm=False)
    findings.extend(_check_signal_attrs("" if is_json else text, contract))
    if not is_json:
        clean = strip_comments(text)
        findings.extend(_check_timing_ref_edges(clean))
        findings.extend(_check_modes(clean))
        if corner_cases:
            findings.extend(_check_corner_cases(clean))
    return findings


def _read_spec(path: Path) -> Tuple[str, bool]:
    text = path.read_text(errors="replace")
    return text, path.suffix.lower() == ".json"


def _unread_siblings(files: List[Path],
                     exclude: Optional[Path] = None) -> List[Path]:
    """Spec-shaped files sitting in the SAME directories as the ones we were
    given, which were not given to us. Non-recursive on purpose: the question
    is "did the caller's pattern under-select this directory?", not "is there
    a spec anywhere on disk".

    `exclude` drops this program's OWN --json report, which is `.json` and can
    land beside a spec — a report is an output, never an unread input."""
    given = {f.resolve() for f in files}
    if exclude is not None:
        try:
            given.add(exclude.resolve())
        except OSError:
            pass
    out: List[Path] = []
    for d in sorted({f.resolve().parent for f in files}):
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if (p.is_file() and p.suffix.lower() in _SPEC_SUFFIXES
                    and p.resolve() not in given):
                out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*",
                    help="Spec file(s): .txt/.md prompt, .json contract, or .v/.sv header")
    ap.add_argument("--spec", help="Spec file (alternative to positional)")
    ap.add_argument("--strict", action="store_true",
                    help="Fail (exit 1) on any WARN finding")
    ap.add_argument("--json", dest="json_out", help="Write findings as JSON to this path")
    a = ap.parse_args()

    specs = list(a.paths) + ([a.spec] if a.spec else [])
    files = [Path(s) for s in specs if Path(s).is_file()]
    if not files:
        print("spec_review_lint: MISSING — no spec file found", file=sys.stderr)
        return 2

    all_findings: List[dict] = []
    parsed = 0
    # The corner-case checklist asks a question about the SPEC, not about one
    # chapter of it, so every readable prose document is collected here and the
    # checklist is run ONCE over the lot, after this loop.
    corpus_docs: List[Tuple[str, str]] = []
    for f in files:
        try:
            text, is_json = _read_spec(f)
            if len(text.strip()) < _MIN_SPEC_CHARS:
                all_findings.append({"code": "spec-too-short", "severity": "INFO",
                                     "message": f"spec under {_MIN_SPEC_CHARS} chars — "
                                                "nothing to lint (SKIP)",
                                     "spec": str(f)})
                continue
            parsed += 1
            if not is_json:
                corpus_docs.append((str(f), strip_comments(text)))
            for fd in lint_spec(text, is_json=is_json, corner_cases=False):
                d = asdict(fd)
                d["spec"] = str(f)
                all_findings.append(d)
        except Exception as e:  # one bad spec must not crash the batch
            all_findings.append({"code": "parse-error", "severity": "ERROR",
                                 "message": str(e), "spec": str(f)})

    # Corner-case checklist — evaluated once, over the corpus.
    for fd in _check_corner_cases_corpus(corpus_docs):
        d = asdict(fd)
        d["spec"] = "(corpus)"
        all_findings.append(d)

    # Denominator disclosure — INFO only, cannot move the exit code.
    unread = _unread_siblings(
        files, Path(a.json_out) if a.json_out else None)
    if unread:
        all_findings.append({
            "code": "spec-corpus-partial", "severity": "INFO",
            "message": (
                f"{len(unread)} spec-shaped file(s) in the same directory(ies) "
                f"were NOT linted, so this verdict covers {len(files)} of "
                f"{len(files) + len(unread)} candidate spec files: "
                + ", ".join(str(p) for p in unread[:12])
                + (" …" if len(unread) > 12 else "")
                + " — widen the caller's pattern if these are part of the spec."),
            "spec": "(corpus)"})

    n_err = sum(1 for d in all_findings if d["severity"] == "ERROR")
    n_warn = sum(1 for d in all_findings if d["severity"] == "WARN")
    fail = n_err > 0 or (a.strict and n_warn > 0)
    verdict = "FAIL" if fail else "PASS"
    print(f"spec_review_lint: {verdict} — findings: {len(all_findings)} "
          f"({n_err} error, {n_warn} warn) "
          f"[{parsed} spec(s) linted of {len(files) + len(unread)} candidate(s)]")
    for d in all_findings:
        print(f"  [{d['severity']}] {d['code']}: {d['message']}")

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"verdict": verdict, "errors": n_err, "warnings": n_warn,
             "findings": all_findings}, indent=2) + "\n")

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
