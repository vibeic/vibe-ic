#!/usr/bin/env python3
"""spec_coverage_check.py — ORGANIC #697 [P1, chip-AGNOSTIC]

SPEC-FIRST COVERAGE ATTRIBUTION across the WHOLE INPUT CHAIN. A hidden scoring
testbench is generated from the SAME specification the author sees, so
everything the scorer checks is — by construction — a SUBSET of the spec UNLESS
the benchmark couples to something the spec never states. It follows that a
verification FAILURE is almost always ONE OF OUR OWN GAPS, not an unfixable
floor.

"SPEC" IS THE ENTIRE INPUT CHAIN — a requirement is "in spec" if it exists at
ANY station:

    input prompt (USER)
      -> structured input data / fact graph (IC EXPERT AGENT, plain-language register)
        -> input Design Documents / L1-L23 (IC EXPERT AGENT)
          -> spec-to-rtl authoring (RTL)

TWO-BRANCH attribution, extended across the whole chain — the program names
WHICH station last held the requirement so the fix routes to the right place:

  (1) SPEC-EXTRACTION GAP — the requirement EXISTS somewhere in the chain but
      was not carried end-to-end. Report the LAST station that still held it:
        * USER prompt had it but the fact graph didn't  -> route: enhance
          IC EXPERT AGENT elicitation (ic-expert-agent, plain-language register);
        * fact graph had it but the L-docs didn't        -> route: enhance
          IC-EXPERT doc completion (ic-expert-agent);
        * L-docs / prompt had it but spec-to-rtl didn't read it out -> route:
          enhance SPEC-TO-RTL extraction (spec-to-rtl).
  (2) TESTBENCH-COVERAGE GAP — we DID extract it, but our own self-testbench
      never exercised it, so the bug passed our gate and only the hidden TB
      caught it. Fix: enhance our TB coverage.

FLOOR is allowed ONLY when the TB-tested thing is NOWHERE in the entire input
chain (white-box internal name / cross-problem convention / unstated value) —
and then the verdict MUST carry evidence (which stations were searched + not
found).

This program is the AUTOMATIC, PROGRAM-FIRST realisation of that doctrine: it
fires deterministically rather than relying on an agent remembering the rule.

WHAT IT DOES
  INPUT : one or more input-chain stations — `--prompt` (USER), `--fact-graph`
          (IC Expert Agent structured input), `--ldocs` (IC-expert L1-L23). `--spec`
          is an alias for the prompt (back-compat). Plus optionally the authored
          `--rtl` and `--tb`.
  STEP 1: extract from EACH station a COMPLETE checklist of testable
          requirements (DETERMINISTIC, pure-structural):
            - every port behavior / width / direction;
            - reset value & polarity & sync/async;
            - every stated timing / latency;
            - every table row (opcode/mode -> output);
            - every worked example (in == out pair);
            - every ENUMERATED SET *plus* its outside-the-set / default
              boundary item (the most-missed pattern in the #697 evidence);
            - signed-ness; bit/byte order & packing; overflow / saturation /
              rounding; handshake / protocol timing.
          Identical requirements found at several stations are MERGED; each item
          records the stations it was found at + the LAST (most-downstream) one.
  STEP 2: for each checklist item, attribute whether the authored TESTBENCH
          exercises it (coverage attribution). A spec requirement with no
          covering assertion is a TESTBENCH-COVERAGE GAP -> reported (WARN
          default, BLOCK in --strict sole-emit).
  STEP 3 (--failure ...): on a verification FAILURE, attribute the failing
          behavior to coverage-gap / extraction-gap (naming the last chain
          station + the routing target) / spec-absent (FLOOR, with the searched
          stations as cited evidence).

JUDGMENT BOUNDARY (honest, documented — NOT faked in the program)
  The PURE-STRUCTURAL parts above (tables, worked examples, port list,
  enumerated sets, reset/latency keyword facts) and the per-station routing are
  DETERMINISTIC and belong in this program. The residual READING judgment —
  "does THIS prose sentence state a testable requirement" — is the LLM step,
  documented in skills/spec-to-rtl, skills/benchmark-verify,
  skills/open-benchmark-methodology + agents/ic-expert-agent.
  This program never fabricates a requirement out of free prose: every emitted
  checklist item is anchored to a structural feature (a `{...}` / table /
  example / explicit reset|latency keyword), so a white-box internal name the
  chain never states is NOT charged as our gap (the §4.05 no-leak guarantee).

chip-AGNOSTIC: structural chain/RTL/TB parse + regex/table/enumerated-set
extraction; NO chip / vendor / SKU literal (enforced by
`programs/source_chip_agnostic_check.py .`).

CLI
    python3 spec_coverage_check.py
        (--spec PROMPT | --prompt PROMPT)        # USER station (alias)
        [--fact-graph FG]                        # IC Expert Agent structured input
        [--ldocs LDOCS]                          # IC-expert L1-L23 (file or dir)
        [--rtl RTL] [--tb TB]
        [--failure TEXT] [--strict] [--json OUT]

Exit codes
    0  no testbench-coverage gap (or advisory only, non-strict)
    1  >=1 testbench-coverage gap and --strict  (sole-emit BLOCK)
    2  argument / I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

# Reuse the canonical Spec<->RTL parsing primitives (ports, reset, comment
# stripping). Keep confirm=False: this program does the STRUCTURAL extraction;
# the LLM prose-reading residual is documented in the skills, not run here.
try:
    import _specrtl_common as _SRC
except ImportError:  # packaged
    from . import _specrtl_common as _SRC  # type: ignore

try:
    import _provenance as _prov  # ORGANIC #770
except ImportError:  # packaged
    from . import _provenance as _prov  # type: ignore

try:
    from _prose_polarity import is_denied as _prose_is_denied
except ImportError:  # packaged
    from ._prose_polarity import is_denied as _prose_is_denied  # type: ignore

# CVDP enhance — program-first STRUCTURAL extractors for the four artifact classes
# the legacy checklist extractor missed (register-map, enumerated-mode literal map +
# outside-set boundary, FSM transition graph, worked-example I/O pairs, rounding/
# packing semantics). Each exposes extract(text)->[dict] with ChecklistItem fields;
# they are §4.05-conservative (only structural-anchored items, [] otherwise).
_CVDP_EXTRACTORS = []
for _modname in ("spec_regmap_extract", "spec_enumset_extract", "spec_fsm_extract",
                 "spec_numeric_pack_extract", "spec_worked_example_extract",
                 # GENERAL L-doc facet extractors (close the Phase-1 completeness
                 # gaps the survey found: L5 analog/digital interface, L7 test/debug,
                 # L11 OTP, L13 lab calibration, per-signal signedness, clock-freq +
                 # electrical). Each is §4.05-conservative (structural-anchored only,
                 # [] otherwise) and benchmark-agnostic — they enrich the spec-coverage
                 # checklist for ANY design doc, not just a benchmark record.
                 "spec_analog_iface_extract", "spec_test_debug_extract",
                 "spec_otp_extract", "spec_calibration_extract",
                 "spec_signedness_extract", "spec_electrical_extract"):
    try:
        _CVDP_EXTRACTORS.append(__import__(_modname))
    except Exception:  # extractor not present in this checkout -> skip silently
        pass

# ORGANIC #770 — checklist kinds whose evidence is a FREE-PROSE keyword/regex
# (low confidence) vs a real structural source. STRUCTURAL kinds (a real markdown
# table row, a given-code port header) keep their historical blocking power; a
# PROSE_HEURISTIC kind's coverage gap blocks only when the RTL corroborates it.
_PROSE_HEURISTIC_KINDS = frozenset({
    "reset", "latency", "enum_boundary", "worked_example",
    "signedness", "byte_order", "overflow", "handshake", "enum_set",
    # GENERAL L-doc facet kinds (additive coverage; non-blocking unless the RTL
    # corroborates them) from the L5/L7/L11/L13/signedness/electrical extractors.
    "analog_converter", "reference_voltage", "analog_pad",
    "scan_chain", "jtag_tap", "bist", "test_mode",
    "otp_field", "otp_lock",
    "calibration_field", "calibration_procedure",
    "signed_operand",
    "clock_frequency", "supply_voltage", "current_spec",
    "temperature_range", "slew_rate",
})
# 'port' and 'table_row' come from the canonical structural extractor
# (`extract_spec_contract`: real table / given-code header), so they stay
# STRUCTURAL — EXCEPT a prose-derived port name that is ABSENT from the RTL (a
# phantom scraped from prose), which is provenance-downgraded in run().


# ---------------------------------------------------------------------------
# Input-chain stations — ordered USER -> PM -> IC-EXPERT (most-downstream last).
# The "last station that still held a requirement" routes the extraction-gap fix
# (a requirement present upstream but dropped before a downstream station means
# THAT downstream station dropped it).
# ---------------------------------------------------------------------------
STATION_ORDER = ["user_prompt", "fact_graph", "l_docs"]
# Routing target for an extraction-gap whose LAST holding station is <key>:
# the next station downstream is the one that DROPPED it.
STATION_ROUTE = {
    "user_prompt": ("ic-expert-agent",
                    "USER prompt stated it but the fact graph dropped it — "
                    "enhance IC Expert Agent elicitation (plain-language register)"),
    "fact_graph": ("ic-expert-agent",
                   "fact graph held it but the L-docs dropped it — "
                   "enhance IC-expert L-doc completion"),
    "l_docs": ("spec-to-rtl",
               "L-docs / prompt held it but spec-to-rtl didn't read it out — "
               "enhance spec-to-rtl extraction"),
}


def _last_station(stations: List[str]) -> str:
    """Most-downstream station (by STATION_ORDER) that still held the item."""
    present = [s for s in STATION_ORDER if s in stations]
    return present[-1] if present else (stations[-1] if stations else "user_prompt")


# ---------------------------------------------------------------------------
# Checklist item — one testable spec requirement + its TB coverage attribution
# ---------------------------------------------------------------------------
@dataclass
class ChecklistItem:
    kind: str                       # port / reset / latency / table_row /
                                    # worked_example / enum_set /
                                    # enum_boundary / signedness / byte_order /
                                    # overflow / handshake
    requirement: str                # human-readable testable requirement
    evidence: str                   # the structural spec fragment it came from
    covered: Optional[bool] = None  # True/False (None until attributed)
    coverage_note: str = ""         # how coverage was decided
    # the tokens a TB must touch to be considered covering this item
    coverage_tokens: List[str] = field(default_factory=list)
    # input-chain stations this requirement was found at + the most-downstream
    stations: List[str] = field(default_factory=list)
    last_station: str = ""
    # ORGANIC #770 — provenance/confidence gate. STRUCTURAL items (real markdown
    # table row / given-code port header / measured fact) always BLOCK when
    # uncovered. A PROSE_HEURISTIC item (free-prose keyword/regex) BLOCKs only
    # when the RTL corroborates it; a prose item the RTL CONTRADICTS or does not
    # structurally back is ADVISORY (a coverage GAP is reported but does not
    # hard-block under --strict). Default STRUCTURAL (fail-closed: an un-tagged
    # item keeps its historical blocking power).
    provenance: str = "STRUCTURAL"
    block_eligible: bool = True
    advisory_note: str = ""
    # ORGANIC #770 r2 — an enum_set whose `{...}` is a single-signal packed-vector
    # CONCATENATION literal (`sig = {a,b,c}`) is NOT an enumerated value set; the
    # extractor records that structural fact here so run() downgrades it to
    # advisory (CONTRADICTED). Default False (a genuine value set stays blocking).
    is_concat_literal: bool = False
    # ORGANIC #780 (#770 r7, R8C1) — a worked_example match that is NOT a real
    # in->out DATA pair but a STRUCTURAL ARTIFACT of the surrounding Verilog /
    # notation:
    #   * the LHS digit is the numeric suffix of an identifier (GRANT_2, STATE_3);
    #   * the RHS digit is the bit-WIDTH field of a sized literal (3'b010);
    #   * a binary-nibble = its-own-decimal-value notational gloss ("0101 = 5",
    #     a per-digit decomposition of ONE example, not an independent vector).
    # The extractor records this so run() tags the gap NO_CORROBORATION -> advisory
    # (the prose-heuristic worked_example has no structural backing as a data
    # pair). Default False (a genuine in->out example stays blocking). chip-AGNOSTIC.
    we_structural_artifact: bool = False


# ---------------------------------------------------------------------------
# Enumerated-set + outside-the-set/default boundary
# ---------------------------------------------------------------------------
# An explicit enumerated set: `{0x1,0x2,0x3}`, `{IDLE, RUN, DONE}`, `{1,2,3}`.
# Brace-delimited list of >=2 comma-separated members. This is the textbook
# #697 pattern: the set is listed, the OUTSIDE-the-set/default path is stated
# but our TB never tested an outside-the-set value.
_ENUM_SET_RE = re.compile(r"\{([^{}]+)\}")
# A "default / otherwise / any other / else -> RESULT" boundary clause.
_DEFAULT_CLAUSE_RE = re.compile(
    r"\b(any\s+other|all\s+other|otherwise|else|default|invalid|unlisted|"
    r"not\s+(?:in\s+the\s+set|listed)|outside\s+the\s+set)\b"
    r"[^.;\n]*?"
    r"(?:->|→|=>|\bgives?\b|\byields?\b|\bproduces?\b|\bbecomes?\b|\bmaps?\s+to\b|=)"
    r"\s*([^.;\n]+)",
    re.I)


def _split_enum_members(blob: str) -> List[str]:
    members = []
    for raw in re.split(r"[,、;]", blob):
        m = raw.strip()
        # only ACCEPT value-shaped members: hex / dec / bin literal, or a
        # bare identifier (mode/opcode name). Reject prose ("a list of things")
        # so a `{...}` that is really an English set-builder phrase doesn't
        # masquerade as an enumerated value set.
        if re.fullmatch(r"(0[xXbB][0-9A-Fa-f_]+|\d+|\d+'[bdh][0-9A-Fa-fxXzZ_]+|[A-Za-z_]\w*)", m):
            members.append(m)
    return members


_VALUE_MEMBER_RE = re.compile(
    r"(0[xXbB][0-9A-Fa-f_]+|\d+|\d+'[bdh][0-9A-Fa-fxXzZ_]+)")
# An explicit "enumerated VALUE set" context that licenses an identifier-only
# brace-list (e.g. "mode in {IDLE, RUN, DONE}", "one of {A, B, C}",
# "valid states {S0, S1}"). Without such a context an identifier-only `{...}`
# is, far more often, a Verilog bit-field CONCATENATION ({E7,...,E0}, {a,b,c})
# or a code expression — NOT an enumerated value set the TB must cover member
# by member. chip-AGNOSTIC: pure set-builder grammar, no design literal.
_SET_CONTEXT_RE = re.compile(
    r"\b(one\s+of|any\s+of|each\s+of|member\s+of|in\s+(?:the\s+)?set|"
    r"valid\s+(?:value|values|state|states|mode|modes|enum\w*)|"
    r"enumerat\w*|\bstate\s*=|\bmode\s+in\b|\bopcode\s+in\b)\b",
    re.I)
# ORGANIC-20260618 (hamming_code_tx_and_rx_0003) — the OBJECT-GOVERNING membership
# markers (`one of` / `any of` / `each of` / `member of` / `in (the) set`) license
# an identifier-only brace as an enumerated value set ONLY when the brace is the
# OBJECT of the phrase (`one of {A,B,C}`). The shipped `_SET_CONTEXT_RE` matched
# these anywhere in the ±window, so `{c1, c2, c3}:` immediately followed by
# "- Result of 1 in any of the bits" (where "any of" governs "the bits", not the
# brace) wrongly promoted a Verilog SIGNAL concatenation to a value enum and
# demanded per-member TB coverage of identifiers c1/c2/c3. These markers are now
# accepted only when they directly PRECEDE the brace (object-of-membership). The
# DESCRIPTIVE markers (valid values / enumerat / state= / mode in / opcode in)
# keep the window search — they describe the set without needing to govern it.
_SET_OBJECT_GOVERN_RE = re.compile(
    r"(?:"
    r"\b(?:one|any|each|member|some)\s+of\b"
    # optional determiners/qualifiers (Step-2.7 #27: `one of the modes {…}`,
    # `one of: {…}`, `one of the following codes: {…}` are genuine pre-brace
    # enums the shipped anchor dropped — broaden WITHOUT re-admitting the
    # post-brace `{c1,c2,c3} … any of the bits` FP, which lives AFTER the brace
    # and so never appears in this pre-brace window).
    r"(?:[\s:=]+(?:the|a|an|any|these|those|its|all|valid|legal|allowed|"
    r"permitted|possible|following|defined|supported|distinct))*"
    # optional explicit set-enumeration noun directly before the brace
    r"(?:[\s:=]+(?:modes?|values?|states?|commands?|opcodes?|codes?|options?|"
    r"choices?|symbols?|levels?|types?|colou?rs?|elements?|items?|entries|"
    r"entry|sets?))?"
    r"[\s:=]*"
    r"|\bin\s+(?:the\s+)?set\s+(?:of\s+)?"
    r"(?:modes?|values?|states?|codes?|options?)?[\s:=]*"
    r")$",
    re.I)
# Step-2.7 #27 (LOW): a POST-brace enumeration phrase governs the brace ONLY when
# it names a VALUE-set noun (`{RED,GREEN,BLUE} … any of the three colors`) — never
# a signal/structural noun (`{c1,c2,c3} … any of the bits`, the hamming concat).
# Window-searched (like the descriptive markers); the value-noun requirement is
# what separates a real value enum from a Verilog concatenation.
_SET_VALUE_NOUN_WINDOW_RE = re.compile(
    r"\b(?:one|any|each|all|member)\s+of\s+(?:the\s+)?(?:\w+\s+){0,2}?"
    r"(?:modes?|values?|states?|commands?|opcodes?|codes?|options?|choices?|"
    r"symbols?|levels?|colou?rs?|categor\w+|kinds?)\b",
    re.I)
# Legacy (no pre-brace position): the object-governing markers anywhere in the
# window. Used only by direct unit callers that don't pass pre_context.
_SET_OBJECT_GOVERN_WINDOW_RE = re.compile(
    r"\b(?:one\s+of|any\s+of|each\s+of|member\s+of|in\s+(?:the\s+)?set)\b",
    re.I)
_SET_DESCRIPTIVE_RE = re.compile(
    r"\b(valid\s+(?:value|values|state|states|mode|modes|enum\w*)|"
    r"enumerat\w*|\bstate\s*=|\bmode\s+in\b|\bopcode\s+in\b)\b",
    re.I)
# ORGANIC #770 r2 Step-2.7 — additional value-SET vocabulary that marks a brace
# list as an ENUMERATION (each member a distinct legal value), so a compactly
# written `NAME = {v1, v2, ...}` is NOT downgraded as a packed-concat literal.
# ORGANIC #770 r3 — NARROWED to STRONG set-membership markers only. The r2 set
# included weak DSP/filter vocabulary ("discrete/calibrated levels", "selectable")
# that appears in coefficient/tap specs WITHOUT meaning an enumerated dispatch
# set — so a single-signal packed concatenation `data_in = {6'b…, 6'b…}` in a
# "configurable low-pass filter" spec was wrongly KEPT as a value-set and
# hard-blocked (configurable_digital_low_pass_filter_0001). A genuine value set
# is marked by EXPLICIT membership / outside-the-set semantics: "any other value
# is reserved/illegal", "one of", "accepts only", "each of these must be
# handled", "legal/allowed values". A bare `name = {fields}` with none of those
# is a concatenation → downgrade.
_ENUM_VALUE_CTX_RE = re.compile(
    r"\b(any\s+other\s+value|otherwise\s+(?:reserved|illegal|invalid)|"
    r"\bis\s+reserved\b|\bis\s+illegal\b|legal\s+values?|allowed\s+values?|"
    r"accepts?\s+only|"
    # "(all of / each of / these …) must be handled" — r3 Step-2.7: the prior arm
    # required an "each" prefix, so "All of these states must be handled" /
    # "These modes must be handled" slipped through and a real value-set
    # downgraded to advisory. Match the membership clause with an OPTIONAL
    # leading quantifier and an optional noun between it and "must … handled".
    r"(?:all|each|these|every)\s+(?:of\s+(?:these|the)\s+)?(?:\w+\s+)?"
    r"must\s+(?:be\s+)?handled|"
    r"must\s+(?:be\s+)?handled|"
    r"each\s+of\s+these\s+(?:values?|modes?|states?)|"
    r"one\s+of\s+(?:the\s+)?(?:following|these))\b",
    re.I)


def _is_value_enum(member_blob: str, members: List[str], context: str,
                   pre_context: Optional[str] = None) -> bool:
    """Decide whether a brace-list `{...}` is a genuine enumerated VALUE set
    (member-by-member TB coverage is testable) versus a Verilog CONCATENATION /
    code expression that merely shares the `{...}` shape.

    Accept when ANY member is a value-shaped literal (hex/dec/bin) — a real
    value set. An identifier-ONLY brace-list is accepted in two cases:
      * a DESCRIPTIVE set marker (valid values / enumerat / mode in / …) anywhere
        in the surrounding window; OR
      * an OBJECT-GOVERNING membership phrase (one of / any of / each of / member
        of / in the set) that directly PRECEDES the brace (the brace is its
        object: `one of {A,B,C}`).
    Otherwise it is treated as a concatenation/expression and NOT charged as an
    enum requirement (the decoder_0011 {E7..E0} output-assembly false positive;
    the hamming {c1,c2,c3} signal-concat false positive)."""
    if any(_VALUE_MEMBER_RE.fullmatch(m) for m in members):
        return True
    if _SET_DESCRIPTIVE_RE.search(context):
        return True
    # Step-2.7 #27 (LOW): a post-brace enumeration over a VALUE-set noun ("…any of
    # the three colors") governs the brace — but a structural noun ("…any of the
    # bits", the concat) does not. Window-searched, value-noun-gated.
    if _SET_VALUE_NOUN_WINDOW_RE.search(context):
        return True
    if pre_context is None:
        # Legacy API (no brace position supplied): fall back to the historical
        # window search for ANY object-governing marker in the context. The
        # production call site below always supplies pre_context and gets the
        # stricter pre-brace anchoring that fixes the post-brace 'any of the bits'
        # FP — so this branch only preserves back-compat for direct unit callers.
        return bool(_SET_OBJECT_GOVERN_WINDOW_RE.search(context))
    # object-governing markers must directly precede the brace (pre-brace text)
    return bool(_SET_OBJECT_GOVERN_RE.search(pre_context))


# ---------------------------------------------------------------------------
# Reset / latency facts (delegated to _specrtl_common, augmented for shorthand)
# ---------------------------------------------------------------------------
# _specrtl_common._detect_reset misses the common shorthand "sync"/"async" and
# "1-cycle latency". #697's own acceptance spec uses BOTH ("Reset active-high
# sync", "1-cycle latency"). Augment here so the checklist is COMPLETE — the
# whole point of the doctrine is that extraction must not silently miss an
# in-spec requirement.
_SYNC_SHORTHAND = re.compile(r"\bsync(?:hronous(?:ly)?)?\b", re.I)
_ASYNC_SHORTHAND = re.compile(r"\basync(?:hronous(?:ly)?)?\b", re.I)
_LATENCY_RE = re.compile(
    r"\b(\d+)\s*[- ]?(?:clock\s+)?cycle(?:s)?\b(?:\s+(?:of\s+)?latency)?"
    r"|\blatency\s+of\s+(\d+)\s*[- ]?(?:clock\s+)?cycle(?:s)?\b"
    r"|\bregistered\b|\bone[- ]clock[- ]cycle\b|\bsingle[- ]cycle\b",
    re.I)


def _reset_context(text: str) -> str:
    low = text.lower()
    return " ".join(
        s for s in re.split(r"(?<=[.\n;])", low)
        if "reset" in s or re.search(r"\bpor\b", s)) or ""


def _detect_reset_mode_polarity(text: str):
    """Return (mode, polarity) including the sync/async SHORTHAND that
    _specrtl_common misses. mode in {synchronous, asynchronous, None};
    polarity in {active-high, active-low, None}."""
    mode, polarity, _signal = _SRC._detect_reset(text)
    rctx = _reset_context(text)
    if mode is None and rctx:
        if _ASYNC_SHORTHAND.search(rctx):
            mode = "asynchronous"
        elif _SYNC_SHORTHAND.search(rctx):
            mode = "synchronous"
    return mode, polarity


# A reset-shaped PORT NAME (whole-identifier), used to derive reset COVERAGE
# TOKENS from the design's actual reset port(s) instead of a fixed
# ['reset','rst','por'] list. The shipped gate hard-coded those three tokens and
# matched them with `\b<tok>\b`, so the dominant sync/async-reset naming
# conventions never matched: `\brst\b` fails inside `rst_in` / `rst_n` / `srst`
# (the `_`/adjacent letter kills the word boundary) and `clr`/`sclr` matched
# nothing. A TB that faithfully drives the design's real reset port was scored
# UNCOVERED (decoder_0001 `rst_in`, Muller_C `srst`/`clr`, gaussian_div `rst_n`).
# The stem is bound to an identifier delimiter (start / `_` / trailing n|ni|digit)
# so it matches rst/reset/clr/clear/por/srst/sclr conventions but NOT unrelated
# identifiers that merely contain the letters (first / burst / worst).
# chip-AGNOSTIC: generic reset-naming grammar, no design / vendor / SKU literal.
#
# #759 — AMBA bus-prefixed ACTIVE-LOW reset convention. The stem above is
# anchored to start-or-`_`, so a reset stem GLUED to a short bus / clock-domain
# prefix with NO delimiter is rejected: APB `presetn`/`preset_n`/`PRESETn`
# (= p+reset), AHB `hresetn`/`hreset_n`, plus generic `sresetn`/`coreresetn`
# all read as p|h|...+reset and break the `(?:^|_)` boundary, so
# `_rtl_reset_ports` returned [] and a TB faithfully driving the design's real
# reset port was scored UNCOVERED (every APB peripheral uses PRESETn). The two
# extra branches below match a short (1-4 char) bus/domain prefix glued to a
# reset/rst stem ONLY WHEN it carries the active-low `n` suffix (`reset_?n` /
# `rst_?n`); that n-suffix is the noun-disambiguator that keeps real resets
# (presetn/hresetn/sresetn) distinct from the noun `preset`/`preset_value`/
# `prescaler`/`present`/`pre_setup` and from every other APB port (prdata/
# pwrite/pready/pselx/penable/paddr/pwdata/pclk).
# chip-AGNOSTIC: generic AMBA reset-naming grammar, no design / vendor / SKU
# literal.
_RESET_PORT_NAME_RE = re.compile(
    r"(?:^|_)(?:a?rst|s?rst|reset|sclr|clr|clear|por)(?:_|n|ni|[0-9]|$)"
    r"|(?:^|_)[a-z]{1,4}(?:reset_?n|rst_?n)(?:_|[0-9]|$)"
    r"|(?:^|_)[a-z]{1,4}(?:reset_?n|rst_?n)$", re.I)
_RESET_PORT_EXACT = {
    "rst", "reset", "clr", "clear", "por", "srst", "sclr", "arst", "areset",
    "aresetn", "nrst", "nreset", "resetn", "rstn", "rst_n", "reset_n",
    # AMBA bus-prefixed active-low resets (APB/AHB) — exact forms for safety.
    "presetn", "preset_n", "hresetn", "hreset_n",
}


def _is_reset_port_name(name: str) -> bool:
    n = name.lower()
    return n in _RESET_PORT_EXACT or bool(_RESET_PORT_NAME_RE.search(n))


# Verilog keywords the (best-effort) RTL port parser can leak as "port" names
# when a body declaration is mis-scoped — never real ports; filtered from the
# cross-check set so they cannot accidentally rescue a spec phantom.
_RTL_PORT_NOISE = {
    "reg", "wire", "logic", "input", "output", "inout", "signed", "unsigned",
    "parameter", "localparam", "integer", "genvar", "wand", "wor", "tri",
}


def _rtl_reset_ports(rtl_text: Optional[str],
                     tb_text: Optional[str] = None) -> List[str]:
    """Reset-shaped port names parsed from the authored RTL (best-effort).

    Returns the concrete reset port identifier(s) so the reset checklist item's
    coverage tokens are the design's REAL reset port(s) — exact, over-fit-free,
    no-leak (a TB must drive the actual reset port to be counted).

    ORGANIC #770 r5 Step-2.7 — scan the DUT DESIGN modules (the TB-instantiated
    top + reachable submodules), not just the FIRST module, so a multi-module RTL
    whose top is not first does not lose a non-standard reset name (init_n/clr).
    A reset port living ONLY in an un-instantiated helper is excluded (it is not
    the bound design's reset — §4.05)."""
    if not rtl_text:
        return []
    seen: set = set()
    out: List[str] = []
    for mod in _dut_module_names(rtl_text, tb_text) or [None]:
        try:
            _, ports = _SRC.parse_rtl_ports(rtl_text, mod)
        except Exception:
            continue
        for p in ports:
            nm = p.name
            if (nm.lower() not in _RTL_PORT_NOISE
                    and _is_reset_port_name(nm) and nm not in seen):
                seen.add(nm)
                out.append(nm)
    return out


def _rtl_module_port_names(rtl_text: str, module: Optional[str]) -> set:
    """Lower-cased port identifiers of ONE module (or the first when module is
    None). Empty on a parse miss. chip-AGNOSTIC."""
    try:
        _, ports = _SRC.parse_rtl_ports(rtl_text, module)
    except Exception:
        return set()
    return {p.name.lower() for p in ports
            if p.name and p.name.lower() not in _RTL_PORT_NOISE}


def _dut_module_names(rtl_text: str, tb_text: Optional[str]) -> List[str]:
    """ORGANIC #770 r5 Step-2.7 — the DUT design's module name(s): the module the
    TESTBENCH instantiates (the authoritative DUT top) PLUS its reachable
    submodules (modules it instantiates, transitively). When the TB / its
    instantiation cannot be determined, fall back to EVERY module (the wider set
    is no-leak biased for the never-driven/decoy negatives — they still block).

    The point (§4.05): a `*tready`/reset port that lives ONLY in a HELPER module
    the DUT top does NOT instantiate is NOT part of the bound design surface, so
    a TB driving a TB-local same-named reg must not satisfy the coverage item."""
    mods = re.findall(r"\bmodule\s+(\w+)\b", rtl_text)
    if not mods:
        return []
    modset = set(mods)
    # module -> set of submodule names it instantiates (`Name inst (...)`).
    insts: Dict[str, set] = {}
    for mm in re.finditer(r"\bmodule\s+(\w+)\b(.*?)\bendmodule\b",
                          rtl_text, re.DOTALL):
        body = mm.group(2)
        sub = {im.group(1) for im in
               re.finditer(r"\b([A-Za-z_]\w*)\s+[A-Za-z_]\w*\s*(?:#\s*\([^)]*\)\s*)?\(",
                           body)
               if im.group(1) in modset and im.group(1) != mm.group(1)}
        insts[mm.group(1)] = sub
    # the TB-instantiated top.
    tops: List[str] = []
    if tb_text:
        for im in re.finditer(
                r"\b([A-Za-z_]\w*)\s+[A-Za-z_]\w*\s*(?:#\s*\([^)]*\)\s*)?\(",
                tb_text):
            if im.group(1) in modset:
                tops.append(im.group(1))
    if not tops:
        return mods  # can't tell which is the DUT → wider set (no-leak biased)
    # BFS the reachable design from each TB-instantiated top.
    reach: set = set()
    frontier = list(tops)
    while frontier:
        m = frontier.pop()
        if m in reach:
            continue
        reach.add(m)
        frontier.extend(insts.get(m, ()))
    return sorted(reach)


def _rtl_port_name_set(rtl_text: Optional[str],
                       tb_text: Optional[str] = None) -> set:
    """Lower-cased set of the DUT design's port identifiers (best-effort).

    Returns an EMPTY set when no usable port could be parsed, so the caller
    skips the phantom-port cross-check rather than risk dropping real ports on
    a parser miss. chip-AGNOSTIC: structural Verilog port parse only.

    ORGANIC #770 r5 — `parse_rtl_ports` returns only the FIRST/chosen module, so
    a MULTI-MODULE RTL whose top is NOT first lost the top's ports. r5 Step-2.7 —
    do NOT blindly union ALL modules either (a HELPER-only `*tready`/reset port
    would let a TB-local same-named reg satisfy the item — a §4.05 leak). Union
    over the DUT DESIGN: the TB-instantiated top + its reachable submodules."""
    if not rtl_text:
        return set()
    names: set = set()
    for mod in _dut_module_names(rtl_text, tb_text) or [None]:
        names |= _rtl_module_port_names(rtl_text, mod)
    return names


def _tb_instantiated_module_types(tb_text: Optional[str], modset: set) -> List[str]:
    """The DISTINCT RTL module type names the TB instantiates, in order
    (`Type inst (...)` / `Type #(...) inst (...)`). chip-AGNOSTIC, pure Verilog
    instantiation grammar."""
    if not tb_text:
        return []
    out: List[str] = []
    seen: set = set()
    for im in re.finditer(
            r"\b([A-Za-z_]\w*)\s+[A-Za-z_]\w*\s*(?:#\s*\([^)]*\)\s*)?\(",
            tb_text):
        t = im.group(1)
        if t in modset and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _ambiguous_port_names(rtl_text: Optional[str],
                          tb_text: Optional[str]) -> set:
    """Lower-cased port names declared by ≥2 DISTINCT module TYPES the TESTBENCH
    instantiates — e.g. a DUT and a separate monitor/driver module that happen to
    share a port name like `m_axis_tready`.

    ORGANIC #770 r6 Step-2.7 (§4.05 no-leak): a named instance connection
    `.shared_port(local)` cannot be unambiguously attributed to the DUT instance
    vs the sibling's, so the handshake alias-credit path must NOT trust it — a TB
    that toggles only a MONITOR's same-named handshake port (while the DUT's port
    is tied to a constant) would otherwise be wrongly credited as exercising the
    DUT handshake. Empty when the TB instantiates <2 distinct module types (the
    common single-DUT self-TB), so the legitimate single-design alias path
    (r6 FP, axis_joiner_0001) is untouched. chip-AGNOSTIC."""
    if not rtl_text or not tb_text:
        return set()
    mods = set(re.findall(r"\bmodule\s+(\w+)\b", rtl_text))
    if not mods:
        return set()
    types = _tb_instantiated_module_types(tb_text, mods)
    if len(types) < 2:
        return set()
    counts: Dict[str, int] = {}
    for t in types:
        for nm in _rtl_module_port_names(rtl_text, t):
            counts[nm] = counts.get(nm, 0) + 1
    return {nm for nm, c in counts.items() if c >= 2}


# ORGANIC #770 — a clocked (registered) block detector, for latency corroboration.
_CLOCKED_BLOCK_RE = re.compile(
    r"@\s*\(\s*(?:posedge|negedge)\b", re.IGNORECASE)


def _rtl_has_clocked_block(rtl_text: Optional[str]) -> Optional[bool]:
    """True iff the RTL has a clock-edge-sensitive (registered) block; False iff
    it parses but has NONE (provably pure-combinational); None when no RTL.

    Used to corroborate a prose 'latency'/'registered' requirement: a prose
    latency claim on a design with no clocked block at all is CONTRADICTED by the
    RTL structure. chip-AGNOSTIC: pure Verilog edge-sensitivity grammar; comment-
    stripped so a `// posedge` mention never false-positives."""
    if not rtl_text:
        return None
    try:
        stripped = _SRC._strip_comments(rtl_text)
    except Exception:
        stripped = rtl_text
    return bool(_CLOCKED_BLOCK_RE.search(stripped))


# ORGANIC R13C3 (cvdp_copilot_ir_receiver_0001) — RTL BIT-ORDERING SIGNATURE, for
# byte_order corroboration. A serial-receiver / packer that assembles a vector one
# bit at a time has a structural shift-insert signature that fixes the bit order:
#   LSB-first: the FIRST-arriving bit ends up in bit[0]; each new bit is inserted
#              at the MSB and the register shifts RIGHT —  reg <= {new, reg[N-1:1]}
#   MSB-first: the FIRST-arriving bit ends up in bit[N-1]; each new bit is inserted
#              at the LSB and the register shifts LEFT  —  reg <= {reg[N-2:0], new}
# Detect the shift-insert concat shape and classify by which side the existing
# register slice sits on. chip-AGNOSTIC: pure Verilog concat/slice grammar, no
# chip / vendor / signal-name literal; comment-stripped so a `// lsb first` note
# never false-positives. Returns "lsb", "msb", or None (no orderable structure).
# A right-shift slice  reg[HI:1]  (drops bit 0, keeps the high end)  -> LSB-first.
# A left-shift  slice  reg[HI:0]  with HI < width-1 (drops MSB)      -> MSB-first.
_SHIFT_INSERT_RE = re.compile(
    r"\{([^{}]+)\}", re.IGNORECASE)
_REG_HI1_SLICE_RE = re.compile(
    r"([A-Za-z_]\w*)\s*\[\s*\d+\s*:\s*1\s*\]")          # reg[N-1:1]  (right shift)
_REG_HI0_SLICE_RE = re.compile(
    r"([A-Za-z_]\w*)\s*\[\s*\d+\s*:\s*0\s*\]")          # reg[N-2:0]  (left shift)
# An incoming 1-bit term: a bare 1-bit literal or a simple identifier / indexed
# bit (the just-decoded bit). Anything that is plausibly the freshly-arrived bit.
_BIT_TERM_RE = re.compile(
    r"^(?:1'b[01xz]|[A-Za-z_]\w*(?:\s*\[[^\]]+\])?)$", re.IGNORECASE)


def _rtl_byte_order_signature(rtl_text: Optional[str]) -> Optional[str]:
    """Classify the RTL's serial bit-ordering as "lsb" / "msb" / None.

    Scans concatenation shift-insert assignments `lhs <= {a, b}` where exactly one
    side is a same-vector contiguous slice and the other is the freshly-arrived
    bit. A `{new, reg[N-1:1]}` (slice on the HIGH side, dropping bit 0, shifting
    right) packs LSB-first; a `{reg[N-2:0], new}` (slice on the LOW side, dropping
    the MSB, shifting left) packs MSB-first. Returns the SOLE consistent order, or
    None when there is no shift-insert structure / it is contradictory.
    chip-AGNOSTIC, comment-stripped, pure grammar."""
    if not rtl_text:
        return None
    try:
        s = _SRC._strip_comments(rtl_text)
    except Exception:
        s = rtl_text
    orders = set()
    for cm in _SHIFT_INSERT_RE.finditer(s):
        body = cm.group(1)
        # split the top-level concat into exactly two comma terms
        parts = [p.strip() for p in body.split(",")]
        if len(parts) != 2:
            continue
        a, b = parts
        a_hi1 = _REG_HI1_SLICE_RE.fullmatch(a)
        b_hi1 = _REG_HI1_SLICE_RE.fullmatch(b)
        a_hi0 = _REG_HI0_SLICE_RE.fullmatch(a)
        b_hi0 = _REG_HI0_SLICE_RE.fullmatch(b)
        # LSB-first: {bit, reg[HI:1]} — bit on the LEFT, right-shift slice on RIGHT
        if b_hi1 and _BIT_TERM_RE.match(a):
            orders.add("lsb")
        # MSB-first: {reg[HI:0], bit} — left-shift slice on LEFT, bit on the RIGHT
        elif a_hi0 and _BIT_TERM_RE.match(b) and not a_hi1:
            orders.add("msb")
    if len(orders) == 1:
        return next(iter(orders))
    return None


def _spec_byte_order_intent(evidence: str) -> Optional[str]:
    """Map the matched byte_order spec phrase to "lsb" / "msb" / None.

    "LSB First" / "little-endian" -> lsb ; "MSB First" / "big-endian" -> msb ;
    a generic 'byte order' / 'bit order' phrase with no direction -> None (not
    classifiable -> cannot be CONTRADICTED, only CORROBORATED-or-not)."""
    e = (evidence or "").lower()
    if re.search(r"lsb[- ]first|little[- ]endian", e):
        return "lsb"
    if re.search(r"msb[- ]first|big[- ]endian", e):
        return "msb"
    return None


# ORGANIC R13C3 — TB STRUCTURAL-STIMULUS coverage for the byte_order item, the
# ordering analogue of _tb_exercises_overflow_region / _tb_exercises_handshake_
# region. The shipped attribute_coverage() marked byte_order covered ONLY when the
# TB literally NAMES the spec phrase ("lsb first") in code — conflating VOCABULARY
# with coverage. A faithful ordering TB drives a vector ONE INDEXED BIT AT A TIME
# (a loop `for(i...) send(frame[i])`) and then asserts the packed output equals
# the source vector (`out === frame`) — proving the arrival order maps to the
# packed bit positions — yet never spells "lsb first". This helper detects that
# structural ordering exercise: an INDEXED bit-by-bit drive of a vector together
# with a whole-vector / per-index equality assertion. A TB that does NOT exercise
# the ordering (no indexed per-bit drive, or no ordering equality check) is NOT
# covering — the §4.05 gap is real and STILL reported. chip-AGNOSTIC: pure
# indexed-drive + equality-assertion grammar; no chip / signal-name literal.
_TB_INDEXED_DRIVE_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s*\[\s*([A-Za-z_]\w*)\s*\]")     # vec[i]  (variable index)
# An ORDERING ASSERTION: an equality whose BOTH operands are vector REFERENCES (a
# bare identifier, or an identifier indexed by a VARIABLE) — i.e. `out === frame`
# or `out[i] === frame[i]`. Critically NEITHER operand may be a numeric/sized
# literal, so `i == 4` (loop counter vs constant) and `junk[i] == 8'h00` (a bit
# vs a literal) are NOT ordering assertions. This is the "packed result ===
# ordered source" check that proves the arrival order maps to the bit positions.
_TB_ORDER_ASSERT_RE = re.compile(
    r"([A-Za-z_]\w*)(?:\s*\[\s*[A-Za-z_]\w*\s*\])?\s*"
    r"(?:===|!==|==|!=)\s*"
    r"([A-Za-z_]\w*)(?:\s*\[\s*[A-Za-z_]\w*\s*\])?(?!\s*[\w'])")


# ORGANIC-20260618 (data_serializer_0001) — a TB binds a DUT port to a LOCAL net
# at instantiation (`data_serializer ... (.s_data_o(c_sd), …)`), then writes its
# ordering assertion against that local net (`c_sd !== expvec[k]`). The DUT-tie
# check compared the assertion operand to the DUT PORT NAME (`s_data_o`) and so
# never credited the port-connection ALIAS (`c_sd`) — a faithful ordering TB was
# scored UNCOVERED. This resolves the named-port-connection aliases `.port(net)`
# so a net bound to a DUT port counts as DUT-tied. Positional connections are not
# resolved (no port name to anchor on) and named connections to a CONSTANT/expr
# (`.PARAM(8)`) are not aliases. chip-AGNOSTIC: Verilog named-connection grammar.
_TB_PORT_CONN_RE = re.compile(r"\.\s*([A-Za-z_]\w*)\s*\(\s*([A-Za-z_]\w*)\s*\)")


def _tb_port_connection_aliases(tb_clean: str,
                                rtl_ports_lower: Optional[set]) -> set:
    """Lower-cased TB net names bound, at instantiation, to a DUT PORT via a
    named connection `.port(net)`. Restricted to nets bound to a name in the
    known DUT port set (when supplied) so an unrelated `.foo(bar)` macro/instance
    cannot widen the tie. chip-AGNOSTIC."""
    if not tb_clean or rtl_ports_lower is None:
        return set()
    ports = {p.lower() for p in rtl_ports_lower}
    aliases: set = set()
    for m in _TB_PORT_CONN_RE.finditer(tb_clean):
        if m.group(1).lower() in ports:
            aliases.add(m.group(2).lower())
    return aliases


def _tb_exercises_byte_order_region(
        tb_clean: str, rtl_ports_lower: Optional[set] = None) -> bool:
    """True iff the TB structurally exercises a serial bit ORDERING.

    Requires ALL of: (1) a loop construct, (2) a per-bit indexed drive `vec[i]`
    of some vector, and (3) an ORDERING ASSERTION — a vector===vector equality
    (`out === frame`, never `counter == literal` or `bit == literal`) in which
    one operand is the bit-indexed-driven vector AND, when the RTL port set is
    known, one operand is a DUT PORT — resolved through named port-connection
    aliases `.port(net)` so a TB net bound to a DUT port counts (so the assertion
    checks the DUT's packing, not a self-comparison of unrelated TB scratch).

    §4.05 no-leak: incidental loop + `scratch[i]=i` + `i==4` (or `junk[i]==8'h00`)
    does NOT count — those carry no vector===vector assertion tying a bit-driven
    vector to the DUT, so a TB that never verifies the ordering still GAPs.
    chip-AGNOSTIC, comment-stripped grammar."""
    if not tb_clean:
        return False
    if not re.search(r"\bfor\b|\brepeat\b|\bforeach\b|\bwhile\b", tb_clean):
        return False
    indexed_vecs = {m.group(1).lower()
                    for m in _TB_INDEXED_DRIVE_RE.finditer(tb_clean)}
    if not indexed_vecs:
        return False
    ports = {p.lower() for p in (rtl_ports_lower or set())}
    # widen the DUT-tie set with nets bound to a DUT port at instantiation
    ports |= _tb_port_connection_aliases(tb_clean, rtl_ports_lower)
    for m in _TB_ORDER_ASSERT_RE.finditer(tb_clean):
        operands = {m.group(1).lower(), m.group(2).lower()}
        ties_drive = bool(operands & indexed_vecs)
        ties_dut = (not ports) or bool(operands & ports)
        if ties_drive and ties_dut:
            return True
    return False


# ORGANIC #770 (R13C1) — does the RTL STRUCTURALLY declare any `signed`
# port/variable/operation? Used to corroborate a prose 'signedness' requirement.
# Verilog's DEFAULT arithmetic is UNSIGNED, so a design that never writes the
# `signed` keyword is structurally unsigned — a prose "unsigned integers" mention
# is then BACKED by the RTL's signed-absence (no behavioral gap to cover) and the
# checklist item must NOT hard-block (it had no corroboration branch and stayed
# UNKNOWN->block, false-positive-ing every spec-faithful unsigned design). A spec
# whose RTL DOES declare `signed` (e.g. a 16qam_mapper's `input signed [...]`) is
# genuinely signed: an uncovered signedness item there is a real gap → keeps
# blocking (no-leak). True iff the comment-stripped RTL contains the `signed`
# keyword as a declaration/operation qualifier; False iff it parses but has none;
# None when no RTL is supplied (cannot judge → keep block). chip-AGNOSTIC: pure
# Verilog `signed` keyword grammar, comment-stripped so a `// signed` mention
# never false-positives. The bare `unsigned` keyword is explicitly NOT treated as
# a signed declaration (`\bsigned\b` does not match inside `unsigned`).
_RTL_SIGNED_DECL_RE = re.compile(
    r"\b(?:input|output|inout|reg|wire|logic|var|integer|bit|byte|"
    r"shortint|int|longint)\b[^;,()=\n]*?\bsigned\b"
    r"|\$signed\b"
    r"|\bsigned\b\s*(?:\[[^\]]*\]\s*)?[A-Za-z_]\w*\s*(?:[;,=]|\[)")


def _rtl_declares_signed(rtl_text: Optional[str]) -> Optional[bool]:
    """True iff the RTL structurally declares a `signed` port/var/op; False iff it
    parses but declares none (unsigned-by-default); None when no RTL is supplied."""
    if not rtl_text:
        return None
    try:
        stripped = _SRC._strip_comments(rtl_text)
    except Exception:
        stripped = rtl_text
    return bool(_RTL_SIGNED_DECL_RE.search(stripped))


# ORGANIC #743 — negation-aware feature presence. A spec whose ONLY mention of
# a reset/clock is the NEGATED phrasing ("no clock or reset inputs", "no reset",
# "without a reset", "operates entirely combinationally, with no clock") must
# NOT derive a phantom reset/clock requirement (which hard-blocks a correct
# combinational design under --strict). A real "reset clears X" mention still
# derives the requirement. chip-AGNOSTIC: pure negation grammar, no chip literal.
_NEG_TOKENS_RE = re.compile(
    r"\b(no|without|not|n't|nor|neither|none|never|free\s+of|lacks?|lacking|"
    r"absent|sans|devoid\s+of|has\s+no|have\s+no|requires?\s+no|needs?\s+no|"
    r"n/?a|not\s+applicable)\b")


def _split_sentences(low: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.\n;:])", low) if s.strip()]


# Negation is scoped to the CLAUSE containing the keyword. A clause boundary is
# a sentence terminator (. \n ;), a COMMA, or a contrast conjunction (but /
# however / …) — each separates independent assertions, so a negation in one
# clause does NOT govern a keyword in another. This avoids the two failure modes
# an earlier char-window version had: (a) a negation comma-joined to a real
# reset clause ("no enable input, the reset clears X") wrongly dropping the
# reset; (b) the issue's own "without waiting, the module asserts reset" being
# suppressed. A negation ANYWHERE in the keyword's own clause (before OR after
# the keyword) negates it ("a reset is not required", "reset: none").
_CLAUSE_SPLIT_RE = re.compile(
    r"[.\n;,]"
    r"|\b(?:but|however|yet|though|although|whereas|while|nevertheless|"
    r"nonetheless|except\s+that)\b")


def _clauses(low: str) -> List[str]:
    return [c for c in _CLAUSE_SPLIT_RE.split(low) if c and c.strip()]


_HEADING_CLAUSE_RE = re.compile(r"^\s*#{1,6}\s")
# A presence-denial token that DIRECTLY governs the keyword: "no [explicit]
# reset", "without a reset", "has no reset", "lacks reset", "does not use a
# reset". ORGANIC #845 round-3 (Step-2.7): only ADJECTIVE/article/qualifier
# fillers may sit between the denial and the keyword — NOT an arbitrary noun.
# The round-2 `(?:\s+\w+){0,3}` arm let a negated OTHER noun intrude ("no GLITCH
# on the reset" wrongly read as denying the reset → a genuine reset dropped, a
# §4.05 leak). So the negated head-noun must BE the keyword.
_DENIAL_FILLER = (
    r"(?:\s+(?:a|an|the|any|explicit|dedicated|external|internal|separate|"
    r"global|local|true|real|actual|physical|valid|async\w*|sync\w*|"
    r"hardware|software|power[\s-]?on|active[\s-]?(?:low|high)|"
    r"additional|extra|special|generic|standard|single|common))*\s+")
_DENIAL_BEFORE = (
    r"\b(?:no|without|has\s+no|have\s+no|lacks?|lacking|devoid\s+of|"
    r"free\s+of|sans|requires?\s+no|needs?\s+no|"
    r"do(?:es)?\s+n(?:o|')t\s+(?:use|have|require|need|include|provide|"
    r"contain|implement|support)|don'?t\s+(?:use|have|require|need|include|"
    r"provide|contain|implement|support))\b")
# A presence-denial that follows the keyword: "<kw> is not provided/present/
# required/needed/implemented/used/supported/available", "<kw> ... not exist",
# "<kw> ... is omitted/removed/absent/excluded/disabled" (ORGANIC #845 round-3).
_DENIAL_AFTER_VERB = (
    r"(?:(?:not|never)\s+(?:a\s+|an\s+|the\s+|any\s+)?"
    r"(?:provided|present|required|needed|implemented|used|supported|"
    r"available|exist\w*|include\w*)"
    r"|(?:is|are|being|intentionally|deliberately)?\s*"
    r"(?:omitted|removed|excluded|stripped|disabled|absent))")
# A REAFFIRMATION that the feature genuinely EXISTS despite a kind-denial: "no
# separate reset (it SHARES the bus reset)", "no dedicated reset, DERIVED FROM
# the global reset". When present, the clause denies a particular KIND, not the
# feature's existence, so it must NOT veto. ORGANIC #845 round-3 (Step-2.7). The
# "use" family is deliberately EXCLUDED — it collides with the denial verb "does
# not USE a reset" (which must stay a denial); "shared/derived/common/bus/…"
# unambiguously reaffirm a still-present (shared) reset.
_REAFFIRM_VERB = (
    r"\b(?:shares?|sharing|shared|derived\s+from|deriv\w*|common|global|"
    r"system|bus|same|tied\s+to|connected\s+to|driven\s+by|instead)\b")
# An ABSENCE verb that denies the feature exists even though it is not a token in
# `_NEG_TOKENS_RE`: "reset … is OMITTED / REMOVED / ABSENT". ORGANIC #845 round-3.
_ABSENCE_VERB_RE = re.compile(
    r"\b(?:omitted|removed|excluded|stripped|absent|disabled)\b", re.I)
# Any negation token that can govern an absence verb in the same clause and make
# it a DOUBLE NEGATIVE reaffirming presence: "the reset is NEVER disabled", "the
# reset CANNOT be disabled", "the reset is NOT to be disabled", "at NO point is
# the reset omitted". ORGANIC #845 round-4/5 (Step-2.7): the absence-verb arm
# wrongly read these as denials and dropped a PRESENT (always-on) reset — a §4.05
# leak. Rather than require the negation ADJACENT to the absence verb (round-4 was
# too narrow — `cannot`/`not to be`/`no point` broke adjacency), a clause that
# carries BOTH an absence verb AND any negation token is a reaffirming double
# negative (the §4.05-safe direction is to DERIVE). A genuine absence ("the reset
# is disabled/omitted", no negation) still denies.
_NEG_GOVERNS_RE = re.compile(
    r"\b(?:never|not|no|nor|none|cannot|can['’]?t|n['’]?t|"
    r"without|unable)\b", re.I)
_DENIAL_CACHE: Dict[str, "re.Pattern[str]"] = {}
_REAFFIRM_CACHE: Dict[str, "re.Pattern[str]"] = {}


def _clause_denies_existence(clause: str, keyword_re: str) -> bool:
    """True iff the clause's negation DENIES THE KEYWORD'S EXISTENCE (not merely
    an incidental negation governing some OTHER noun, NOR a denial of a particular
    KIND while the feature still exists). ORGANIC #845 round-2/3 (Step-2.7): a
    clause like 'a power-on reset is not optional', 'on reset there are no
    outstanding transactions', 'there must be no glitch on the reset', or 'no
    separate reset (it shares the bus reset)' negates something OTHER than the
    reset's existence, so it must NOT veto a `## Reset` heading affirmative
    (not-deriving a genuine reset is the §4.05 leak direction). The denial token
    must DIRECTLY govern the keyword (`no [explicit] <kw>`, `does not use a <kw>`,
    `<kw> is not provided`, `<kw> is omitted`) AND the clause must carry NO
    reaffirmation that the feature still exists (`shares`/`derived from`/… <kw>)."""
    pat = _DENIAL_CACHE.get(keyword_re)
    if pat is None:
        kwp = r"(?:" + keyword_re + r")"
        pat = re.compile(
            _DENIAL_BEFORE + _DENIAL_FILLER + kwp
            + r"|" + kwp + r"\b(?:\s+\w+){0,4}?\s+(?:is|are|will\s+be|gets?|"
            r"being)?\s*" + _DENIAL_AFTER_VERB,
            re.I)
        _DENIAL_CACHE[keyword_re] = pat
    if pat.search(clause) is None:
        return False
    # a NEGATED absence verb ("never disabled", "cannot be disabled", "not to be
    # disabled", "at no point omitted") is a double negative reaffirming presence
    # → not an existence-denial. Any negation token co-occurring with an absence
    # verb in the clause suffices (lean to DERIVE = §4.05-safe).
    if _ABSENCE_VERB_RE.search(clause) and _NEG_GOVERNS_RE.search(clause):
        return False
    # a reaffirmation that the feature still exists (shared/derived) → kind-denial
    # only, not an existence-denial → does NOT veto.
    rea = _REAFFIRM_CACHE.get(keyword_re)
    if rea is None:
        kwp = r"(?:" + keyword_re + r")"
        rea = re.compile(
            _REAFFIRM_VERB + r"[^.!?;]{0,40}?" + kwp
            + r"|" + kwp + r"[^.!?;]{0,40}?" + _REAFFIRM_VERB,
            re.I)
        _REAFFIRM_CACHE[keyword_re] = rea
    return rea.search(clause) is None


def _mention_present_unnegated(text: str, keyword_re: str,
                               *, polarity_check=_prose_is_denied) -> bool:
    """True iff the keyword appears in at least one CLAUSE where it is NOT
    governed by a negation token. If EVERY clause mentioning the keyword negates
    it, the feature is genuinely absent and no requirement is derived.

    ORGANIC #845 (gmii_axis_0001) — a markdown SECTION HEADING (`## Reset`) is a
    topic LABEL, not an affirmative requirement statement. Split into its own
    clause it carries the keyword with no negation token, so it would wrongly
    count as an affirmative mention even when the section BODY documents the
    legitimate ABSENCE of the feature ('No explicit reset port is provided').
    A heading-only affirmative mention is honored ONLY when no body clause
    DENIES THE FEATURE'S EXISTENCE (`_EXISTENCE_DENIAL_RE`). ORGANIC #845
    round-2 (Step-2.7): a body clause whose negation is incidental ('a power-on
    reset is NOT optional', 'reset is NEVER deasserted until …') does NOT veto
    the heading — only a presence-denial does (no-leak: not-deriving a genuine
    reset is the leak direction, so an ambiguous negation still derives)."""
    low = text.lower()
    kw = re.compile(keyword_re, re.I)
    heading_affirmative = False
    negated_body = False
    for clause in _clauses(low):
        if not kw.search(clause):
            continue
        # The shared vocabulary is the authority for general prose polarity.
        # Keep the older feature-specific terms below because they also encode
        # presence verbs ("lacks", "omitted") that are deliberately outside
        # the generic no/not vocabulary; do not grow another private list here.
        negated = bool(polarity_check(clause)
                       or _NEG_TOKENS_RE.search(clause)
                       or _ABSENCE_VERB_RE.search(clause))
        is_heading = bool(_HEADING_CLAUSE_RE.search(clause))
        if not is_heading and not negated:
            return True   # an affirmative BODY clause — feature is present
        if is_heading and not negated:
            heading_affirmative = True
        if (not is_heading and negated
                and _clause_denies_existence(clause, keyword_re)):
            negated_body = True
    if heading_affirmative and not negated_body:
        return True
    return False


def _has_reset(text: str) -> bool:
    # #743: only an UN-negated reset mention derives the reset requirement.
    return _mention_present_unnegated(text, r"\breset\b|\brst\b|\bpor\b")


def _has_clock(text: str) -> bool:
    # #743: companion negation-guard for the clock keyword path (same blind spot:
    # 'no clock or reset inputs' must not derive a phantom clock requirement).
    return _mention_present_unnegated(text, r"\bclock\b|\bclk\b")


# #760 (arithmetic_progression_generator_0015) — preventive/structural-fact
# guard for the overflow/saturation/truncation structural-keyword extractor.
# The #743 clause-scoped negation guard (_mention_present_unnegated / _clauses)
# is wired ONLY into _has_reset/_has_clock; the overflow/signed/byteorder/
# handshake loop (~line 539) bypasses it and does a bare rx.search(spec_text)
# with NO comment-stripping and NO context guard. A *width-derivation* note such
# as "WIDTH_OUT_VAL ... sized to prevent overflow" (carried verbatim from an RTL
# inline comment // ... to prevent overflow) is a STRUCTURAL fact describing how
# the design AVOIDS the condition, NOT a behavioral requirement to actively
# HANDLE it — yet it derived a phantom overflow checklist item that hard-blocks a
# correct edge-case ($clog2(0)) design under --strict. This guard inspects the
# CLAUSE the keyword sits in: if the clause states the design PREVENTS/AVOIDS the
# condition (prevent/avoid/sized to/wide enough to/so it does not …) AND does NOT
# also state ACTIVE handling (saturate/clamp/wrap/correct/clip/round in the same
# clause), the match is a width-sizing note, not a behavioral requirement — skip.
# A real "must saturate to prevent overflow and clamp" keeps the requirement
# because the active-handling verb co-occurs. chip-AGNOSTIC: pure preventive +
# active-handling grammar, no chip / vendor / SKU literal.
_PREVENTIVE_CTX_RE = re.compile(
    r"\b(prevent|preventing|avoid|avoiding|sized\s+to|wide\s+enough|"
    r"big\s+enough|large\s+enough|so\s+(?:it|that|they)\s+(?:do(?:es)?\s+not|"
    r"never|won'?t|cannot)|to\s+ensure\s+no|guard(?:s|ed|ing)?\s+against|"
    r"without\b)", re.I)
# Active-handling verbs that mean the design DOES exercise the condition (so the
# requirement is real even if it sits beside a "prevent" word).
_ACTIVE_HANDLE_RE = re.compile(
    r"\b(saturat\w*|clamp\w*|wrap\w*|clip\w*|round(?:s|ed|ing)?|"
    r"correct\w*|truncat\w*|roll(?:s|ed|ing)?[- ]?over)\b", re.I)


def _is_preventive_structural_fact(clause: str, matched_word: str) -> bool:
    """True iff `clause` describes the design PREVENTING/AVOIDING the matched
    overflow-family condition (a width-sizing / structural note) rather than
    actively HANDLING it.

    Suppress ONLY a preventive clause whose match is the bare condition NOUN
    (overflow / underflow / wrap-around) — i.e. the design AVOIDS that condition.
    If ANY active-handling verb (saturat*/clamp*/wrap*/clip*/round*/correct*/
    truncat*) appears ANYWHERE in the clause, the design DOES exercise a
    region behavior, so the requirement is real and is KEPT — no-leak biased:
    when in doubt, KEEP. 'sized to prevent overflow' (noun-only, preventive) is
    suppressed; 'saturate to prevent overflow and clamp', 'truncated output',
    'wraps around on overflow' are all kept. (#760)"""
    if not _PREVENTIVE_CTX_RE.search(clause):
        return False
    # The condition NOUN alone (overflow/underflow) in a preventive clause is a
    # width-sizing/structural note. Any active-handling verb anywhere in the
    # clause means the design HANDLES the region -> keep (do not suppress).
    if _ACTIVE_HANDLE_RE.search(clause):
        return False
    return bool(re.fullmatch(r"(overflow|underflow|wrap[- ]?around)",
                             matched_word.strip(), re.I))


def _detect_latency(text: str) -> Optional[str]:
    """Return a human latency phrase if the spec states one, else None."""
    lat = _SRC._detect_latency(text)
    if lat is True:
        return "registered / single-cycle latency"
    # lat is False = the spec EXPLICITLY declares combinational / zero-latency /
    # unregistered behaviour. That declaration is AUTHORITATIVE and suppresses
    # the whole latency item — it must override the keyword-grep fallback below,
    # which would otherwise re-derive a phantom "registered / N-cycle latency"
    # from incidental wording (e.g. a combinational block that "completes in one
    # clock cycle" means WITHIN one cycle, i.e. zero registered latency). This
    # mirrors the #743 negation-guard pattern: a False from the helper is an
    # explicit absence, not a "keep looking". (#758)
    if lat is False:
        return None
    m = _LATENCY_RE.search(text)
    if m:
        n = m.group(1) or m.group(2)
        if n:
            return f"{n}-cycle latency"
        return "registered latency"
    return None


# ---------------------------------------------------------------------------
# Worked example:  "in 0x05 -> out 0x0A",  "f(3)=9",  "input=2 output=4"
# ---------------------------------------------------------------------------
# The separator is CAPTURED so a bare '=' (heavily overloaded: assignment,
# arithmetic equality, encoding-legend "code = label") can be distinguished from
# the unambiguous worked-example ARROWS ('->', '=>', '→', which mean "maps to /
# produces"). A bare-'=' match is only charged as a worked example when it is a
# genuine in==out DATA pair, NOT a control-code -> label ENCODING LEGEND
# ("00=90 CW, 01=180, 10=270", a 2-bit selector legend on a port comment) nor an
# arithmetic-expression fragment ("data_out = 8'b... << 4 = 8'b...") — see
# _is_control_code_legend below. chip-AGNOSTIC: pure legend/expression grammar,
# no chip / vendor / SKU literal. (#761)
_WORKED_EXAMPLE_RE = re.compile(
    r"(0[xXbB][0-9A-Fa-f_]+|\d+)\s*(->|→|=>|=)\s*(0[xXbB][0-9A-Fa-f_]+|\d+)")

# Two or more comma/、-separated "N = label" entries on one line is an
# ENUMERATION LEGEND (code -> human-readable label), not a sequence of I/O data
# pairs. e.g. "00=90 CW, 01=180, 10=270 CW, 11=no rotation",
# "1 = sign extend, 0 = zero fill". The label half may be non-numeric ("90 CW",
# "no rotation"), which is exactly what a worked-example DATA pair is not.
_LEGEND_ENTRY_RE = re.compile(
    r"(0[xXbB][0-9A-Fa-f_]+|\d+|\d+'[bdh][0-9A-Fa-fxXzZ_]+)\s*[:=]\s*"
    r"[0-9A-Za-z_]")
# An arithmetic-operator context around a bare '=' ("<< 4 = 8'b...", "a + b = c")
# is an equality of an EXPRESSION, not an input->output example.
_ARITH_OP_RE = re.compile(r"[+\-*/%]|<<|>>|&|\||\^")


def _line_of(text: str, pos: int) -> str:
    """The full source LINE containing offset `pos` (no trailing newline)."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end < 0:
        end = len(text)
    return text[start:end]


def _is_control_code_legend(text: str, m) -> bool:
    """True iff a bare-'=' worked-example match is actually a control-code ->
    label ENCODING LEGEND or an arithmetic-expression fragment rather than an
    in==out DATA pair. ARROW matches ('->','=>','→') are never legends and never
    reach this check. chip-AGNOSTIC: structural legend/expression grammar only.

      * legend  : the match's own LINE holds >=2 comma-separated "N = label"
                  entries (an enumerated selector legend), OR the left operand is
                  enumerated elsewhere as a sized case label / selector code
                  ("2'b10" / "10:" / "10 =") — i.e. a control code, not data.
      * arith   : the match's own line contains an arithmetic operator joining
                  the operands (the '=' is expression equality, not a mapping).
    (#761)"""
    line = _line_of(text, m.start())
    # legend: two-or-more "N = label" entries on the line, comma/、-separated.
    if len(_LEGEND_ENTRY_RE.findall(line)) >= 2 and ("," in line or "、" in line):
        return True
    # arith: an arithmetic operator on the line between numeric operands.
    if _ARITH_OP_RE.search(line):
        return True
    # selector code: the left operand appears as a sized case label / selector
    # code somewhere in the chain text (control-code, not data), e.g. the port
    # comment "[1:0] sel : 00=.., 01=.." plus a "2'b00" case in the RTL/spec.
    code = m.group(1)
    if re.fullmatch(r"\d+", code):
        if re.search(r"\d+'[bdh]0*" + re.escape(code) + r"\b", text):
            return True
    return False


def _binary_nibble_has_grouped_source(text: str, nibble: str) -> bool:
    """ORGANIC #780 r2 (Step-2.7 §4.05) — True iff `nibble` (a bare binary token)
    appears as a CONTIGUOUS slice of a LARGER multi-nibble grouped/concatenated
    binary literal in `text` — the per-digit decomposition SOURCE (e.g.
    `0010_0101_0111` for the gloss `0101`). The source must carry >= 2 nibbles'
    worth of bits so a GENUINE standalone binary->decimal vector (a real
    binary-to-BCD / decoder test like `0101 -> 5`, which has NO such grouped
    source) is NOT mistaken for a decomposition gloss and keeps BLOCKING.
    chip-AGNOSTIC: pure binary-literal grammar."""
    n = len(nibble)
    for tm in re.finditer(r"[01][01_]*[01]", text):
        tok = tm.group(0).replace("_", "")
        if len(tok) <= n or len(tok) < 2 * n:
            continue
        # NIBBLE-ALIGNED containment only (ORGANIC #780 r2 Step-2.7 §4.05): a
        # per-digit decomposition places each digit on an n-bit boundary, so the
        # nibble must occur at an offset that is a MULTIPLE of n. This rejects a
        # COINCIDENTAL substring match in an unrelated wide TB/spec literal (where
        # the nibble lands at a non-aligned offset), which would otherwise
        # falsely downgrade a genuine standalone binary->decimal example.
        idx = tok.find(nibble)
        while idx != -1:
            if idx % n == 0:
                return True
            idx = tok.find(nibble, idx + 1)
    return False


def _worked_example_is_covered_parent_gloss(coverage_tokens: List[str],
                                            combined_text: str) -> bool:
    """ORGANIC #780 r2 (field reopen) — True iff a worked_example item is a
    binary-nibble NOTATIONAL gloss (LHS bits == RHS value, e.g. `0101 -> 5`) that
    is a per-digit STEP of a LARGER grouped binary value present in the spec OR
    the TESTBENCH — i.e. the parent example input the TB actually stimulates
    (binary_to_BCD_0010: the spec lists MSD/Middle/LSD digits separately but the
    TB drives the full `bcd_in = 0010_0101_0111`, so `0101 -> 5` is an
    intermediate algorithm step of a COVERED parent, not an independent I/O
    vector). The extraction-time `we_structural_artifact` only sees the SPEC, so
    a spec that shows the digits separately (table / "MSD 0010, Middle 0101")
    misses the parent — this run()-time check adds the TESTBENCH text, where the
    grouped parent input is driven.

    §4.05 no-leak: a GENUINE standalone binary->decimal example the TB never
    drives a CONTAINING parent value for (no grouped >=2-nibble source anywhere)
    is NOT downgraded → still BLOCKS. A TB that drives only the bare nibble
    itself (a 4-bit `4'b0101`) is NOT a >=2-nibble parent, so a real decoder
    vector keeps its blocking power. chip-AGNOSTIC."""
    if len(coverage_tokens) != 2:
        return False
    lhs, rhs = coverage_tokens[0], coverage_tokens[1]
    if not (re.fullmatch(r"[01]{2,}", lhs) and re.fullmatch(r"\d+", rhs)):
        return False
    try:
        if not (int(lhs, 2) == int(rhs, 10) and int(lhs, 2) != int(lhs, 10)):
            return False
    except ValueError:
        return False
    return _binary_nibble_has_grouped_source(combined_text, lhs)


def _worked_example_structural_artifact(text: str, m) -> bool:
    """ORGANIC #780 (#770 r7, R8C1) — True iff a worked-example match is NOT a
    real in->out DATA pair but a STRUCTURAL ARTIFACT of the surrounding Verilog /
    notation, so a coverage gap on it has no structural backing and must be
    ADVISORY (NO_CORROBORATION), not a hard block. chip-AGNOSTIC: pure
    Verilog/notation grammar, no chip / vendor / SKU literal.

    Three shapes, each independently observed to hard-block correct RTL:
      (A) the LHS digit is the numeric SUFFIX of an identifier — the char
          immediately before it is [A-Za-z_] — e.g. the "2" of `GRANT_2`,
          `STATE_3`. A state-encoding localparam legend, not a data operand.
          (cvdp_copilot_bus_arbiter_0001: "GRANT_2 = 3'b010" -> phantom 2->3.)
      (B) the RHS digit is the bit-WIDTH field of a sized literal — the char
          immediately after it is an apostrophe — e.g. the "3" of `3'b010`.
          A sized-literal width, not a data value. (same case.)
      (C) a binary-nibble = its-own-decimal-value notational GLOSS: the LHS is a
          bare binary-shaped multi-bit token (all 0/1, >=2 chars, NO base
          prefix) whose binary value EQUALS the RHS decimal AND differs from its
          own decimal reading — e.g. "0101 = 5" (bin 0101 = 5). This is a
          per-digit decomposition gloss of ONE worked example, not an
          independent input->output vector. (cvdp_copilot_binary_to_BCD_0010:
          the single example bcd_in=0010_0101_0111 -> 257 is split into
          0010=2 / 0101=5 / 0111=7 by the per-digit "Process MSD/Middle/LSD"
          annotation lines.)
    """
    lhs, rhs = m.group(1), m.group(3)
    s_lhs, e_rhs = m.start(1), m.end(3)
    # (A) LHS digit is the numeric suffix of an identifier.
    if s_lhs > 0 and re.match(r"[A-Za-z_]", text[s_lhs - 1]):
        return True
    # (B) RHS digit is immediately followed by a sized-literal apostrophe.
    if e_rhs < len(text) and text[e_rhs] == "'":
        return True
    # (C) binary-nibble = its-own-decimal-value notational gloss. To avoid eating
    # a GENUINE standalone binary->decimal vector (a real binary-to-BCD / decoder
    # test like "0101 -> 5"), the nibble must ALSO be a constituent of a larger
    # multi-nibble grouped binary literal in the spec (the decomposition SOURCE,
    # e.g. `0010_0101_0111`). A standalone vector has no such source and keeps
    # BLOCKING (ORGANIC #780 r2 Step-2.7 §4.05 — the gloss detector was too broad).
    if re.fullmatch(r"[01]{2,}", lhs) and re.fullmatch(r"\d+", rhs):
        try:
            if (int(lhs, 2) == int(rhs, 10) and int(lhs, 2) != int(lhs, 10)
                    and _binary_nibble_has_grouped_source(text, lhs)):
                return True
        except ValueError:
            pass
    return False


# Signed-ness / byte order / overflow / handshake — structural keyword facts.
_SIGNED_RE = re.compile(r"\b(signed|unsigned|two'?s\s+complement)\b", re.I)
_BYTEORDER_RE = re.compile(
    r"\b(little[- ]endian|big[- ]endian|msb[- ]first|lsb[- ]first|"
    r"byte\s+order|bit\s+order|byte\s+packing)\b", re.I)
_OVERFLOW_RE = re.compile(
    r"\b(overflow|underflow|saturat\w*|wrap[- ]?around|rounding|truncat\w*|clip\w*)\b",
    re.I)
_HANDSHAKE_RE = re.compile(
    r"\b(valid\s*/\s*ready|valid[- ]ready|handshake|ack(?:nowledge)?|req(?:uest)?"
    r"\s*/\s*ack|backpressure|stall)\b", re.I)


# ---------------------------------------------------------------------------
# Checklist extraction (DETERMINISTIC, structural)
# ---------------------------------------------------------------------------
def extract_checklist(spec_text: str) -> List[ChecklistItem]:
    items: List[ChecklistItem] = []

    # --- Ports (structural; reuse the canonical contract extractor) ---
    contract = _SRC.extract_spec_contract(spec_text, confirm=False)
    for p in contract.ports:
        items.append(ChecklistItem(
            kind="port",
            requirement=(f"port '{p.name}' is {p.direction}"
                         + (f", width {p.width}" if p.width != 1 else "")),
            evidence=f"{p.direction} {p.name}",
            coverage_tokens=[p.name]))

    # --- Reset ---
    if _has_reset(spec_text):
        mode, polarity = _detect_reset_mode_polarity(spec_text)
        qual = " ".join(x for x in (polarity, mode) if x) or "reset"
        items.append(ChecklistItem(
            kind="reset",
            requirement=f"reset behavior ({qual})",
            evidence=_reset_context(spec_text).strip()[:120] or "reset",
            coverage_tokens=["reset", "rst", "por"]))

    # --- Latency / timing ---
    lat = _detect_latency(spec_text)
    if lat:
        items.append(ChecklistItem(
            kind="latency",
            requirement=f"output timing: {lat}",
            evidence=lat,
            # NOTE: the bare '#' token was dead — attribute_coverage matches it
            # as `\b#\b` which can never match "#1"/"#10" (`#` is not a word
            # char, so there is no word boundary around it). Removed (#758).
            coverage_tokens=["latency", "cycle", "@(posedge", "@(negedge",
                             "posedge", "negedge"]))

    # --- Enumerated set(s) + the outside-the-set / default boundary ---
    for m in _ENUM_SET_RE.finditer(spec_text):
        members = _split_enum_members(m.group(1))
        if len(members) < 2:
            continue
        # A `{...}` is charged as an enumerated VALUE set ONLY when it is a real
        # value set (>=1 hex/dec/bin literal) or it sits in an explicit
        # set-builder context. An identifier-only brace-list with no set context
        # is a Verilog bit-field CONCATENATION / code expression (e.g. the
        # {E7,E6,...,E0} output-assembly column of a decoder table) and must NOT
        # demand per-member TB coverage. Window = the line/clause around the set.
        _ws, _we = m.start(), m.end()
        _ctx = spec_text[max(0, _ws - 80):min(len(spec_text), _we + 40)]
        # pre-brace text only — object-governing membership markers must directly
        # precede the `{` (the brace is the OBJECT: `one of {A,B,C}`), so a phrase
        # AFTER the brace ("{c1,c2,c3}: any of the bits") does not license it.
        _pre = spec_text[max(0, _ws - 60):_ws]
        if not _is_value_enum(m.group(1), members, _ctx, _pre):
            continue
        set_repr = "{" + ", ".join(members) + "}"
        # ORGANIC #770 r2 — a single-signal packed-vector CONCATENATION literal
        # (`sig = {6'b001100, 6'b110011, ...}`) is one value of one signal, NOT an
        # enumerated value set whose members must each be 'handled'. Record the
        # structural fact so run() downgrades it to advisory (CONTRADICTED), and
        # do NOT emit the outside-the-set boundary for it (a concat literal has no
        # member-level boundary). A genuine value set is untouched (still blocks).
        # (configurable_digital_low_pass_filter_0001)
        if _is_single_signal_concat_assignment(spec_text, m):
            items.append(ChecklistItem(
                kind="enum_set",
                requirement=f"valid enumerated set {set_repr} each handled",
                evidence=m.group(0),
                coverage_tokens=list(members),
                is_concat_literal=True))
            continue
        items.append(ChecklistItem(
            kind="enum_set",
            requirement=f"valid enumerated set {set_repr} each handled",
            evidence=m.group(0),
            coverage_tokens=list(members)))
        # The MOST-MISSED #697 pattern: the outside-the-set / default boundary.
        # Always emit it when an enumerated set is present — the boundary is a
        # testable requirement even if the prose default clause is implicit.
        dm = _DEFAULT_CLAUSE_RE.search(spec_text)
        default_result = (dm.group(2).strip() if dm else None)
        req = "outside-the-set value -> "
        req += (f"default ({default_result})" if default_result
                else "default / error path")
        items.append(ChecklistItem(
            kind="enum_boundary",
            requirement=req,
            evidence=(dm.group(0).strip() if dm else set_repr),
            # an outside-the-set value is, by definition, NOT one of the
            # members — coverage requires a TB token that is none of them.
            coverage_tokens=["__OUTSIDE_SET__"] ))
        # one enum boundary requirement is enough; subsequent sets still each
        # get their own enum_set item above, but the boundary item is global.
        break

    # --- Table rows (opcode/mode -> output) ---
    for row in _extract_table_rows(spec_text):
        items.append(ChecklistItem(
            kind="table_row",
            requirement=f"table row: {row['key']} -> {row['val']}",
            evidence=row["evidence"],
            coverage_tokens=[row["key"], row["val"]]))

    # --- Worked examples (in -> out pairs not already an enum/table) ---
    seen_examples = set()
    for m in _WORKED_EXAMPLE_RE.finditer(spec_text):
        # skip if this fragment is inside an enumerated `{...}` set
        if _inside_braces(spec_text, m.start()):
            continue
        sep = m.group(2)
        lhs, rhs = m.group(1), m.group(3)
        # #761: a bare '=' is overloaded (assignment / arithmetic equality /
        # encoding legend). Charge a '='-separated pair as a worked example ONLY
        # when it is a genuine in==out DATA pair — NOT a control-code -> label
        # ENCODING LEGEND ("00=90, 01=180, 10=270" on a 2-bit selector port
        # comment) nor an arithmetic-expression fragment ("... << 4 = 8'b...").
        # The unambiguous worked-example arrows (-> => →) bypass this guard.
        # Without it the gate misparses an enumeration legend as I/O vectors and
        # decides coverage by coincidental numeric-substring overlap
        # (image_rotate_0015).
        if sep == "=" and _is_control_code_legend(spec_text, m):
            continue
        key = (lhs, rhs)
        if key in seen_examples:
            continue
        seen_examples.add(key)
        # ORGANIC #780 (#770 r7, R8C1) — record whether this match is a structural
        # ARTIFACT (identifier-suffix LHS / sized-literal-width RHS / binary-
        # nibble=decimal gloss) rather than a real in->out data pair, so run()'s
        # #770 provenance loop can downgrade an uncorroborated worked_example gap
        # to advisory instead of hard-blocking correct RTL. chip-AGNOSTIC.
        items.append(ChecklistItem(
            kind="worked_example",
            requirement=f"worked example: {lhs} -> {rhs}",
            evidence=m.group(0),
            coverage_tokens=[lhs, rhs],
            we_structural_artifact=_worked_example_structural_artifact(
                spec_text, m)))

    # --- Signed-ness / byte order / overflow / handshake (structural facts) ---
    for rx, kind, label in (
        (_SIGNED_RE, "signedness", "signed-ness"),
        (_BYTEORDER_RE, "byte_order", "bit/byte order & packing"),
        (_OVERFLOW_RE, "overflow", "overflow / saturation / rounding"),
        (_HANDSHAKE_RE, "handshake", "handshake / protocol timing"),
    ):
        mm = rx.search(spec_text)
        # #760: the overflow family gets a clause-scoped preventive guard (the
        # #743 negation guard is wired ONLY into _has_reset/_has_clock and this
        # loop bypassed it). A "prevent/avoid/sized to ... overflow" width-sizing
        # note (often carried verbatim from an RTL inline comment) is a
        # STRUCTURAL fact about how the design AVOIDS the condition, not a
        # behavioral requirement to HANDLE it — re-scan the clauses and accept
        # only the FIRST mention whose clause is NOT a bare preventive/width note
        # (a co-occurring active-handling verb saturate/clamp/wrap/... keeps it).
        # The other three families are unchanged (output-stable). chip-AGNOSTIC.
        if kind == "overflow":
            mm = None
            for clause in _clauses(spec_text.lower()):
                cm = rx.search(clause)
                if cm and not _is_preventive_structural_fact(clause, cm.group(0)):
                    mm = cm
                    break
        if mm:
            items.append(ChecklistItem(
                kind=kind,
                requirement=f"{label}: {mm.group(0).strip()}",
                evidence=mm.group(0).strip(),
                coverage_tokens=[mm.group(1) if mm.groups() else mm.group(0)]))

    # --- CVDP program-first structural extractors (register-map / enum-set +
    #     boundary / FSM transitions / worked-examples / rounding-packing). Each
    #     emits ChecklistItem-shaped dicts anchored to a real structure; they
    #     recover the four classes the legacy extractor above misses. Items are
    #     merged with the above by extract_chain's _item_key (dups collapse). ---
    for _ext in _CVDP_EXTRACTORS:
        try:
            for d in (_ext.extract(spec_text) or []):
                if not isinstance(d, dict) or not d.get("kind") or not d.get("requirement"):
                    continue
                items.append(ChecklistItem(
                    kind=str(d["kind"]),
                    requirement=str(d["requirement"]),
                    evidence=str(d.get("evidence", ""))[:200],
                    coverage_tokens=list(d.get("coverage_tokens", []) or []),
                    provenance=str(d.get("provenance", "STRUCTURAL")),
                    block_eligible=bool(d.get("block_eligible", True))))
        except Exception:
            # an extractor must never break the canonical checklist — §4.05 it stays
            # additive; a malformed extractor result is dropped, not propagated.
            continue

    return items


def _item_key(it: ChecklistItem) -> tuple:
    """Stable identity for merging the same requirement across chain stations.

    enum_boundary collapses to one global boundary requirement regardless of the
    exact default-result prose, so an enum present at several stations merges.
    Other kinds key on (kind, normalised requirement)."""
    if it.kind == "enum_boundary":
        return ("enum_boundary",)
    return (it.kind, it.requirement.strip().lower())


def extract_chain(stations: dict) -> List[ChecklistItem]:
    """Run the structural extractor on EACH provided input-chain station and
    MERGE identical requirements, recording the stations each was found at + the
    most-downstream one (which routes the extraction-gap fix).

    `stations` maps a STATION_ORDER key -> its text (only the provided ones).
    A requirement found ONLY upstream (e.g. user_prompt) but missing from a
    downstream station means that downstream station dropped it — captured by
    last_station + STATION_ROUTE at attribution time.
    """
    merged: "dict[tuple, ChecklistItem]" = {}
    for st in STATION_ORDER:
        text = stations.get(st)
        if not text:
            continue
        for it in extract_checklist(text):
            k = _item_key(it)
            if k in merged:
                if st not in merged[k].stations:
                    merged[k].stations.append(st)
                # ORGANIC #780 (#770 r7, R8C1) — a worked_example identified as a
                # structural artifact at ANY station stays an artifact after the
                # cross-station merge (the structural shape is the same text).
                if it.we_structural_artifact:
                    merged[k].we_structural_artifact = True
            else:
                it.stations = [st]
                merged[k] = it
    items = list(merged.values())
    for it in items:
        it.last_station = _last_station(it.stations)
    return items


# A downstream schema/drafting instruction is not a design requirement.  These
# shapes are deliberately evaluated after cross-station merge: the first
# (user-prompt) evidence remains attached to a merged item, so an explicit
# upstream denial such as "no reset pin" wins over a generated L-doc's generic
# "reset behavior verification" boilerplate.
_NON_REQUIREMENT_EVIDENCE_RE = re.compile(
    r"\b(?:does\s+not\s+specify|not\s+specified|deferred\s+to|"
    r"look\s+for|not\s+applicable)\b",
    re.IGNORECASE,
)
_EMPTY_JSON_EVIDENCE_RE = re.compile(
    r'"[^"]+"\s*:\s*(?:\[\s*\]|\{\s*\}|null|false|"")',
    re.IGNORECASE,
)
_CHANNEL_REQ_RE = re.compile(r"\bwith\s+(\d+)\s+channel", re.IGNORECASE)


def _is_non_requirement_artifact(it: ChecklistItem) -> bool:
    """Reject only evidence that structurally states absence/instruction/no-op.

    This is intentionally narrow: affirmative feature prose and non-empty JSON
    continue to produce blocking requirements.
    """
    evidence = it.evidence.strip()
    low = evidence.lower()
    if it.kind == "reset":
        explicit_absence = re.search(
            r"\b(?:no|without)\s+(?:\w+\s+){0,3}reset(?:\s+pin)?\b",
            evidence,
            re.IGNORECASE,
        )
        if explicit_absence or not _mention_present_unnegated(
                evidence, r"\breset\b|\brst\b|\bpor\b"):
            return True
    if it.kind == "rounding_mode" and re.fullmatch(r"floorplans?", low):
        return True
    if it.kind in {"scan_chain", "jtag_tap", "bist", "test_mode"} \
            and _NON_REQUIREMENT_EVIDENCE_RE.search(evidence):
        return True
    if it.kind in {"calibration_field", "calibration_procedure"} \
            and _EMPTY_JSON_EVIDENCE_RE.search(evidence):
        return True
    if it.kind == "analog_converter":
        match = _CHANNEL_REQ_RE.search(it.requirement)
        if match:
            count = re.escape(match.group(1))
            # The same integer must qualify channel(s)/copies in the evidence;
            # a decimal tail ("1.2 V ... 6 channels") is not a 2-channel ADC.
            qualified = re.search(
                rf"(?<![\d.]){count}(?!\d)[^.;\n|]{{0,40}}?"
                rf"\b(?:channels?|copies|ch)\b",
                evidence,
                re.IGNORECASE,
            )
            if not qualified:
                return True
    return False


# Physical/PVT facts are genuine requirements, but a two-state digital RTL
# self-TB cannot exercise voltage, current, temperature, or slew.  Keep them in
# the report and route them to AMS/corner sign-off; do not demand that an RTL TB
# game token coverage by putting "1.8 V" in a comment.
_AMS_ONLY_KINDS = frozenset({
    "supply_voltage", "current_spec", "temperature_range", "slew_rate",
})


def _inside_braces(text: str, pos: int) -> bool:
    """True if `pos` falls inside a `{...}` enumerated set."""
    for m in _ENUM_SET_RE.finditer(text):
        if m.start() <= pos < m.end():
            return True
    return False


# A simple GFM / column table row `key -> val` extractor (opcode/mode tables).
_GFM_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$", re.M)


def _markdown_table_text(text: str) -> str:
    """ORGANIC #770 Step-2.7 — concatenated text of every markdown TABLE ROW in
    `text` (a `|`-delimited line that belongs to a GFM table: it sits next to a
    `|---|`-style delimiter row). Used to tell whether a behavioral requirement
    (latency / reset / overflow / …) has a STRUCTURAL source (stated in a table
    cell, e.g. `| Output latency | 1 clock cycle |`) versus only a free-prose
    mention — a structural-sourced behavioral item must NOT be downgraded to
    advisory even when the RTL appears to contradict it. chip-AGNOSTIC, pure GFM
    grammar; no-leak biased (it only PROMOTES items to STRUCTURAL)."""
    lines = text.splitlines()
    n = len(lines)
    out: List[str] = []
    i = 0
    _delim = re.compile(r"\|?[\s:\-|]+\|?")
    while i < n - 1:
        if lines[i].count("|") >= 2 and "-" in lines[i + 1] \
                and _delim.fullmatch(lines[i + 1].strip()):
            out.append(lines[i])            # header row
            j = i + 2
            while j < n and lines[j].count("|") >= 2:
                out.append(lines[j])        # body rows
                j += 1
            i = j
        else:
            i += 1
    return "\n".join(out)


def _output_timing_table_text(text: str) -> str:
    """ORGANIC #770 r2 — concatenated text of only the OUTPUT-TIMING markdown
    table rows: a `|`-delimited GFM table ROW whose KEY/first-column cell (or a
    column header) is about OUTPUT / LATENCY / TIMING (e.g.
    `| Output latency | 1 clock cycle |`, `| Timing | registered |`), NOT an
    internal-signal / helper / description row.

    The shipped Step-2.7 `_markdown_table_text` returns EVERY table row, so the
    latency promotion fired on an `## Internal Signals` helper table whose
    Description cell merely says 'Registered version of the sel signal'
    (axis_mux_0001) — re-blocking a pure-combinational design. Scoping the
    latency/timing promotion to OUTPUT-TIMING rows fixes that while a genuine
    `| Output latency | 1 clock cycle |` row still promotes (no-leak). A row
    qualifies if its KEY cell (or any column header of its table) matches the
    output/latency/timing vocabulary AND is NOT an internal-signal/helper
    descriptor. chip-AGNOSTIC: pure GFM grammar + output-timing header vocabulary;
    no chip / vendor / SKU literal."""
    # vocabulary that marks a row/column as OUTPUT-TIMING (the thing whose latency
    # is a real spec requirement) — distinct from an internal-signal helper row.
    timing_key = re.compile(
        r"\b(output\s*(?:timing|latency)?|latency|timing|"
        r"clock\s*cycles?|throughput|delay|pipeline\s*(?:depth|stage)?)\b",
        re.I)
    # an INTERNAL-SIGNAL / helper descriptor column whose 'Registered' mention is
    # about an internal helper net, NOT the module's output timing.
    helper_key = re.compile(
        r"\b(internal|helper|signal|description|note|comment|wire|reg(?:ister)?\s*name)\b",
        re.I)
    lines = text.splitlines()
    n = len(lines)
    out: List[str] = []
    i = 0
    _delim = re.compile(r"\|?[\s:\-|]+\|?")
    while i < n - 1:
        if lines[i].count("|") >= 2 and "-" in lines[i + 1] \
                and _delim.fullmatch(lines[i + 1].strip()):
            header = [c.strip().strip("`*_ ").lower()
                      for c in lines[i].strip().strip("|").split("|")]
            header_timing = any(timing_key.search(h) for h in header)
            j = i + 2
            while j < n and lines[j].count("|") >= 2:
                cells = [c.strip().strip("`*_ ")
                         for c in lines[j].strip().strip("|").split("|")]
                key_cell = cells[0].lower() if cells else ""
                row_text = " ".join(cells).lower()
                # ORGANIC #770 r2 Step-2.7 — a row is OUTPUT-TIMING if a timing
                # keyword appears in its key cell, ANY value cell, OR a column
                # header (the earlier key-cell/header-only scan missed a latency
                # stated in a Details VALUE cell — a real forgot-to-register bug).
                row_has_timing = (header_timing
                                  or timing_key.search(key_cell)
                                  or any(timing_key.search(c.lower())
                                         for c in cells[1:]))
                # NARROW internal-helper exclusion: only skip a row whose KEY is an
                # internal-net descriptor AND whose value cell is the specific
                # 'Registered version of the <sig> signal' helper phrasing
                # (axis_mux_0001) — never a blanket Signal/Description-table skip.
                is_internal_helper = bool(
                    re.search(r"registered\s+version\s+of\s+the\s+\w+\s+signal",
                              row_text)
                    or (helper_key.search(key_cell)
                        and re.search(r"\bregistered\s+version\b", row_text)))
                if row_has_timing and not is_internal_helper:
                    out.append(lines[j])
                j += 1
            i = j
        else:
            i += 1
    return "\n".join(out)


def _extract_table_rows(text: str) -> List[dict]:
    """Extract opcode/mode -> output rows from a 2+-column markdown table.

    Conservative + structural: only a `|`-delimited table whose header has a
    key-shaped column (opcode/mode/input/cmd/sel) AND an output-shaped column
    (output/out/result/q/value) is read. A generic report table never matches.
    """
    rows: List[dict] = []
    lines = text.splitlines()
    n = len(lines)
    i = 0
    key_hdr = re.compile(r"^(opcode|op|mode|input|in|cmd|command|sel|select|addr|state)$", re.I)
    val_hdr = re.compile(r"^(output|out|result|q|value|val|next|action|response)$", re.I)
    while i < n - 1:
        if lines[i].count("|") < 2:
            i += 1
            continue
        header = [c.strip().strip("`*_ ").lower() for c in lines[i].strip().strip("|").split("|")]
        delim = lines[i + 1].strip()
        if not re.fullmatch(r"\|?[\s:\-|]+\|?", delim) or "-" not in delim:
            i += 1
            continue
        kcol = next((k for k, h in enumerate(header) if key_hdr.fullmatch(h)), None)
        vcol = next((k for k, h in enumerate(header) if val_hdr.fullmatch(h)), None)
        if kcol is None or vcol is None:
            i += 1
            continue
        j = i + 2
        while j < n and lines[j].count("|") >= 2:
            cells = [c.strip().strip("`*_ ") for c in lines[j].strip().strip("|").split("|")]
            if re.fullmatch(r"[\s:\-|]+", "|".join(cells)):
                j += 1
                continue
            if len(cells) > max(kcol, vcol) and cells[kcol] and cells[vcol]:
                rows.append({"key": cells[kcol], "val": cells[vcol],
                             "evidence": lines[j].strip()})
            j += 1
        i = j if j > i else i + 1
    return rows


# #760 (bcd_adder_0001) — VALUE-REGION coverage for the overflow/saturation/
# truncation item. The shipped attribute_coverage() marked the overflow item
# covered ONLY via a whole-word literal match of the SPEC word (e.g. 'truncated')
# in non-comment TB code. That conflates VOCABULARY with coverage and is gameable
# both directions: a degenerate TB declaring an unused `reg truncated;` and
# driving only 0+0 PASSES, while a semantically-complete exhaustive truncation TB
# that names its var 'low4'/'mod16' (no literal word) is spuriously BLOCKED. The
# __OUTSIDE_SET__ enum-boundary branch already shows the right precedent: demand
# the TB STIMULATE the region, not merely NAME it. This helper detects whether
# the TB structurally EXERCISES an overflow/region decision: a magnitude/range
# comparison (<, >, <=, >=) that selects the overflow-vs-normal path.
# Equality/inequality (===,!==,==,!=) — pass/fail assertions — and shifts
# (<<,>>) are NOT region decisions and are excluded.
# chip-AGNOSTIC: pure range-decision grammar, no chip / vendor / SKU literal.
_TB_RANGE_DECISION_RE = re.compile(r"(?<![<>=!])(<=|>=|<|>)(?![<>=])")


def _tb_exercises_overflow_region(tb_clean: str) -> bool:
    """True iff the TB contains a magnitude/range comparison that can select the
    overflow / out-of-range path (the value-region analogue of the
    __OUTSIDE_SET__ outside-the-set stimulus requirement). Shift operators and
    equality/inequality comparators are stripped first so only a genuine
    magnitude decision counts. (#760)"""
    # remove shifts and equality/inequality compound operators so they cannot be
    # mistaken for a magnitude decision.
    t = re.sub(r"<<|>>|===|!==|==|!=", " ", tb_clean)
    return bool(_TB_RANGE_DECISION_RE.search(t))


# ORGANIC-20260618 (car_parking_management_0015) — `rounding` and `truncation`
# are lumped into the overflow family by `_OVERFLOW_RE`, but they are NOT a
# saturation/wrap value-region decision: a ceil/floor-division design has no
# range comparator selecting an "overflow path", so the range-decision model
# (`_tb_exercises_overflow_region`) cannot be satisfied by a faithful rounding TB
# and the item hard-blocked a correct division-rounding design. A rounding/
# truncation requirement is covered when the TB structurally exercises rounding:
# the ceil/floor-division IDIOM (`(x + N-1)/N`, `(x + DIV-1)`, `$ceil`/`$floor`)
# OR a REFERENCE-MODEL equality assertion (`got !== exp`, `===`/`!==`/`==`/`!=`
# between two non-literal operands) that checks the rounded result. A real
# saturate/overflow/wrap/clip spec is unaffected — those trigger words keep the
# strict range-decision model (this branch fires only for rounding/truncation).
# §4.05 no-leak: a rounding TB that drives no division idiom AND no reference
# equality still GAPs. chip-AGNOSTIC: pure ceil/floor-idiom + equality grammar.
_TB_CEIL_FLOOR_IDIOM_RE = re.compile(
    r"\$\s*(?:ceil|floor)\b"                      # $ceil / $floor
    r"|\+\s*\(?\s*[A-Za-z_0-9']+\s*-\s*1\s*\)?\s*\)?\s*/"   # (x + N-1)/
    r"|/\s*[A-Za-z_0-9']+\s*\+\s*\(",             # x / N + (rem != 0)
    re.I)
_TB_REF_EQ_RE = re.compile(
    r"([A-Za-z_]\w*)(?:\s*\[[^\]]*\])?\s*(?:===|!==|==|!=)\s*"
    r"([A-Za-z_]\w*)(?:\s*\[[^\]]*\])?(?!\s*[\w'])")


def _tb_exercises_rounding(tb_clean: str) -> bool:
    """True iff the TB structurally exercises a rounding/truncation computation:
    a ceil/floor-division idiom, OR a reference-model equality assertion between
    two non-literal operands (`got !== exp`). chip-AGNOSTIC."""
    if not tb_clean:
        return False
    if _TB_CEIL_FLOOR_IDIOM_RE.search(tb_clean):
        return True
    return bool(_TB_REF_EQ_RE.search(tb_clean))


# ORGANIC #770 round-2 (axis_joiner_0001) — STRUCTURAL-STIMULUS coverage for the
# handshake item, the value-region analogue applied to a valid/ready protocol.
# The shipped attribute_coverage() marked the handshake item covered ONLY when
# the TB literally NAMES one of the spec coverage tokens (e.g. the noun
# 'handshake' or the slash-joined token 'valid/ready'). That conflates VOCABULARY
# with coverage: a faithful AXI-Stream TB drives the protocol by TOGGLING the
# concrete `m_tready`/`s_tvalid` handshake signals to model backpressure — and
# never spells the noun 'handshake' anywhere — yet was scored UNCOVERED and
# hard-BLOCKed under --strict. This helper detects whether the TB structurally
# EXERCISES the handshake: it assigns (drives) a valid/ready-shaped handshake
# signal to BOTH an asserted (1/high) AND a deasserted (0/low) value — i.e. it
# toggles the handshake line, the structural signature of backpressure / a real
# valid/ready exchange. A TB that merely declares the wires but never drives a
# both-polarity toggle on a handshake-shaped signal is NOT covering — the gap is
# real and STILL reported. chip-AGNOSTIC: pure valid/ready signal-naming +
# both-polarity-drive grammar; no chip / vendor / SKU literal.
# ORGANIC #770 r2 Step-2.7 — restricted to the VALID/READY two-phase protocol
# line ONLY. The earlier broad set (ack/req/stall/en) matched ubiquitous local
# control regs (dma_req/internal_req/irq_ack/stall_dbg) that toggle in nearly
# every TB, so a decoy toggle spuriously satisfied the handshake item. valid/ready
# (and the vld/rdy abbreviations) ARE the handshake exchange; a real protocol TB
# toggles one of them.
_HANDSHAKE_SIGNAL_RE = re.compile(
    r"[A-Za-z_]\w*(?:valid|ready|vld|rdy)\b"
    r"|(?:valid|ready|vld|rdy)[A-Za-z_]*\b",
    re.I)
# A blocking/non-blocking assignment to <signal> of a 0/1 (or sized-literal 0/1)
# RHS. Captured so we can confirm BOTH a high-drive and a low-drive on the SAME
# handshake-shaped signal (the toggle = backpressure structural signature).
_HS_DRIVE_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s*(?:<=|=)\s*"
    r"(?:\d+'[bBdDhH])?\s*([01])\b",
    re.I)
# ORGANIC #770 r3 — a valid/ready signal that is ASSIGNED AT ALL (any RHS: a
# variable, an expression, a stall-loop control — `m_tready = (i % 3 != 0)`),
# not only a literal 0/1. The r2 literal-toggle detector missed a backpressure
# pattern driven through a loop/expression (axis_joiner_0001), so a correct AXIS
# TB with real backpressure was scored UNCOVERED. Capture every LHS assignment.
_HS_ANY_DRIVE_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s*(?:<=|=)(?!=)\s*\S",
    re.I)


def _is_handshake_signal(name: str) -> bool:
    n = name.lower()
    return bool(_HANDSHAKE_SIGNAL_RE.fullmatch(n)
                or _HANDSHAKE_SIGNAL_RE.search(n))


# ORGANIC #770 r6 — a NAMED instance port connection `.<dut_port>(<tb_local>)`.
# The TB declares a LOCAL reg (`reg m_tready;`) and wires it to the DUT's port
# (`.m_axis_tready(m_tready)`); it then TOGGLES the local reg. The DUT-port set
# holds the PORT name (`m_axis_tready`), so a membership test on the toggled
# LOCAL name (`m_tready`) misses. This captures the local↔port alias so a driven
# local name can be mapped to its DUT port before the membership test.
_NAMED_CONN_RE = re.compile(
    r"\.\s*([A-Za-z_]\w*)\s*\(\s*([A-Za-z_]\w*)\s*\)")


def _tb_local_to_dut_port(tb_clean: str) -> Dict[str, str]:
    """Map each TB-local signal name -> the DUT port it is connected to via a
    NAMED instance connection `.dut_port(local)`. chip-AGNOSTIC, pure grammar.
    (ORGANIC #770 r6, axis_joiner_0001 `.m_axis_tready(m_tready)`.)"""
    amap: Dict[str, str] = {}
    for m in _NAMED_CONN_RE.finditer(tb_clean):
        dut_port, local = m.group(1).lower(), m.group(2).lower()
        # a same-name connection (`.clk(clk)`) is a no-op for the alias.
        if local != dut_port:
            amap[local] = dut_port
    return amap


def _tb_exercises_handshake_region(tb_clean: str,
                                   rtl_ports_lower: Optional[set] = None,
                                   ambiguous_ports: Optional[set] = None) -> bool:
    """True iff the TB structurally exercises a valid/ready handshake: it drives
    at least one valid/ready DUT-interface port to BOTH a high (1) and a low (0)
    value — the backpressure / handshake-exchange toggle signature. Merely
    declaring the handshake wires without ever toggling one is NOT coverage.

    ORGANIC #770 r2 Step-2.7: the toggled signal must be an actual DUT port
    (when the RTL port set is known) so a decoy local control reg cannot satisfy
    the item; and the signal must be a valid/ready line (not the broad
    req/ack/stall set). ORGANIC #770 r3 (+ r3 Step-2.7): coverage requires a real
    BACKPRESSURE TOGGLE of a valid/ready DUT port — EITHER two distinct literal
    0/1 writes, OR ≥2 assignments with DISTINCT right-hand sides (the line is
    re-driven to different values over time), OR an assignment whose RHS is a
    genuine LOOP/TIME-VARYING expression (it references the for-loop control
    variable). A single drive of any CONSTANT value — whether a literal, a
    parameter/macro/named-constant, or a constant arithmetic expression like
    `2-1` — is just HOLDING the line and does NOT exercise the handshake (r3
    Step-2.7 caught the syntactic "non-literal ⇒ non-constant" conflation).
    chip-AGNOSTIC. (axis_joiner_0001, #770 r2/r3)"""
    # ORGANIC #770 r6 — TB-local → DUT-port alias from named connections, so a
    # toggled local reg (`m_tready`) wired to a DUT handshake port
    # (`.m_axis_tready(m_tready)`) is recognised as exercising that DUT port.
    alias = _tb_local_to_dut_port(tb_clean)

    def _is_dut_hs(sig: str) -> bool:
        s = sig.lower()
        mapped = alias.get(s, s)
        # Resolve the DUT PORT this driven signal reaches: the signal itself if it
        # is a port, else the port it aliases to via a named connection.
        if rtl_ports_lower is None:
            # no port set to judge — accept on the handshake-shaped name alone
            # (the signal itself, or the port it maps to).
            return _is_handshake_signal(s) or _is_handshake_signal(mapped)
        if s in rtl_ports_lower:
            dut_port = s
        elif mapped in rtl_ports_lower:
            # ORGANIC #770 r6 Step-2.7 §4.05: the credit here comes via a NAMED
            # CONNECTION alias (`.mapped(s)`), not s being a DUT port itself. If
            # `mapped` is a port name shared by ≥2 distinct TB-instantiated module
            # types, the connection cannot be attributed to the DUT instance (it
            # may target a sibling MONITOR's same-named port) → do NOT credit the
            # handshake via this ambiguous alias.
            if ambiguous_ports and mapped in ambiguous_ports:
                return False
            dut_port = mapped
        else:
            return False                      # reaches no DUT port → decoy
        # the DUT PORT it drives must itself be a valid/ready handshake line. A
        # local whose NAME contains 'ready' but is wired to a NON-handshake port
        # (e.g. `.m_axis_tdata(myready)`) is NOT exercising the handshake (r6
        # Step-2.7: judge the PORT, not the local name).
        return _is_handshake_signal(dut_port)

    high: set = set()
    low: set = set()
    for m in _HS_DRIVE_RE.finditer(tb_clean):
        sig, val = m.group(1), m.group(2)
        if not _is_dut_hs(sig):
            continue
        (high if val == "1" else low).add(sig.lower())
    if high & low:
        return True
    # the for-loop control variable name(s) — a drive whose RHS references one is
    # genuinely time-varying (a stall pattern), not a held constant.
    loop_vars = {lm.group(1).lower()
                 for lm in re.finditer(r"\bfor\s*\(\s*([A-Za-z_]\w*)\s*=",
                                       tb_clean)}
    rhs_seen: Dict[str, set] = {}
    loop_driven: set = set()
    for m in _HS_ANY_DRIVE_RE.finditer(tb_clean):
        sig = m.group(1)
        if not _is_dut_hs(sig):
            continue
        rhs = tb_clean[m.end() - 1:].split(";", 1)[0].strip()
        rhs_seen.setdefault(sig.lower(), set()).add(re.sub(r"\s+", "", rhs))
        # RHS references a loop control var (`(i % 3 != 0)`, `i[0]`, …) → toggling.
        ids = set(re.findall(r"[A-Za-z_]\w*", rhs))
        if ids & loop_vars:
            loop_driven.add(sig.lower())
    if loop_driven:
        return True
    # ≥2 DISTINCT right-hand sides on the same port = the line is re-driven to
    # different values over time (a real toggle); a single constant drive is not.
    return any(len(v) >= 2 for v in rhs_seen.values())


# ORGANIC #770 round-2 (configurable_digital_low_pass_filter_0001) — a
# SINGLE-SIGNAL packed-vector CONCATENATION literal is NOT an enumerated value
# set. `data_in = {6'b001100, 6'b110011, 6'b010101, 6'b101010}` is one Verilog
# assignment whose `{...}` RHS positionally concatenates sub-fields into ONE
# 24-bit value of ONE signal — the sub-fields are bit-slices of a single packed
# word, NOT alternative values the design must each 'handle'. The extractor's
# _is_value_enum already accepts this brace-list as a value set (its members are
# sized literals), so it demands per-member TB coverage and hard-BLOCKs a TB that
# drives the packed signal with a normal value. This detector recognises the
# concatenation-ASSIGNMENT shape: a `lhs = {member, member, ...}` (or `<=`) where
# the lhs is a single identifier (optionally bit-selected) and the braces are the
# whole RHS — so the brace-list is downgraded (CONTRADICTED → advisory) rather
# than charged as an enumerated value set. A genuine enumerated set ("mode in
# {0x1,0x2,0x3}", a case-label set, a table column) is NOT an assignment RHS and
# is untouched (still STRUCTURAL → BLOCKs). chip-AGNOSTIC: pure Verilog
# concatenation-assignment grammar; no chip / vendor / SKU literal.
_CONCAT_ASSIGN_RE = re.compile(
    r"[A-Za-z_]\w*(?:\s*\[[^\]]*\])?\s*(?:<=|=|=\s*assign\b)?\s*$")


def _is_single_signal_concat_assignment(spec_text: str, brace_match) -> bool:
    """True iff the `{...}` at `brace_match` is the RHS of a single-signal
    assignment (`sig = {a, b, c}` / `sig <= {a, b, c}` / `assign sig = {...}`),
    i.e. a packed-vector CONCATENATION literal of ONE signal — not an enumerated
    value set. The text immediately BEFORE the `{` must end with
    `<identifier> [optional bit-select] =|<=` and the `{...}` must be (modulo
    trailing `;`/whitespace) the WHOLE right-hand side (no comma joining it to a
    sibling list element). chip-AGNOSTIC. (#770 r2)"""
    pre = spec_text[:brace_match.start()]
    # ORGANIC #770 r2/r3 — do NOT downgrade when the surrounding text marks a
    # genuine ENUMERATED VALUE SET with STRONG membership semantics ('any other
    # value is reserved/illegal', 'accepts only', 'must handle each', 'one of the
    # following', 'legal/allowed values'). `GAIN_LEVELS = {8'h10, 8'h20, ...}`
    # with 'any other value is reserved' has identical syntax to a packed concat
    # but each member is a distinct LEGAL value — it must stay BLOCK-eligible.
    # r3: the BROAD `_SET_CONTEXT_RE` (a bare 'one of', 'valid value') was REMOVED
    # from this override — it fired on DSP/filter prose describing the bit-fields
    # ('each tap is one of the calibrated levels') and wrongly KEPT a real
    # single-signal packed concatenation as a value-set
    # (configurable_digital_low_pass_filter_0001). Only the NARROWED strong-marker
    # `_ENUM_VALUE_CTX_RE` gates the override now.
    ctx_window = spec_text[max(0, brace_match.start() - 200):
                           brace_match.end() + 120]
    if _ENUM_VALUE_CTX_RE.search(ctx_window):
        return False
    # take the current line's text before the brace (assignment lives on one line)
    line_start = pre.rfind("\n") + 1
    pre_line = pre[line_start:]
    # strip a leading `assign` keyword so `assign sig = {...}` is recognised too.
    pre_line = re.sub(r"^\s*assign\b", "", pre_line, flags=re.I)
    pre_stripped = pre_line.rstrip()
    if not (pre_stripped.endswith("=") or pre_stripped.endswith("<=")):
        return False
    # the signal being assigned is the LAST identifier (+ optional bit-select)
    # immediately before the `=`/`<=`. r3: take only that trailing token — a
    # prose-prefixed assignment ("the input sample shift register is data_in =
    # {...}") left the whole phrase as the lhs and failed the identifier
    # fullmatch, silently skipping the concat downgrade (lpf FP). A comma right
    # before the `=` (a list element) is still rejected.
    lhs_region = re.sub(r"(<=|=)\s*$", "", pre_stripped).rstrip()
    if lhs_region.endswith(","):
        return False
    mlhs = re.search(r"([A-Za-z_]\w*(?:\s*\[[^\]]*\])?)\s*$", lhs_region)
    if not mlhs:
        return False
    lhs = mlhs.group(1).strip()
    # ORGANIC #770 r2 Step-2.7 — the SET-CONTEXT vocabulary gate above
    # (`_SET_CONTEXT_RE` / `_ENUM_VALUE_CTX_RE` over the surrounding window) is the
    # discriminator: a value-SET written compactly as `NAME = {v1, v2, ...}` is
    # surrounded by enumeration vocabulary ('discrete levels', 'one of', 'any
    # other value is reserved', 'each handled') → NOT downgraded (kept block). A
    # bare `sig = {a, b, c}` with NO such vocabulary is a packed concatenation
    # literal → downgraded to advisory. (A same-width-members heuristic was tried
    # and REMOVED: same-width members are equally a 3×6-bit packed concat or a
    # value-set, so width alone cannot discriminate — the vocabulary does.)
    return True


# ---------------------------------------------------------------------------
# Coverage attribution against the authored TESTBENCH
# ---------------------------------------------------------------------------
def attribute_coverage(items: List[ChecklistItem], tb_text: Optional[str],
                       enum_members_all: List[str],
                       rtl_ports_lower: Optional[set] = None,
                       ambiguous_ports: Optional[set] = None) -> None:
    """Set .covered / .coverage_note for each checklist item based on whether
    the authored TB exercises it. No TB => everything UNCOVERED.

    `rtl_ports_lower` (ORGANIC #770 r2 Step-2.7) is the RTL's port-name set; the
    handshake structural-coverage check restricts its toggle detection to actual
    DUT-interface ports so a decoy local control reg (dma_req/internal_req/…)
    toggling in the TB cannot spuriously satisfy the protocol-handshake item."""
    if tb_text is None:
        for it in items:
            it.covered = False
            it.coverage_note = "no testbench supplied"
        return

    tb_clean = _SRC.strip_comments(tb_text)
    tb_low = tb_clean.lower()
    # literal value tokens the TB stimulates (hex/dec/bin literals)
    tb_values = set(re.findall(r"0[xXbB][0-9A-Fa-f_]+|\b\d+'[bdh][0-9A-Fa-fxXzZ_]+|\b\d+\b",
                               tb_clean))
    tb_values_norm = {_norm_value(v) for v in tb_values}

    members_norm = {_norm_value(m) for m in enum_members_all
                    if re.fullmatch(r"(0[xXbB][0-9A-Fa-f_]+|\d+|\d+'[bdh][0-9A-Fa-fxXzZ_]+)", m)}

    for it in items:
        # The enum-boundary item needs an OUTSIDE-the-set value in the TB.
        if "__OUTSIDE_SET__" in it.coverage_tokens:
            # When the enum has NO value-shaped members (identifier-only set),
            # "outside the set" is undefinable over value literals, so the
            # boundary requirement is structurally unsatisfiable for ANY TB.
            # Auto-satisfy it instead of unconditionally failing — the legacy
            # `... if members_norm else set()` made it impossible to pass
            # (decoder_0011). A value set with members still demands a real
            # outside-the-set stimulus below.
            if not members_norm:
                it.covered = True
                it.coverage_note = ("enum has no value-shaped members; "
                                    "outside-the-set boundary not value-testable "
                                    "(auto-satisfied)")
                continue
            outside = tb_values_norm - members_norm
            it.covered = bool(outside)
            it.coverage_note = (
                f"TB stimulates outside-the-set value(s) {sorted(outside)}"
                if outside else
                "TB only stimulates listed members; no outside-the-set value")
            continue
        # #760: the overflow/saturation/truncation item is a VALUE-REGION
        # requirement, not a vocabulary one. Mark covered iff the TB structurally
        # EXERCISES the overflow region (a magnitude/range decision selecting the
        # overflow-vs-normal path). The literal spec token is kept as a
        # sufficient-WITH-stimulus corroborating signal but is no longer
        # sufficient ALONE (so a token-only no-stimulus TB no longer passes) nor
        # necessary (so a genuine exhaustive truncation TB that names its var
        # differently no longer BLOCKs). A real uncovered-overflow TB — one that
        # never drives the region (no range decision) — still GAPs / BLOCKs.
        if it.kind == "overflow":
            token_hit = any(
                tok.strip()
                and re.search(r"\b" + re.escape(tok.strip().lower()) + r"\b",
                              tb_low)
                for tok in it.coverage_tokens)
            region = _tb_exercises_overflow_region(tb_clean)
            # ORGANIC-20260618 — a rounding/truncation trigger (NOT saturate/
            # overflow/wrap/clip) is not a value-region decision; accept the
            # ceil/floor-division idiom or a reference-model equality as covering.
            _is_rounding = any(
                re.fullmatch(r"rounding|truncat\w*", (tok or "").strip().lower())
                for tok in it.coverage_tokens)
            rounding = _is_rounding and _tb_exercises_rounding(tb_clean)
            it.covered = bool(region or rounding)
            if rounding and not region:
                it.coverage_note = ("TB exercises rounding/truncation (ceil/floor "
                                    "division idiom or reference-model equality)")
            elif region and token_hit:
                it.coverage_note = ("TB exercises overflow region (range "
                                    "decision) and names the spec token")
            elif region:
                it.coverage_note = ("TB exercises overflow region (range "
                                    "decision selecting the out-of-range path)")
            elif token_hit:
                it.coverage_note = ("TB names the spec token but never drives a "
                                    "range decision into the overflow region "
                                    "(vocabulary without stimulus)")
            else:
                it.coverage_note = ("no TB stimulus into the overflow region and "
                                    f"no reference to {it.coverage_tokens}")
            continue
        # ORGANIC #770 r2 (axis_joiner_0001): the handshake item is a
        # STRUCTURAL-STIMULUS requirement, not a vocabulary one. A faithful
        # valid/ready TB exercises the protocol by TOGGLING the concrete
        # `m_tready`/`s_tvalid` handshake signals (backpressure) and need never
        # spell the noun 'handshake'. Mark covered iff the TB drives a
        # handshake-shaped signal to BOTH high and low (the toggle signature), OR
        # it names a spec token. A TB that never toggles a handshake line (and
        # never names the token) still GAPs.
        if it.kind == "handshake":
            token_hit = any(
                tok.strip()
                and re.search(r"\b" + re.escape(tok.strip().lower()) + r"\b",
                              tb_low)
                for tok in it.coverage_tokens)
            region = _tb_exercises_handshake_region(
                tb_clean, rtl_ports_lower, ambiguous_ports)
            it.covered = bool(region or token_hit)
            if region and token_hit:
                it.coverage_note = ("TB toggles a handshake signal (valid/ready "
                                    "backpressure) and names the spec token")
            elif region:
                it.coverage_note = ("TB toggles a handshake signal high+low "
                                    "(valid/ready backpressure exchange)")
            elif token_hit:
                it.coverage_note = ("TB names the handshake spec token")
            else:
                it.coverage_note = ("no TB toggle of a valid/ready handshake "
                                    f"signal and no reference to {it.coverage_tokens}")
            continue
        # ORGANIC R13C3 (cvdp_copilot_ir_receiver_0001): the byte_order item is a
        # STRUCTURAL-STIMULUS requirement, not a vocabulary one. A faithful
        # ordering TB drives a vector ONE INDEXED BIT AT A TIME and asserts the
        # packed output equals the source vector (`out === frame`), proving the
        # arrival order maps to the packed bit positions — and need never spell
        # the phrase "lsb first". Mark covered iff the TB structurally exercises
        # the ordering (indexed per-bit drive + an equality assertion in a loop),
        # OR it names a spec token. A TB that never drives an ordered per-bit
        # stimulus (and never names the token) still GAPs — §4.05 no-leak.
        if it.kind == "byte_order":
            token_hit = any(
                tok.strip()
                and re.search(r"\b" + re.escape(tok.strip().lower()) + r"\b",
                              tb_low)
                for tok in it.coverage_tokens)
            region = _tb_exercises_byte_order_region(tb_clean, rtl_ports_lower)
            it.covered = bool(region or token_hit)
            if region and token_hit:
                it.coverage_note = ("TB drives an indexed per-bit ordered stimulus "
                                    "and names the spec token")
            elif region:
                it.coverage_note = ("TB drives an indexed per-bit ordered stimulus "
                                    "with an ordering equality assertion")
            elif token_hit:
                it.coverage_note = ("TB names the byte/bit-order spec token")
            else:
                it.coverage_note = ("no TB indexed per-bit ordered stimulus and "
                                    f"no reference to {it.coverage_tokens}")
            continue
        # Normal item: covered if ANY of its coverage tokens appears in the TB.
        hit = []
        for tok in it.coverage_tokens:
            t = tok.strip()
            if not t:
                continue
            if re.fullmatch(r"0[xXbB][0-9A-Fa-f_]+|\d+|\d+'[bdh][0-9A-Fa-fxXzZ_]+", t):
                if _norm_value(t) in tb_values_norm:
                    hit.append(t)
            elif re.search(r"\b" + re.escape(t.lower()) + r"\b", tb_low):
                hit.append(t)
        it.covered = bool(hit)
        it.coverage_note = (f"TB references {hit}" if hit
                            else f"no TB reference to {it.coverage_tokens}")


def _norm_value(v: str) -> int:
    """Normalise a Verilog/hex/dec value literal to an int for comparison."""
    v = v.strip().replace("_", "")
    m = re.fullmatch(r"(\d+)'([bdh])([0-9A-Fa-fxXzZ]+)", v)
    if m:
        base = {"b": 2, "d": 10, "h": 16}[m.group(2).lower()]
        digits = re.sub(r"[xXzZ]", "0", m.group(3))
        try:
            return int(digits, base)
        except ValueError:
            return -1
    try:
        if v.lower().startswith("0x"):
            return int(v, 16)
        if v.lower().startswith("0b"):
            return int(v, 2)
        return int(v)
    except ValueError:
        return -1


# ---------------------------------------------------------------------------
# Failure attribution (extraction-gap / coverage-gap / spec-absent)
# ---------------------------------------------------------------------------
def attribute_failure(failure_text: str, items: List[ChecklistItem],
                      stations: dict) -> dict:
    """Attribute a verification FAILURE to one of the #697 branches, naming the
    LAST input-chain station that held the requirement so the fix routes right.

    - coverage-gap : the failing behavior matches a checklist item we DID
                     extract (at some chain station) but our TB left UNCOVERED.
    - extraction-gap: the failing behavior is present at some chain STATION but
                     is NOT in our checklist (we dropped it). The last holding
                     station + STATION_ROUTE name which downstream station
                     dropped it (ic-expert-agent / spec-to-rtl).
    - spec-absent  : the failing behavior is nowhere in the chain — genuine
                     FLOOR; must cite the stations searched as evidence.
    """
    f = failure_text.strip()
    f_low = f.lower()
    f_tokens = set(re.findall(r"[A-Za-z_]\w+|0[xX][0-9A-Fa-f]+|\d+", f_low))

    # 1) coverage-gap: overlaps an UNCOVERED checklist item (we extracted it)
    for it in items:
        if it.covered is False:
            it_tokens = set()
            for t in [it.requirement] + it.coverage_tokens:
                it_tokens |= set(re.findall(r"[A-Za-z_]\w+|0[xX][0-9A-Fa-f]+|\d+", t.lower()))
            it_tokens.discard("__outside_set__")
            if f_tokens & it_tokens:
                return {"attribution": "coverage-gap",
                        "matched_item": it.requirement,
                        "held_at_stations": it.stations,
                        "fix": "enhance our TB coverage to exercise this item"}
    # also coverage-gap if the failure literally mentions outside-set/default
    if re.search(r"\b(outside|default|otherwise|invalid|unlisted)\b", f_low):
        for it in items:
            if it.kind == "enum_boundary" and it.covered is False:
                return {"attribution": "coverage-gap",
                        "matched_item": it.requirement,
                        "held_at_stations": it.stations,
                        "fix": "enhance our TB coverage to exercise the boundary"}

    # 2) extraction-gap: present at a chain STATION but not in our checklist.
    #    Find the most-downstream station whose TEXT contains the failing
    #    tokens — that station HELD it; the next station downstream dropped it.
    held_at = []
    sig_tokens = [t for t in f_tokens if len(t) >= 3]
    for st in STATION_ORDER:
        text = stations.get(st)
        if text and any(tok in text.lower() for tok in sig_tokens):
            held_at.append(st)
    if held_at:
        last = _last_station(held_at)
        route_target, route_why = STATION_ROUTE[last]
        return {"attribution": "extraction-gap",
                "held_at_stations": held_at,
                "last_holding_station": last,
                "route_to": route_target,
                "evidence": (f"failing behavior present at {held_at} but no "
                             f"checklist item captured it; {route_why}"),
                "fix": f"route to {route_target}: {route_why}"}

    # 3) genuine spec-absence (FLOOR) — cite the stations searched + not found.
    searched = [s for s in STATION_ORDER if stations.get(s)]
    return {"attribution": "spec-absent",
            "stations_searched": searched,
            "evidence": (f"failing behavior NOT found at any input-chain station "
                         f"{searched} nor in the checklist — this is the ONLY "
                         f"case a FLOOR label is allowed, and it must cite this "
                         f"absence (white-box internal name / cross-problem "
                         f"convention / unstated value)."),
            "fix": "FLOOR-with-evidence: record the searched stations; do NOT "
                   "charge as our gap"}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def run(stations: dict, rtl_text: Optional[str], tb_text: Optional[str],
        failure_text: Optional[str], strict: bool) -> dict:
    """`stations` maps STATION_ORDER keys -> text (only the provided ones)."""
    # The verbatim user prompt is the highest-authority station.  Preserve an
    # explicit interface absence across the station merge: generated L-doc
    # boilerplate such as "reset behavior verification" must not turn a source
    # declaration of "no reset pin" into an RTL/TB requirement.
    user_prompt = stations.get("user_prompt") or ""
    reset_explicitly_absent = bool(
        re.search(r"\b(?:reset|rst|por)\b", user_prompt, re.IGNORECASE)
    ) and not _mention_present_unnegated(
        user_prompt, r"\breset\b|\brst\b|\bpor\b",
        polarity_check=_prose_is_denied,
    )
    items = [it for it in extract_chain(stations)
             if not _is_non_requirement_artifact(it)
             and not (reset_explicitly_absent and it.kind == "reset")]

    # --- Reset coverage tokens from the design's REAL reset port(s) ----------
    # The shipped reset item hard-codes ['reset','rst','por'] which never match
    # the dominant conventions (rst_in / rst_n / srst / clr). Augment the reset
    # item with the authored RTL's actual reset port identifier(s) so a TB that
    # faithfully drives the real reset port is counted as covering reset.
    rtl_reset_ports = _rtl_reset_ports(rtl_text, tb_text)
    if rtl_reset_ports:
        for it in items:
            if it.kind == "reset":
                for nm in rtl_reset_ports:
                    if nm not in it.coverage_tokens:
                        it.coverage_tokens.append(nm)

    # --- (#752 → #751 adversarial-review remediation) -----------------------
    # An EARLIER version of this fix DROPPED any spec-derived `port` checklist
    # item absent from the authored RTL port set, to suppress prose-fabricated
    # phantom ports. That cross-check was a §4.05 LEAK: it could not tell a
    # prose phantom apart from a REAL spec port the RTL WRONGLY OMITS (a defect
    # of exactly the class this gate exists to catch), so a TB for an RTL that
    # dropped a required port passed --strict. The phantom source is now fixed
    # AT EXTRACTION — `_specrtl_common._NL_PORT` no longer harvests prose bullets
    # and the prose-scan fallback is fenced on a real `module … endmodule`
    # (#751) — so there is nothing legitimate left for a downstream drop to do,
    # and the drop only created the leak. It is removed; a spec port absent from
    # the RTL now correctly stays a requirement (a missing real port still GAPs /
    # BLOCKs under --strict).
    enum_members_all: List[str] = []
    for it in items:
        if it.kind == "enum_set":
            enum_members_all += it.coverage_tokens

    attribute_coverage(
        items, tb_text, enum_members_all,
        _rtl_port_name_set(rtl_text, tb_text) if rtl_text else None,
        _ambiguous_port_names(rtl_text, tb_text) if rtl_text else None)

    # ── ORGANIC #770 — provenance / confidence tagging ──────────────────────
    # Tag each item STRUCTURAL vs PROSE_HEURISTIC and compute whether the RTL
    # corroborates a prose item. A coverage GAP on a PROSE_HEURISTIC item that
    # the RTL CONTRADICTS or does not structurally back is downgraded to
    # ADVISORY (block_eligible=False); STRUCTURAL gaps keep blocking. No-leak
    # biased: when no RTL is supplied (rtl_text None) every corroboration is
    # UNKNOWN, so NOTHING is downgraded — historical blocking power is preserved.
    rtl_ports_lower = _rtl_port_name_set(rtl_text, tb_text) if rtl_text else None
    rtl_has_reset = bool(_rtl_reset_ports(rtl_text, tb_text)) if rtl_text else None
    rtl_has_clock = _rtl_has_clocked_block(rtl_text) if rtl_text else None
    # ORGANIC #770 r2 — does the RTL structurally implement a valid/ready
    # handshake (a port whose name matches the handshake-signal grammar)? Used to
    # corroborate a prose 'handshake' requirement: a prose handshake mention on a
    # design with NO handshake-shaped port has no structural backing.
    rtl_has_handshake = (
        any(_is_handshake_signal(p) for p in rtl_ports_lower)
        if rtl_ports_lower is not None else None)
    # ORGANIC #770 Step-2.7 — a behavioral requirement STATED IN A MARKDOWN TABLE
    # is a STRUCTURAL source (high confidence), not a free-prose guess, so it must
    # keep its block even when the RTL appears to contradict it. Detect each
    # behavioral kind's trigger inside the table-cell text; if present, that kind
    # is structurally sourced and is NOT provenance-downgraded.
    _all_spec = "\n".join(v for v in stations.values() if v)
    _table_txt = _markdown_table_text(_all_spec)
    # ORGANIC #770 r2 — the LATENCY/TIMING promotion is scoped to OUTPUT-TIMING
    # table rows only; the shipped promotion fired on an `Internal Signals` helper
    # table whose Description cell merely says 'Registered version of the sel
    # signal' (axis_mux_0001), re-blocking a pure-combinational design. A genuine
    # `| Output latency | 1 clock cycle |` row still promotes (no-leak). The other
    # behavioral kinds (reset/overflow/handshake/signedness/byte_order) are not
    # the over-promotion class and keep the full-table source.
    _timing_table_txt = _output_timing_table_text(_all_spec)
    _structural_kinds = set()
    if _timing_table_txt and _LATENCY_RE.search(_timing_table_txt):
        _structural_kinds.add("latency")
    if _table_txt:
        tl = _table_txt.lower()
        if re.search(r"\breset\b|\brst\b|\bpor\b", tl):
            _structural_kinds.add("reset")
        if _OVERFLOW_RE.search(_table_txt):
            _structural_kinds.add("overflow")
        if _HANDSHAKE_RE.search(_table_txt):
            _structural_kinds.add("handshake")
        if _SIGNED_RE.search(_table_txt):
            _structural_kinds.add("signedness")
        if _BYTEORDER_RE.search(_table_txt):
            _structural_kinds.add("byte_order")
    for it in items:
        if it.kind in _PROSE_HEURISTIC_KINDS and it.kind not in _structural_kinds:
            it.provenance = _prov.PROSE_HEURISTIC
            corr = _prov.UNKNOWN
            if it.kind == "reset":
                # corroborated iff the RTL actually has a reset port; a prose
                # 'reset' mention with NO reset port AND no clock (pure comb) has
                # no structural backing.
                if rtl_has_reset is True:
                    corr = _prov.CORROBORATED
                elif rtl_text is not None and not rtl_has_reset and not rtl_has_clock:
                    corr = _prov.NO_CORROBORATION
            elif it.kind == "latency":
                # corroborated iff the RTL has a clocked (registered) block; a
                # prose latency on a provably pure-combinational RTL is contradicted.
                corr = _prov.corroborate_structural_feature(rtl_has_clock)
            elif it.kind == "handshake":
                # ORGANIC #770 r2 — corroborated iff the RTL declares a
                # handshake-shaped port (…valid/…ready/…ack/…req/…stall). A prose
                # 'handshake'/'backpressure'/'valid/ready' mention on a design with
                # NO handshake-shaped port has no structural backing → advisory.
                # When the RTL DOES have handshake ports, an uncovered handshake is
                # a genuine coverage gap and STILL blocks (CORROBORATED). No-leak:
                # None (no RTL) keeps the block. (axis_joiner_0001)
                if rtl_has_handshake is True:
                    corr = _prov.CORROBORATED
                elif rtl_has_handshake is False:
                    corr = _prov.NO_CORROBORATION
            elif it.kind == "enum_set" and it.is_concat_literal:
                # ORGANIC #770 r2 — a single-signal packed-vector CONCATENATION
                # literal (`sig = {a,b,c}`) is NOT an enumerated value set; its
                # sub-fields are positional bit-slices of ONE value, not members to
                # each be 'handled'. The structural shape CONTRADICTS the
                # enumerated-set reading → advisory. A genuine enumerated value set
                # (is_concat_literal=False) keeps STRUCTURAL → blocks.
                # (configurable_digital_low_pass_filter_0001)
                corr = _prov.CONTRADICTED
            elif it.kind == "worked_example":
                # ORGANIC #780 (#770 r7, R8C1) — a worked_example gap blocks only
                # when the matched `LHS -> RHS` is a REAL in->out DATA pair. When
                # the match is a STRUCTURAL ARTIFACT of the surrounding Verilog /
                # notation (the LHS digit is the numeric suffix of an identifier
                # like GRANT_2; the RHS digit is a sized-literal bit-WIDTH like
                # 3'b010; or a binary-nibble=decimal gloss like "0101 = 5" that is
                # one per-digit step of ONE example) it has NO structural backing
                # as a data pair → NO_CORROBORATION → advisory. A genuine in->out
                # example (we_structural_artifact False) keeps its historical
                # blocking power (UNKNOWN → block), so a worked example the TB
                # never stimulates STILL hard-blocks. No-leak biased: only the
                # provably-non-data shapes downgrade.
                # (cvdp_copilot_bus_arbiter_0001: phantom 2->3 from "GRANT_2 =
                #  3'b010"; cvdp_copilot_binary_to_BCD_0010: the single example
                #  0010_0101_0111->257 split into 0010=2 / 0101=5 / 0111=7.)
                if it.we_structural_artifact:
                    corr = _prov.NO_CORROBORATION
                # ORGANIC #780 r2 (field reopen) — the extraction-time artifact
                # check sees only the SPEC, so a spec that lists the per-digit
                # steps SEPARATELY (table / "MSD 0010, Middle 0101, LSD 0111")
                # misses that they decompose ONE example whose grouped parent
                # input (`bcd_in = 0010_0101_0111`) the TESTBENCH drives. Re-check
                # against spec+TB: a binary-nibble gloss that is a slice of a
                # grouped parent the TB stimulates is an intermediate step →
                # advisory. A genuine standalone example the TB never drives a
                # containing parent for still BLOCKS (§4.05).
                elif _worked_example_is_covered_parent_gloss(
                        it.coverage_tokens,
                        _all_spec + "\n" + (tb_text or "")):
                    corr = _prov.NO_CORROBORATION
            elif it.kind == "byte_order":
                # ORGANIC R13C3 (cvdp_copilot_ir_receiver_0001) — a PROSE/example
                # byte_order requirement (not in a markdown table -> not in
                # _structural_kinds) corroborated against the RTL's structural
                # bit-ordering signature. The shipped code had NO elif here, so
                # corr stayed UNKNOWN and is_block_eligible(PROSE_HEURISTIC,
                # UNKNOWN) returned True — a prose-only "LSB First" hard-BLOCKed a
                # correct LSB-first design that the TB faithfully ordered, while
                # the only way to "pass" was to inject the functionless literal
                # 'lsb first' into the TB (gaming a token, not verifying order).
                #   - RTL has a shift-insert order matching the spec direction
                #     -> CORROBORATED: the requirement is real; an uncovered order
                #        STILL blocks, but the structural ordering stimulus above
                #        now counts as coverage (no literal phrase needed).
                #   - RTL implements the OPPOSITE order -> CONTRADICTED -> advisory
                #     (the prose finding is refuted by the structure).
                #   - RTL has NO orderable shift-insert structure (the design does
                #     not serially pack a vector) -> NO_CORROBORATION -> advisory
                #     (a prose byte-order mention with no structural backing).
                #   - no RTL supplied -> UNKNOWN -> keep block (no-leak biased).
                # No-leak: a byte_order stated in a markdown TABLE is already in
                # _structural_kinds and never reaches this branch, so it keeps its
                # hard block. chip-AGNOSTIC: pure shift-insert concat grammar.
                rtl_order = _rtl_byte_order_signature(rtl_text)
                spec_order = _spec_byte_order_intent(it.evidence)
                if rtl_text is None:
                    corr = _prov.UNKNOWN
                elif rtl_order is None:
                    corr = _prov.NO_CORROBORATION
                elif spec_order is None:
                    # direction-less spec phrase but the RTL DOES pack serially:
                    # the ordering requirement is structurally backed -> block.
                    corr = _prov.CORROBORATED
                elif rtl_order == spec_order:
                    corr = _prov.CORROBORATED
                else:
                    corr = _prov.CONTRADICTED
            elif it.kind == "signedness":
                # ORGANIC R13C3 + #770 (R13C1) — signedness shares the byte_order
                # gap: it is in _PROSE_HEURISTIC_KINDS with no corroboration branch,
                # so a prose-only signed/unsigned note hard-blocked. Corroborate
                # against whether the RTL STRUCTURALLY declares `signed` via the
                # shared tri-state `_rtl_declares_signed()` detector: no structural
                # signed declaration -> NO_CORROBORATION -> advisory (a prose
                # "unsigned integers" mention is backed by the signed-absence, the
                # Verilog default; e.g. montgomery_0001); present -> CORROBORATED ->
                # keep block (e.g. 16qam_mapper); no RTL -> UNKNOWN -> keep block.
                # No-leak: a markdown-table signedness stays structural.
                _sg = _rtl_declares_signed(rtl_text)
                if _sg is None:
                    corr = _prov.UNKNOWN
                elif _sg:
                    corr = _prov.CORROBORATED
                else:
                    corr = _prov.NO_CORROBORATION
            it.block_eligible = _prov.is_block_eligible(it.provenance, corr)
            if not it.block_eligible:
                it.advisory_note = _prov.advisory_reason(it.provenance, corr)
        if it.kind in _AMS_ONLY_KINDS and it.covered is False:
            it.provenance = _prov.PROSE_HEURISTIC
            it.block_eligible = False
            it.advisory_note = (
                "physical/PVT requirement remains for AMS or corner sign-off; "
                "a digital RTL testbench cannot exercise this quantity")
        # NOTE (#770 §4.05): the `port` kind is DELIBERATELY NOT
        # provenance-downgraded here. A spec port absent from the RTL port set
        # cannot be told apart from a phantom by absence alone — that exact
        # "drop if absent from RTL" cross-check WAS the #752 §4.05 leak (it waved
        # through an RTL that wrongly omitted a real required port; see the
        # comment block above). Phantom prose-words like `'and'` (scraped from
        # "Input and output signals ...") are fixed AT EXTRACTION in
        # `_specrtl_common._nl_port_is_prose`, never by a downstream absence test.
        # So `port` stays STRUCTURAL → a genuine missing port still BLOCKs.

    gaps = [it for it in items if it.covered is False]
    # ORGANIC #770 — only a BLOCK-eligible gap hard-blocks under --strict.
    blocking_gaps = [it for it in gaps if it.block_eligible]
    report = {
        "gate": "spec_coverage_check",
        "doctrine": "spec-first coverage attribution (#697): 'spec' is the whole "
                    "input chain (prompt -> fact-graph -> L-docs); a verification "
                    "failure is a coverage-gap or an extraction-gap (routed to the "
                    "last holding station) until the chain is PROVEN not to contain "
                    "the requirement (spec-absent FLOOR, with cited evidence).",
        "input_chain_stations": [s for s in STATION_ORDER if stations.get(s)],
        "checklist_items": len(items),
        "covered": sum(1 for it in items if it.covered),
        "coverage_gaps": len(gaps),
        "items": [asdict(it) for it in items],
    }
    if failure_text:
        report["failure_attribution"] = attribute_failure(
            failure_text, items, stations)

    # block decision: only BLOCK-eligible TESTBENCH-COVERAGE GAPs gate (#770),
    # and only in --strict. An advisory (prose-heuristic, RTL-contradicted /
    # uncorroborated) gap is reported but never a hard veto.
    report["pass"] = (len(gaps) == 0)
    report["advisory_gaps"] = len(gaps) - len(blocking_gaps)
    report["blocking_gaps"] = len(blocking_gaps)
    report["strict"] = strict
    report["blocked"] = bool(strict and blocking_gaps)
    return report


def _print_human(report: dict) -> None:
    chain = report.get("input_chain_stations", [])
    print(f"spec_coverage_check: {report['covered']}/{report['checklist_items']} "
          f"chain-derived requirement(s) covered by the testbench "
          f"(input chain: {' -> '.join(chain) or 'none'})")
    for it in report["items"]:
        loc = f" [{it.get('last_station', '')}]" if it.get("last_station") else ""
        if it["covered"]:
            print(f"  [OK]   {it['kind']}{loc}: {it['requirement']}")
        elif not it.get("block_eligible", True):
            # ORGANIC #770 — a prose-heuristic gap the RTL contradicts / does not
            # back is reported but does NOT hard-block.
            print(f"  [ADVISORY] {it['kind']}{loc}: {it['requirement']} "
                  f"(UNCOVERED, advisory — {it.get('advisory_note', '')})")
        else:
            print(f"  [GAP]  {it['kind']}{loc}: {it['requirement']} (UNCOVERED) "
                  f"-- {it['coverage_note']}")
    if report.get("coverage_gaps"):
        print(f"\nTESTBENCH-COVERAGE GAPs: {report['coverage_gaps']} chain "
              f"requirement(s) have no covering assertion in the authored TB.")
        print("  Doctrine (#697): this is OUR gap (enhance TB coverage), NOT a "
              "FLOOR — a hidden scorer derived from the same spec WILL test it.")
    if "failure_attribution" in report:
        fa = report["failure_attribution"]
        print(f"\nFAILURE ATTRIBUTION: {fa['attribution']}")
        for k in ("matched_item", "held_at_stations", "last_holding_station",
                  "route_to", "stations_searched", "evidence"):
            if k in fa:
                print(f"  {k}: {fa[k]}")
        print(f"  fix: {fa['fix']}")
    if report["blocked"]:
        print("\n[STRICT/sole-emit] BLOCK: self-testbench must cover every "
              "spec-derived checklist item before the artifact is emitted.")
    elif report.get("coverage_gaps"):
        print("\n[advisory] coverage gaps reported (WARN) — non-strict, not "
              "hard-blocked. Re-run with --strict for sole-emit gating.")
    else:
        print("\nspec-coverage ok — testbench covers every spec-derived "
              "checklist item.")


def _read(path: str, what: str) -> str:
    """Read a station file, or concatenate the L-doc files in a directory."""
    p = Path(path)
    if p.is_dir():                       # an L-docs DIRECTORY (L1..L23 files)
        parts = []
        for f in sorted(p.glob("L*")):
            if f.is_file():
                parts.append(f.read_text(errors="replace"))
        if not parts:                    # no L-files: read everything readable
            for f in sorted(p.glob("*")):
                if f.is_file():
                    parts.append(f.read_text(errors="replace"))
        return "\n".join(parts)
    return p.read_text(errors="replace")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Spec-first coverage attribution gate across the whole "
                    "input chain (ORGANIC #697).")
    # USER station (prompt). --spec is the back-compat alias.
    ap.add_argument("--prompt", default=None,
                    help="USER input prompt (input-chain station 1).")
    ap.add_argument("--spec", default=None,
                    help="Alias for --prompt (back-compat).")
    ap.add_argument("--fact-graph", dest="fact_graph", default=None,
                    help="IC Expert Agent structured input / fact graph (station 2).")
    ap.add_argument("--ldocs", default=None,
                    help="IC-expert L1-L23 Design Documents (file or directory; "
                         "input-chain station 3).")
    ap.add_argument("--rtl", default=None, help="Authored RTL (optional).")
    ap.add_argument("--tb", default=None, help="Authored testbench (optional).")
    ap.add_argument("--failure", default=None,
                    help="A verification-failure description to attribute "
                         "(coverage-gap / extraction-gap[+station] / spec-absent).")
    ap.add_argument("--strict", action="store_true",
                    help="sole-emit BLOCK: exit non-zero on any coverage gap.")
    ap.add_argument("--json", default=None, help="Write the JSON report here.")
    args = ap.parse_args(argv)

    prompt_path = args.prompt or args.spec
    if not (prompt_path or args.fact_graph or args.ldocs):
        print("[ERROR] supply at least one input-chain station: "
              "--prompt/--spec, --fact-graph, or --ldocs", file=sys.stderr)
        return 2

    stations: dict = {}
    try:
        if prompt_path:
            stations["user_prompt"] = _read(prompt_path, "--prompt/--spec")
        if args.fact_graph:
            stations["fact_graph"] = _read(args.fact_graph, "--fact-graph")
        if args.ldocs:
            stations["l_docs"] = _read(args.ldocs, "--ldocs")
        rtl_text = _read(args.rtl, "--rtl") if args.rtl else None
        tb_text = _read(args.tb, "--tb") if args.tb else None
    except OSError as e:
        print(f"[ERROR] cannot read input: {e}", file=sys.stderr)
        return 2

    report = run(stations, rtl_text, tb_text, args.failure, args.strict)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))

    _print_human(report)
    return 1 if report["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
