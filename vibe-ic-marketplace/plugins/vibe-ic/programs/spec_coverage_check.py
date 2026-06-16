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
      -> structured input data / fact graph (PM AGENT)
        -> input Design Documents / L1-L23 (IC EXPERT AGENT)
          -> spec-to-rtl authoring (RTL)

TWO-BRANCH attribution, extended across the whole chain — the program names
WHICH station last held the requirement so the fix routes to the right place:

  (1) SPEC-EXTRACTION GAP — the requirement EXISTS somewhere in the chain but
      was not carried end-to-end. Report the LAST station that still held it:
        * USER prompt had it but the fact graph didn't  -> route: enhance
          PM-AGENT elicitation (pm-agent);
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
          (PM agent structured input), `--ldocs` (IC-expert L1-L23). `--spec`
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
  skills/open-benchmark-methodology + agents/pm-agent, agents/ic-expert-agent.
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
        [--fact-graph FG]                        # PM-agent structured input
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

# ORGANIC #770 — checklist kinds whose evidence is a FREE-PROSE keyword/regex
# (low confidence) vs a real structural source. STRUCTURAL kinds (a real markdown
# table row, a given-code port header) keep their historical blocking power; a
# PROSE_HEURISTIC kind's coverage gap blocks only when the RTL corroborates it.
_PROSE_HEURISTIC_KINDS = frozenset({
    "reset", "latency", "enum_boundary", "worked_example",
    "signedness", "byte_order", "overflow", "handshake", "enum_set",
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
    "user_prompt": ("pm-agent",
                    "USER prompt stated it but the fact graph dropped it — "
                    "enhance PM-agent elicitation"),
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


def _is_value_enum(member_blob: str, members: List[str], context: str) -> bool:
    """Decide whether a brace-list `{...}` is a genuine enumerated VALUE set
    (member-by-member TB coverage is testable) versus a Verilog CONCATENATION /
    code expression that merely shares the `{...}` shape.

    Accept when ANY member is a value-shaped literal (hex/dec/bin) — a real
    value set. An identifier-ONLY brace-list is accepted ONLY in an explicit
    enumerated-set context window (see _SET_CONTEXT_RE); otherwise it is treated
    as a concatenation/expression and NOT charged as an enum requirement (the
    decoder_0011 {E7..E0} output-assembly false positive)."""
    if any(_VALUE_MEMBER_RE.fullmatch(m) for m in members):
        return True
    return bool(_SET_CONTEXT_RE.search(context))


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


def _rtl_reset_ports(rtl_text: Optional[str]) -> List[str]:
    """Reset-shaped port names parsed from the authored RTL (best-effort).

    Returns the concrete reset port identifier(s) so the reset checklist item's
    coverage tokens are the design's REAL reset port(s) — exact, over-fit-free,
    no-leak (a TB must drive the actual reset port to be counted)."""
    if not rtl_text:
        return []
    try:
        _, ports = _SRC.parse_rtl_ports(rtl_text, None)
    except Exception:
        return []
    seen, out = set(), []
    for p in ports:
        nm = p.name
        if (nm.lower() not in _RTL_PORT_NOISE
                and _is_reset_port_name(nm) and nm not in seen):
            seen.add(nm)
            out.append(nm)
    return out


def _rtl_port_name_set(rtl_text: Optional[str]) -> set:
    """Lower-cased set of the authored RTL's port identifiers (best-effort).

    Returns an EMPTY set when no usable port could be parsed, so the caller
    skips the phantom-port cross-check rather than risk dropping real ports on
    a parser miss. chip-AGNOSTIC: structural Verilog port parse only."""
    if not rtl_text:
        return set()
    try:
        _, ports = _SRC.parse_rtl_ports(rtl_text, None)
    except Exception:
        return set()
    return {p.name.lower() for p in ports
            if p.name and p.name.lower() not in _RTL_PORT_NOISE}


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


def _mention_present_unnegated(text: str, keyword_re: str) -> bool:
    """True iff the keyword appears in at least one CLAUSE where it is NOT
    governed by a negation token. If EVERY clause mentioning the keyword negates
    it (e.g. 'with no clock or reset inputs', 'a reset is not required'), the
    feature is genuinely absent and no requirement is derived. A real reset
    clause comma-joined to an unrelated negated clause still derives."""
    low = text.lower()
    kw = re.compile(keyword_re, re.I)
    saw_mention = False
    for clause in _clauses(low):
        if kw.search(clause):
            saw_mention = True
            if not _NEG_TOKENS_RE.search(clause):
                return True   # an affirmative clause — feature is present
    # mentions existed but ALL clauses negated → absent; no mention → absent.
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
        if not _is_value_enum(m.group(1), members, _ctx):
            continue
        set_repr = "{" + ", ".join(members) + "}"
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
        items.append(ChecklistItem(
            kind="worked_example",
            requirement=f"worked example: {lhs} -> {rhs}",
            evidence=m.group(0),
            coverage_tokens=[lhs, rhs]))

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
            else:
                it.stations = [st]
                merged[k] = it
    items = list(merged.values())
    for it in items:
        it.last_station = _last_station(it.stations)
    return items


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


# ---------------------------------------------------------------------------
# Coverage attribution against the authored TESTBENCH
# ---------------------------------------------------------------------------
def attribute_coverage(items: List[ChecklistItem], tb_text: Optional[str],
                       enum_members_all: List[str]) -> None:
    """Set .covered / .coverage_note for each checklist item based on whether
    the authored TB exercises it. No TB => everything UNCOVERED."""
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
            it.covered = bool(region)
            if region and token_hit:
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
                     dropped it (pm-agent / ic-expert-agent / spec-to-rtl).
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
    items = extract_chain(stations)

    # --- Reset coverage tokens from the design's REAL reset port(s) ----------
    # The shipped reset item hard-codes ['reset','rst','por'] which never match
    # the dominant conventions (rst_in / rst_n / srst / clr). Augment the reset
    # item with the authored RTL's actual reset port identifier(s) so a TB that
    # faithfully drives the real reset port is counted as covering reset.
    rtl_reset_ports = _rtl_reset_ports(rtl_text)
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

    attribute_coverage(items, tb_text, enum_members_all)

    # ── ORGANIC #770 — provenance / confidence tagging ──────────────────────
    # Tag each item STRUCTURAL vs PROSE_HEURISTIC and compute whether the RTL
    # corroborates a prose item. A coverage GAP on a PROSE_HEURISTIC item that
    # the RTL CONTRADICTS or does not structurally back is downgraded to
    # ADVISORY (block_eligible=False); STRUCTURAL gaps keep blocking. No-leak
    # biased: when no RTL is supplied (rtl_text None) every corroboration is
    # UNKNOWN, so NOTHING is downgraded — historical blocking power is preserved.
    rtl_ports_lower = _rtl_port_name_set(rtl_text) if rtl_text else None
    rtl_has_reset = bool(_rtl_reset_ports(rtl_text)) if rtl_text else None
    rtl_has_clock = _rtl_has_clocked_block(rtl_text) if rtl_text else None
    # ORGANIC #770 Step-2.7 — a behavioral requirement STATED IN A MARKDOWN TABLE
    # is a STRUCTURAL source (high confidence), not a free-prose guess, so it must
    # keep its block even when the RTL appears to contradict it. Detect each
    # behavioral kind's trigger inside the table-cell text; if present, that kind
    # is structurally sourced and is NOT provenance-downgraded.
    _all_spec = "\n".join(v for v in stations.values() if v)
    _table_txt = _markdown_table_text(_all_spec)
    _structural_kinds = set()
    if _table_txt:
        tl = _table_txt.lower()
        if _LATENCY_RE.search(_table_txt):
            _structural_kinds.add("latency")
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
            it.block_eligible = _prov.is_block_eligible(it.provenance, corr)
            if not it.block_eligible:
                it.advisory_note = _prov.advisory_reason(it.provenance, corr)
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
                    help="PM-agent structured input / fact graph (station 2).")
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
