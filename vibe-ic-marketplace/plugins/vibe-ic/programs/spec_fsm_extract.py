#!/usr/bin/env python3
"""spec_fsm_extract.py — PROGRAM-FIRST structural extractor for stated FSMs.

A large family of CVDP `code_generation` prompts (and any L-doc / datasheet)
state a Finite State Machine EXPLICITLY: a set of NAMED states plus the
TRANSITIONS between them. The hidden scoring testbench exercises exactly those
state/transition behaviors, so a verification FAILURE on an FSM design is —
per the spec-coverage doctrine — almost always one of OUR OWN extraction gaps
(a stated transition we never read out / never covered), not an unfixable
floor.

This program does the DETERMINISTIC, chip-AGNOSTIC, PROGRAM-FIRST half of that
job: given a prompt, it extracts the STRUCTURAL FSM skeleton —

  * one `fsm_state`      ChecklistItem per stated, NAMED state, and
  * one `fsm_transition` ChecklistItem per stated (state, condition -> next), and
  * one `fsm_state_output` ChecklistItem per explicit one-cycle output owned by
    a named state.

— anchored to a real state-name token and a real transition statement, so the
downstream coverage attribution (`spec_coverage_check.py` / the TB self-check)
can verify every stated edge is exercised.

WHAT COUNTS AS A "STATED FSM" (the §4.05 no-leak boundary)
  The extractor keys ONLY on STRUCTURE — a state-name token (UPPER_CASE /
  `S0..Sn` / `STATE_x` / a markdown state-section header / an enum or localparam
  encoding) and an explicit transition statement (prose "in IDLE, on start, go
  to LOAD" / "transitions to RUN" / "moves to DONE state"; a `| state | next |`
  table row; an enum-listed state with a stated next). It NEVER fabricates a
  requirement out of free prose: a vague "implement a state machine" with NO
  enumerated states and NO explicit transition returns `[]`. The gate is hard:

      >= 2 distinct named states  AND  >= 1 explicit transition,

  otherwise `extract()` returns `[]` (no fabrication). chip-AGNOSTIC: every
  matcher is generic FSM grammar (state-name shape, transition verb, enum /
  localparam / markdown-section structure) — NO chip / vendor / SKU / problem-id
  literal (enforced by `programs/source_chip_agnostic_check.py .`).

CONTRACT
  Each emitted dict is shaped to seed a `spec_coverage_check.ChecklistItem`:
    {
      "kind":        "fsm_state" | "fsm_transition" | "fsm_state_output",
      "requirement": human-readable testable requirement,
      "evidence":    the EXACT state / transition line it came from,
      "coverage_tokens": [tokens a TB must touch to cover it],
      # transition / state-output structured fields (also harmless on states):
      "state":       <source state name>      (transition only),
      "next_state":  <destination state name> (transition only),
      "condition":   <transition condition or "">,
      "signal":      <output signal>          (state-output only),
      "asserted_value": 1,                    (state-output only),
      "duration_cycles": 1,                   (state-output only),
    }

CLI
    python3 spec_fsm_extract.py <prompt.txt> [--json]
    cat prompt.txt | python3 spec_fsm_extract.py -
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# State-name grammar (chip-AGNOSTIC, pure structural shape)
# ---------------------------------------------------------------------------
# A state-name TOKEN: an UPPER_CASE / S<n> / STATE_<n> identifier of >=2 chars.
# Allows the dominant FSM naming conventions: IDLE, ROLLING, INIT_WRITE,
# RETURN_MONEY, S0, S12, STATE_3, FAIL_FINAL. Requires at least one letter and
# either an all-caps shape (>=2 alnum, may carry digits/underscores) or the
# canonical S<digits> / STATE_<n> short forms. A single letter, a pure number,
# or a lower-case word is NOT a state-name token (so prose words never qualify).
_STATE_TOKEN_RE = re.compile(
    r"\b("
    r"S\d+"                              # S0, S12
    r"|STATE_?\d+"                       # STATE3, STATE_3
    r"|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"   # multi-part ALL_CAPS: INIT_WRITE
    r"|[A-Z]{2,}\d*"                     # single-part ALL_CAPS: IDLE, RUN2
    r")\b")

# Words in UPPER_CASE shape that are NOT FSM state names — generic spec / protocol
# vocabulary that would otherwise masquerade as states. chip-AGNOSTIC (no design
# literal): these are common English / Verilog / acronym tokens, kept as a small
# deny-set so an enumerated state list is not polluted, but a state with one of
# these names is still admitted if it is STRUCTURALLY a state (enum / localparam /
# explicit `<NAME> state` / a transition target).
_NON_STATE_WORDS: Set[str] = {
    "FSM", "RTL", "LSB", "MSB", "CRC", "ID", "IDS", "OK", "NA", "TODO", "FIXME",
    "AND", "OR", "NOT", "XOR", "NAND", "NOR", "DUT", "TB", "IO", "PV", "DC",
    "AC", "II", "III", "IV", "I", "A", "B", "C", "N", "X", "Y", "Z",
    "HIGH", "LOW", "ON", "OFF", "YES", "NO", "MSW", "LSW", "GND", "VDD", "VSS",
}


def _is_state_token(tok: str) -> bool:
    """PROSE-grade state token: ALL_CAPS / S<n> / STATE_<n> shape, not a deny-word.
    Used when the only evidence is free prose ("between IDLE and ROLLING states")
    — the strict all-caps shape keeps ordinary prose words from minting states."""
    if not tok or tok.upper() in _NON_STATE_WORDS:
        return False
    return bool(_STATE_TOKEN_RE.fullmatch(tok))


# A relaxed identifier shape for a STRUCTURALLY-anchored state name (an enum
# member, a `**Name** (enc)` section, a `| state |` table cell, an encoding list).
# Structure already proves it is a state, so Title-case / mixed-case names are
# admitted (Idle / Transmit / Clock_Toggle) — only identifier shape + the deny-set
# are enforced. chip-AGNOSTIC.
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")


def _is_structural_state_token(tok: str) -> bool:
    if not tok or tok.upper() in _NON_STATE_WORDS:
        return False
    if not _IDENT_RE.fullmatch(tok):
        return False
    # must carry at least one letter and be >=2 chars (a single letter / a pure
    # underscore is not a state name)
    return len(tok) >= 2 and any(c.isalpha() for c in tok)


# ---------------------------------------------------------------------------
# Comment stripping (so a `// IDLE` Verilog comment never seeds a state)
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
# State collection — multiple structural sources
# ---------------------------------------------------------------------------
# (1) A SystemVerilog `typedef enum ... { S1, S2, ... }` block. The brace body is
#     a comma list of state-name identifiers (optionally `= encoding`).
_ENUM_BLOCK_RE = re.compile(
    r"\benum\b[^{}]*\{([^{}]+)\}", re.IGNORECASE)
# (2) `localparam`/`parameter` state encodings, incl. COMMA-CHAINED declarations
#     `localparam IDLE = 3'b000, GRANT_1 = 3'b001, CLEAR = 3'b011;`. The block
#     matcher grabs the whole declaration; _localparam_assignments() then splits it
#     into individual NAME = VALUE pairs (each `,`-separated assignment).
_LOCALPARAM_BLOCK_RE = re.compile(
    r"\b(?:localparam|parameter)\b\s*(?:logic\s*)?(?:\[[^\]]*\]\s*)?"
    r"([^;]+?);",
    re.IGNORECASE)
_LOCALPARAM_ASSIGN_RE = re.compile(
    r"([A-Za-z_]\w*)\s*=\s*([^,]+)")


def _localparam_assignments(text: str):
    """Yield (name, value) for every localparam/parameter assignment, including
    comma-chained declarations. chip-AGNOSTIC."""
    for blk in _LOCALPARAM_BLOCK_RE.finditer(text):
        body = blk.group(1)
        for a in _LOCALPARAM_ASSIGN_RE.finditer(body):
            yield a.group(1).strip(), a.group(2).strip()
# Markdown state-section / encoding patterns, split into STRONG (self-corroborating
# — the markup itself proves "this names a state") and WEAK (needs corroboration —
# the same markup is used for document sections / port lists, so admit only when a
# transition or a `<NAME> state` prose mention confirms it).
#
# STRONG — the state code / the literal word "state" is in the anchor itself:
_MD_STRONG_PATTERNS = [
    # numbered section header carrying the word "State": "1. **IDLE State:**",
    # "2. **ITEM_SELECTION State:**", "**RETURN_MONEY State:**" (the word "state"
    # inside the bold distinguishes it from a bare `**Inputs**` section heading).
    re.compile(r"^\s*(?:#{1,6}\s*)?(?:\d+[.)]\s*)?\*\*\s*([A-Za-z_]\w*)\s*"
               r"state\s*:?\s*\*\*", re.IGNORECASE | re.MULTILINE),
    # bold name immediately followed by a STATE ENCODING in parens/backticks:
    # "**Idle** (`00`)", "**Transmit** (`01`)" (the encoding proves it is a state).
    re.compile(r"\*\*\s*([A-Za-z_]\w*)\s*\*\*\s*\(\s*`?[01xXzZ]{2,8}`?\s*\)",
               re.IGNORECASE),
    # bold "NAME (n):" encoded header — "**IDLE (0):**", "**EXTRACTING (1):**".
    re.compile(r"\*\*\s*([A-Za-z_]\w*)\s*\(\s*\d+\s*\)\s*:?\s*\*\*",
               re.IGNORECASE),
    # markdown heading whose text IS a state name + the word "state":
    # "## IDLE State", "### ROLLING state".
    re.compile(r"^\s*#{1,6}\s+([A-Za-z_]\w*)\s+state\b",
               re.IGNORECASE | re.MULTILINE),
]
# WEAK — same markup is also used for non-state document structure, so a candidate
# here is admitted only if CORROBORATED (transition target/source or `<NAME> state`
# prose). This is the §4.05 no-leak guard against `**Inputs**` / `` - `clk`: `` /
# `**Interface**` masquerading as states.
_MD_WEAK_PATTERNS = [
    # bare numbered/heading bold name WITHOUT "state"/encoding: "1. **IDLE**",
    # "### **READY**". Also matches `**Inputs**` — hence WEAK / corroboration-gated.
    re.compile(r"^\s*(?:#{1,6}\s*)?(?:\d+[.)]\s*)?\*\*\s*([A-Za-z_]\w*)\s*\*\*",
               re.MULTILINE),
    # backtick-quoted name in a defining bullet: "- `INIT`: SDRAM init." Also
    # matches `` - `clk`: `` port bullets — hence WEAK / corroboration-gated.
    re.compile(r"^\s*[-*]\s*`([A-Za-z_]\w*)`\s*:", re.MULTILINE),
]
# Markdown section headers that DEFINE a transition-source region — only the
# MULTI-LINE per-state section forms (strong headers + the bare-bold numbered/
# heading form). The backtick-BULLET weak pattern (_MD_WEAK_PATTERNS[1]) is a
# ONE-LINER state definition, NOT a region governing the prose that follows, so
# it is EXCLUDED — otherwise a flat transition paragraph below a `` - `INIT`: ``
# bullet list would inherit the last bullet's state as a spurious source.
_MD_SECTION_HEADER_PATTERNS = _MD_STRONG_PATTERNS + [_MD_WEAK_PATTERNS[0]]
# (4) Inline encoding enumeration: "IDLE(00), PROCESS(01), READY(10)" or
#     "00 = Idle", "`01` = Transmit", "`10` = Clock Toggle". Both `NAME(enc)` and
#     `enc = NAME`. The name-first form requires a >=2-bit encoding so a prose
#     gloss like "asserted (`1`)" / "deasserted (`0`)" is NOT read as a state.
#     The val-first form captures the FULL name phrase (multi-word states like
#     "Clock Toggle") up to the line end / next comma.
_ENC_NAME_FIRST_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s*\(\s*`?[01xXzZ]{2,8}`?\s*\)")
_ENC_VAL_FIRST_RE = re.compile(
    r"`?([01xXzZ]{1,8})`?\s*=\s*([A-Za-z_][\w ]*?)(?=\s*[\n,;)]|\s*$)")
# (5) An explicit "<NAME> state" / "state <NAME>" prose mention — a weaker source
#     used ONLY to ADMIT a token already structurally implied (it never alone
#     creates a state; see _collect_states).
# Backtick-aware: a datasheet routinely backtick-quotes the state name
# ("In the `IDLE` state", "state `LOAD`"), so the optional backticks around the
# name let `IDLE` state / state `LOAD` register as a prose state source.
_NAME_STATE_PROSE_RE = re.compile(
    r"`?([A-Z][A-Z0-9_]+)`?\s+state\b|\bstate\s+`?([A-Z][A-Z0-9_]+)`?\b")
# (6) An FSM-STATE-LIST cue LINE that explicitly announces an enumerated state
#     list and ENDS WITH A COLON, e.g. "Implements an FSM with states for:",
#     "The FSM has the following states:", "with states:". The CONTIGUOUS
#     backtick-bullet block that immediately follows is a STRONG state source
#     (self-corroborating: the cue line explicitly says "these are the states").
#     The cue must name an FSM / state machine AND the word "state(s)" AND close
#     with ':' so an arbitrary "states:" mid-paragraph does not qualify. NO inline
#     comma-list arm — the inline `IDLE(00), PROCESS(01)` form is already covered
#     by the encoding extractor. chip-AGNOSTIC.
_FSM_LIST_CUE_LINE_RE = re.compile(
    r"^[^\n]*?"
    r"(?:\bFSM\b|\bstate\s+machine\b|\bfinite[\s-]+state\b)"
    r"[^\n]*?\bstates?\b[^\n:]*:\**\s*$",   # allow trailing markdown `**` / spaces
    re.IGNORECASE | re.MULTILINE)
# a backtick-quoted bullet state member on a list line (the cue-list shape).
_BACKTICK_BULLET_RE = re.compile(
    r"^\s*[-*]\s*`([A-Za-z_]\w*)`\s*[:\-]")


def _fsm_list_member_names(prose: str) -> List[Tuple[str, str]]:
    """State names enumerated in a CONTIGUOUS backtick-bullet list introduced by an
    FSM-state-list cue line ("Implements an FSM with states for:" + `- `INIT`: …`).
    The cue makes these STRONG (self-corroborating) sources. Returns (name,
    evidence). chip-AGNOSTIC: keys on the cue grammar + contiguous list structure,
    no design literal."""
    out: List[Tuple[str, str]] = []
    lines = prose.splitlines()
    for cue in _FSM_LIST_CUE_LINE_RE.finditer(prose):
        idx = prose[:cue.end()].count("\n")
        # walk the bullets that immediately follow (skip at most ONE blank line
        # before the block starts; stop at the first non-bullet once started).
        j = idx + 1
        started = False
        blanks = 0
        while j < len(lines):
            ln = lines[j]
            if not ln.strip():
                if started or blanks >= 1:
                    break
                blanks += 1
                j += 1
                continue
            mb = _BACKTICK_BULLET_RE.match(ln)
            if mb:
                started = True
                out.append((_norm(mb.group(1)), ln.strip()))
                j += 1
                continue
            break
    return out


def _norm(name: str) -> str:
    return name.strip().strip("`*").strip()


def _canon_multiword(name: str) -> str:
    """Underscore-join a multi-word state name ("Clock Toggle" -> "Clock_Toggle")
    so it reads as a single identifier-shaped state token. chip-AGNOSTIC."""
    return re.sub(r"\s+", "_", _norm(name))


# A localparam/parameter VALUE that is shaped like a STATE ENCODING (a small
# sized binary/hex literal or a small plain integer) — used to keep a config
# parameter (`MEM_ADDR_WIDTH = 16`, `N_ROM = 256`) from masquerading as a state.
# A state encoding is a 1-2 digit binary/hex sized literal (`2'b00`, `3'h5`) or a
# small unsized integer typical of a one-hot/sequential code. chip-AGNOSTIC.
_STATE_ENCODING_VALUE_RE = re.compile(
    r"^\s*\d*'[bBhHdD][0-9A-Fa-fxXzZ_]{1,8}\s*$"     # 2'b00, 3'h5
    r"|^\s*\d{1,2}\s*$",                              # small plain int 0..99
    re.IGNORECASE)


def _prose_state_names(prose: str) -> Set[str]:
    """ALL_CAPS names that appear in an explicit `<NAME> state` / `state <NAME>` /
    `in <NAME>` prose context. Used to (a) seed prose-only FSMs and (b) corroborate
    a localparam so a config parameter is not minted as a state. chip-AGNOSTIC."""
    names: Set[str] = set()
    for m in _NAME_STATE_PROSE_RE.finditer(prose):
        nm = _norm(m.group(1) or m.group(2) or "")
        if _is_state_token(nm):
            names.add(nm)
    # "between IDLE and ROLLING states" / "states: IDLE, RUN, DONE" enumerations
    for m in re.finditer(
            r"\bstates?\b\s*[:\-]?\s*([A-Z][A-Z0-9_]*(?:\s*(?:,|and|or|/)\s*"
            r"`?[A-Z][A-Z0-9_]*`?){1,})", prose):
        for tok in re.findall(r"[A-Z][A-Z0-9_]+", m.group(0)):
            if _is_state_token(tok):
                names.add(tok)
    for m in re.finditer(
            r"\bbetween\s+`?([A-Z][A-Z0-9_]+)`?\s+and\s+`?([A-Z][A-Z0-9_]+)`?\s+states?\b",
            prose):
        for g in m.groups():
            if _is_state_token(_norm(g)):
                names.add(_norm(g))
    return names


def _raw_transition_tokens(prose: str) -> Set[str]:
    """Lower-cased destination + source tokens named by a transition VERB, BEFORE
    any state-set is known — used to corroborate WEAK state candidates. A token a
    transition verb explicitly moves to/from is, by that fact, a state. Includes
    the explicit `in <X>` / `from <X>` source tokens. chip-AGNOSTIC."""
    toks: Set[str] = set()
    for m in _TRANS_RE.finditer(prose):
        toks.add(_norm(m.group(1)).lower())
    for m in re.finditer(
            r"\b(?:in|from|within|during|while\s+in)\s+(?:the\s+)?`?\*?\*?"
            r"\b([A-Za-z_]\w*)\b`?\*?\*?\s+state\b", prose, re.IGNORECASE):
        toks.add(_norm(m.group(1)).lower())
    return {t for t in toks if t}


def _collect_states(prose: str, code: str) -> Tuple[List[str], Dict[str, str]]:
    """Return (ordered distinct state names, name->evidence-line).

    Two-tier, corroboration-gated (the §4.05 no-leak core):
      * STRONG sources self-admit — an enum member, an inline `NAME(enc)`/`enc =
        NAME` encoding, a `**Name** (enc)` / `**NAME (n):**` encoded header, a
        `**NAME State:**` / `## NAME state` header (the encoding or the literal
        word "state" proves it names a state).
      * WEAK sources (a bare `**NAME**` bold heading, a `` - `name`: `` bullet —
        markup shared with document sections / port lists) admit ONLY when
        CORROBORATED by a transition naming the token or a `<NAME> state` prose
        mention. This is what keeps `**Inputs**`, `**Interface**`, `` - `clk`: ``
        from masquerading as states.
      * A localparam/parameter admits only when its value is state-encoding-shaped
        AND the name is corroborated (rejects `N_ROM = 256` config params).
      * Prose-only FSM (no structural state at all): fall back to the explicit
        `<NAME> state` ALL_CAPS prose enumeration (the dice-roller case)."""
    order: List[str] = []
    evidence: Dict[str, str] = {}
    prose_states = _prose_state_names(prose)
    trans_toks = _raw_transition_tokens(prose)
    corroborated = {s.lower() for s in prose_states} | trans_toks

    def _add(name: str, ev: str, *, structural: bool) -> None:
        nm = _norm(name)
        ok = _is_structural_state_token(nm) if structural else _is_state_token(nm)
        if not ok:
            return
        if nm not in evidence:
            order.append(nm)
            evidence[nm] = ev.strip()

    def _add_weak(name: str, ev: str) -> None:
        nm = _norm(name)
        if not _is_structural_state_token(nm):
            return
        if nm.lower() not in corroborated:
            return   # uncorroborated bare-bold / bullet — NOT a state (no leak)
        _add(nm, ev, structural=True)

    # (1) STRONG: enum members
    for m in _ENUM_BLOCK_RE.finditer(code):
        for member in m.group(1).split(","):
            nm = member.split("=")[0].strip().strip("`")
            if nm:
                _add(nm, "enum member: " + nm, structural=True)

    # (2) STRONG: inline encodings NAME(enc) / enc = NAME (multi-word names like
    # "Clock Toggle" are underscore-joined to one identifier token).
    for m in _ENC_NAME_FIRST_RE.finditer(prose):
        _add(m.group(1), m.group(0).strip(), structural=True)
    for m in _ENC_VAL_FIRST_RE.finditer(prose):
        # §4.05 PRECISION: a state-encoding NAME is conventionally CAPITALIZED
        # ("0 = Idle", "01 = Transmit", "10 = IDLE"). A lower-case phrase after a
        # single-bit value is a bit-FIELD value gloss ("1 = enabled", "0 = shift
        # LSB first"), NOT a state — reject it so a register bit-field table does
        # not mint phantom FSM states. chip-AGNOSTIC.
        name = m.group(2).strip()
        if not name[:1].isupper():
            continue
        _add(_canon_multiword(name), m.group(0).strip(), structural=True)

    # (3) STRONG: markdown encoded / "state"-worded section headers. The two
    # "state"-WORDED forms (`**NAME State**`, `## NAME state`) are strong only when
    # NAME is an ALL_CAPS / S-num state token; a Title-case name there ("Initial
    # State" = the starting CONDITION, not a state called "Initial") must be
    # corroborated — otherwise it is dropped (no leak). The two ENCODED forms
    # (`**Name** (00)`, `**NAME (0):**`) carry a real state code and stay strong
    # even Title-case (Idle/Transmit).
    _STATE_WORDED = {_MD_STRONG_PATTERNS[0], _MD_STRONG_PATTERNS[3]}
    for pat in _MD_STRONG_PATTERNS:
        for m in pat.finditer(prose):
            nm = next((g for g in m.groups() if g), None)
            if not nm:
                continue
            if pat in _STATE_WORDED and not _is_state_token(_norm(nm)):
                _add_weak(nm, m.group(0).strip())   # Title-case "State" header → gated
            else:
                _add(nm, m.group(0).strip(), structural=True)

    # (3b) STRONG: members of an FSM-state-list introduced by an explicit cue
    # ("Implements an FSM with states for:" + `- `INIT`: ...`). The cue is what
    # makes these self-corroborating (vs a generic port/signal bullet list).
    for nm, ev in _fsm_list_member_names(prose):
        _add(nm, ev, structural=True)

    # (4) WEAK (corroboration-gated): bare bold headings + backtick bullets
    for pat in _MD_WEAK_PATTERNS:
        for m in pat.finditer(prose):
            nm = next((g for g in m.groups() if g), None)
            if nm:
                _add_weak(nm, m.group(0).strip())

    # (5) localparam / parameter state-encodings (value-shaped + corroborated),
    # including comma-chained declarations (`localparam IDLE=0, GRANT_1=1, ...`).
    for src in (code, prose):
        for nm, val in _localparam_assignments(src):
            if not _STATE_ENCODING_VALUE_RE.match(val):
                continue
            if nm in evidence or nm.lower() in corroborated:
                _add(nm, "localparam " + nm + " = " + val, structural=True)

    # (6) TRANSITION-IMPLIED states (always runs). A datasheet FSM is often stated
    # purely as transition prose ("In the `IDLE` state … transitions to `LOAD`;
    # from `LOAD` … moves to `SHIFT` …"). Per this module's own doctrine, a token a
    # transition VERB explicitly moves TO — or an explicit `in/from <NAME> state`
    # SOURCE — is, by that fact, a state. This must run UNCONDITIONALLY (not only
    # when `order` is empty): a state-shaped token elsewhere in a multi-section
    # datasheet (a register/mode table) would otherwise make `order` non-empty and
    # silently drop the real transition-prose FSM. §4.05: only ALL_CAPS / S<n>
    # state-shaped tokens are admitted (a lower-case "the next stage" never
    # qualifies) AND each must be named by a real transition verb / `… state`
    # phrase, so this stays no-leak.
    for m in _TRANS_RE.finditer(prose):
        nm = _norm(m.group(1))
        if _is_state_token(nm):
            _add(nm, "transition target: " + nm, structural=False)
    for m in re.finditer(
            r"\b(?:in|from|within|during|while\s+in)\s+(?:the\s+)?`?\*?\*?"
            r"\b([A-Za-z_]\w*)\b`?\*?\*?\s+state\b", prose, re.IGNORECASE):
        nm = _norm(m.group(1))
        if _is_state_token(nm):
            _add(nm, "transition source: " + nm, structural=False)

    # (7) prose-only fallback — a `<NAME> state` mention with no transition (a
    # degenerate single-state mention) still seeds the prose state set.
    if not order:
        for nm in sorted(prose_states):
            _add(nm, "prose state mention: " + nm, structural=False)

    return order, evidence


# ---------------------------------------------------------------------------
# Transition collection
# ---------------------------------------------------------------------------
# A transition VERB phrase that moves the FSM to a destination state. The verb
# group is followed (after optional articles/words) by a state-name token.
_TRANS_VERB = (
    r"(?:transition(?:s|ed|ing)?(?:\s+(?:back|forward))?(?:\s+(?:in)?to)?"
    r"|move(?:s|d)?(?:\s+(?:back|forward|on))?(?:\s+(?:in)?to)?"
    r"|go(?:es|ing)?(?:\s+(?:back|forward))?(?:\s+(?:in)?to)?"
    r"|return(?:s|ed|ing)?(?:\s+back)?\s+to"        # "returns to/back to" — to mandatory
    r"|proceed(?:s|ed)?(?:\s+to)?"
    r"|advance(?:s|d)?(?:\s+to)?"
    r"|jump(?:s|ed)?(?:\s+to)?"
    r"|enter(?:s|ed|ing)?"
    r"|switch(?:es|ed)?(?:\s+to)?"
    r"|reset(?:s)?\s+(?:back\s+)?to"                # "resets to" — to mandatory so
                                                   # "resets <reg> to <val>" is not a
                                                   # state transition
    r"|remain(?:s)?(?:\s+(?:in|at))?"   # self-loop ("remains in IDLE")
    r")")
# articles / fillers permitted between the verb and the destination state name.
# "to"/"into" are NOT here — the verbs above already optionally consume them, so
# leaving them out of the filler prevents "resets <reg> to <val>" from skipping
# the register and landing on a later state token.
_DEST_FILLER = (
    r"(?:\s+(?:the|a|an|back|its|next|new|`))*\s*")
# A transition statement: <verb> [filler] **/`NAME`/NAME — capture the dest token
# as a generic identifier; the CALLER resolves it case-insensitively against the
# known state set (so Title-case states like "Idle" match). chip-AGNOSTIC.
_TRANS_RE = re.compile(
    _TRANS_VERB + _DEST_FILLER +
    r"\*?\*?`?\b([A-Za-z_]\w*)\b`?\*?\*?",
    re.IGNORECASE)

# A table row `| state | next | ... |` — header must NAME a state/current column
# AND a next/destination column; rows then map current->next.
_TABLE_LINE_RE = re.compile(r"^\s*\|(.+)\|\s*$", re.MULTILINE)


def _row_cells(line: str) -> List[str]:
    # split a markdown table row into trimmed cells
    inner = line.strip().strip("|")
    return [c.strip().strip("`*") for c in inner.split("|")]


def _condition_clause(sentence: str, dest_pos: int) -> str:
    """Best-effort condition for a transition: a leading `when/if/on/upon ...`
    clause in the sentence before the destination, else "". Trimmed, chip-AGNOSTIC."""
    head = sentence[:dest_pos]
    m = re.search(r"\b(?:when|if|on|upon|once|after|while)\b([^,.;]*)$", head,
                  re.IGNORECASE)
    if m:
        return m.group(0).strip()
    # look anywhere earlier in the sentence
    m = re.search(r"\b(?:when|if|on|upon|once|after|while)\b([^,.;]*)",
                  sentence, re.IGNORECASE)
    return m.group(0).strip() if m else ""


def _split_sentences(prose: str) -> List[str]:
    # split on sentence terminators AND newlines so a per-line transition
    # ("- Moves to WRITE when ...") is its own unit.
    parts = re.split(r"(?<=[.;\n])", prose)
    return [p for p in parts if p.strip()]


def _resolve_state(tok: str, by_lower: Dict[str, str]) -> Optional[str]:
    """Map an any-case token to its canonical state name (case-insensitive),
    or None when it is not a known state. chip-AGNOSTIC."""
    return by_lower.get(_norm(tok).lower())


def _current_state_for(sentence: str, by_lower: Dict[str, str],
                       section_state: Optional[str],
                       dest_pos: int) -> Optional[str]:
    """The SOURCE state of a transition stated in `sentence`. Prefer an explicit
    "in <STATE>" / "from <STATE>" / "<STATE> state" mention BEFORE the destination
    in the sentence; else the enclosing markdown state SECTION (section_state).
    Case-insensitive state resolution."""
    head = sentence[:dest_pos] if dest_pos else sentence
    # explicit "in STATE", "from STATE", "while in the STATE state"
    best = None
    for m in re.finditer(
            r"\b(?:in|from|within|during|at|while\s+in)\s+(?:the\s+)?`?\*?\*?"
            r"\b([A-Za-z_]\w*)\b`?\*?\*?(?:\s+state)?",
            head, re.IGNORECASE):
        cand = _resolve_state(m.group(1), by_lower)
        if cand is not None:
            best = cand   # last explicit source before the destination wins
    if best is not None:
        return best
    return section_state


# A section region: (start_pos, owner_state). Transitions whose sentence starts
# inside [start, next_start) default to `owner_state` as the SOURCE. This BOUNDS
# section ownership so a flat prose paragraph BELOW all the per-state sections
# does NOT inherit the last section's state (the sdram/ethernet mis-resolution).
def _section_regions(prose: str, by_lower: Dict[str, str]
                     ) -> List[Tuple[int, int, str]]:
    """Sorted list of (start, end, owner_state) for each markdown state-section
    header that names a known state, bounded by the next such header."""
    headers: List[Tuple[int, str]] = []
    for pat in _MD_SECTION_HEADER_PATTERNS:
        for m in pat.finditer(prose):
            nm = _resolve_state(_norm(next((g for g in m.groups() if g), "")),
                                by_lower)
            if nm is not None:
                headers.append((m.start(), nm))
    headers.sort()
    regions: List[Tuple[int, int, str]] = []
    for i, (start, nm) in enumerate(headers):
        end = headers[i + 1][0] if i + 1 < len(headers) else len(prose)
        regions.append((start, end, nm))
    return regions


def _section_owner_for(regions: List[Tuple[int, int, str]],
                       pos: int) -> Optional[str]:
    for start, end, owner in regions:
        if start <= pos < end:
            return owner
    return None


def _collect_transitions(prose: str, states: List[str]
                         ) -> List[Tuple[str, str, str, str]]:
    """Return list of (source_state, condition, next_state, evidence_line).

    Sources: (a) prose transition verbs anchored to a known destination state,
    with the source resolved from an in-sentence "in <STATE>" or the BOUNDED
    enclosing markdown section; (b) a `| state | next | ... |` table. State
    resolution is case-insensitive so Title-case states (Idle/Transmit) match."""
    by_lower = {s.lower(): s for s in states}
    regions = _section_regions(prose, by_lower)
    out: List[Tuple[str, str, str, str]] = []
    seen: Set[Tuple[str, str, str]] = set()

    # (a) prose / per-line transitions
    for sent in _split_sentences(prose):
        spos = prose.find(sent)
        for m in _TRANS_RE.finditer(sent):
            dest = _resolve_state(m.group(1), by_lower)
            if dest is None:
                continue
            section_owner = _section_owner_for(regions, max(spos, 0))
            src = _current_state_for(sent, by_lower, section_owner, m.start())
            is_self_loop = bool(re.search(r"\bremain", m.group(0), re.IGNORECASE))
            if src is not None and src == dest and not is_self_loop:
                # "moves to IDLE" resolved to its own section is a mis-resolution;
                # keep only explicit self-loops ("remains in IDLE"). Do NOT drop
                # the edge — fall back to an unspecified source rather than emit a
                # spurious self-loop (no fabricated source).
                src = None
            # src may be None: the destination edge IS stated even when the source
            # is not resolvable (a 2-state prose FSM with implicit source). Record
            # it with an empty source rather than fabricate a wrong one.
            src_key = src or ""
            cond = _condition_clause(sent, m.start())
            key = (src_key, cond, dest)
            if key in seen:
                continue
            seen.add(key)
            out.append((src_key, cond, dest, sent.strip()))

    # (b) state/next table
    out.extend(_table_transitions(prose, states, seen))
    return out


# ---------------------------------------------------------------------------
# Named-state one-cycle output collection (Issue #1950)
# ---------------------------------------------------------------------------
# These forms are deliberately narrow: the output identifier must be quoted or
# sit directly in a set/assert/drive/pulse/trigger clause, the clause must state
# exactly one cycle, and the owner must be an explicit state section / an
# ``in|during <STATE>`` phrase / the unique destination of that same sentence.
# A free-standing ``done pulses for one cycle`` therefore does NOT invent a
# state owner.  This is the §4.05 no-leak boundary.
_STATE_OUTPUT_PATTERNS = (
    re.compile(
        r"\b(?:sets?|asserts?|drives?|raises?|pulses?)\s+"
        r"(?:the\s+)?`?([A-Za-z_]\w*)`?(?:\s+signal)?\s+"
        r"(?:to\s+)?(?:high|1\s*'\s*b1|1)\b[^.;\n]{0,100}?"
        r"\b(?:for|during)\s+(?:exactly\s+)?one(?:\s+clock)?\s+cycle\b",
        re.IGNORECASE),
    re.compile(
        r"`([A-Za-z_]\w*)`\s+(?:is\s+)?(?:set\s+to|goes|pulses?|asserts?)\s+"
        r"(?:high|1\s*'\s*b1|1)\b[^.;\n]{0,100}?"
        r"\b(?:for|during)\s+(?:exactly\s+)?one(?:\s+clock)?\s+cycle\b",
        re.IGNORECASE),
    re.compile(
        r"\btriggers?\s+(?:the\s+)?`?([A-Za-z_]\w*)`?(?:\s+signal)?\s+"
        r"(?:high\s+)?(?:for|during)\s+(?:exactly\s+)?one"
        r"(?:\s+clock)?\s+cycle\b",
        re.IGNORECASE),
    re.compile(
        r"`([A-Za-z_]\w*)`[^.;\n]{0,50}?\bactive\s+high\b[^.;\n]{0,50}?"
        r"\b(?:for|during)\s+(?:exactly\s+)?one(?:\s+clock)?\s+cycle\b",
        re.IGNORECASE),
)
_NON_SIGNAL_NAMES = {
    "a", "an", "the", "to", "signal", "signals", "output", "outputs",
    "pulse", "pulses", "state", "states", "cycle", "cycles",
}


def _state_output_regions(prose: str, by_lower: Dict[str, str]
                          ) -> List[Tuple[int, int, str]]:
    """Per-state sections bounded by the next state OR document heading.

    The transition extractor intentionally lets the last state section reach the
    document end because flat transition prose may follow it.  Output ownership
    must be stricter: a later ``## Assumptions`` / numbered bold section is not
    still an action of the preceding state.
    """
    state_headers: List[Tuple[int, str]] = []
    for pat in _MD_SECTION_HEADER_PATTERNS:
        for m in pat.finditer(prose):
            nm = _resolve_state(_norm(next((g for g in m.groups() if g), "")),
                                by_lower)
            if nm is not None:
                state_headers.append((m.start(), nm))
    state_headers.sort()
    generic = sorted({m.start() for m in re.finditer(
        r"^\s*(?:#{1,6}\s+.+|\d+[.)]\s+\*\*[^\n]+\*\*)",
        prose, re.MULTILINE)})
    regions: List[Tuple[int, int, str]] = []
    for start, owner in state_headers:
        later = [p for p in generic if p > start]
        end = later[0] if later else len(prose)
        regions.append((start, end, owner))
    return regions


def _sentence_spans(prose: str):
    """Yield ``(start, sentence)`` without losing the absolute section offset."""
    start = 0
    for m in re.finditer(r".*?(?:[.;\n]|\Z)", prose, re.DOTALL):
        sent = m.group(0)
        if sent.strip():
            yield m.start(), sent
        start = m.end()
    if start < len(prose) and prose[start:].strip():  # defensive; \Z normally wins
        yield start, prose[start:]


def _explicit_state_owner(sentence: str, sentence_pos: int,
                          states: List[str],
                          regions: List[Tuple[int, int, str]]) -> Optional[str]:
    """Resolve the state that owns an output clause, or None rather than guess.

    Priority is the enclosing per-state section, then an explicit in/during
    state phrase, then a UNIQUE transition destination in the same sentence.
    The final form covers prose such as ``pulse error for one cycle and move to
    ERROR_STATE`` while refusing a sentence with two different destinations.
    """
    by_lower = {s.lower(): s for s in states}
    section = _section_owner_for(regions, sentence_pos)
    if section is not None:
        return section

    owners: List[str] = []
    for m in re.finditer(
            r"\b(?:in|during|within|while\s+in)\s+(?:the\s+)?`?\*?\*?"
            r"([A-Za-z_]\w*)`?\*?\*?(?:\s+state)?\b",
            sentence, re.IGNORECASE):
        owner = _resolve_state(m.group(1), by_lower)
        if owner is not None and owner not in owners:
            owners.append(owner)
    if len(owners) == 1:
        return owners[0]
    if len(owners) > 1:
        return None

    dests: List[str] = []
    for m in _TRANS_RE.finditer(sentence):
        # A pulse followed by "reset/return to IDLE" belongs to the terminal
        # event, not to the quiescent destination.  Only an explicit move /
        # transition / enter-style destination can provide ownership here.
        if re.match(r"\s*(?:reset|return)", m.group(0), re.IGNORECASE):
            continue
        dest = _resolve_state(m.group(1), by_lower)
        if dest is not None and dest.upper() not in {"IDLE", "RESET", "WAIT"} \
                and dest not in dests:
            dests.append(dest)
    return dests[0] if len(dests) == 1 else None


def _collect_state_outputs(prose: str, states: List[str]) -> List[Tuple[str, str, str]]:
    """Return ``(owner_state, output_signal, evidence)`` for explicit one-cycle
    named-state output clauses.  First occurrence wins; no owner means no item."""
    by_lower = {s.lower(): s for s in states}
    regions = _state_output_regions(prose, by_lower)
    out: List[Tuple[str, str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    for pos, sentence in _sentence_spans(prose):
        signals: List[str] = []
        for pat in _STATE_OUTPUT_PATTERNS:
            for m in pat.finditer(sentence):
                sig = _norm(m.group(1))
                if (_IDENT_RE.fullmatch(sig)
                        and sig.lower() not in _NON_SIGNAL_NAMES
                        and sig not in signals):
                    signals.append(sig)
        if not signals:
            continue
        owner = _explicit_state_owner(sentence, pos, states, regions)
        if owner is None:
            continue
        evidence = sentence.strip()
        for sig in signals:
            key = (owner.lower(), sig.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append((owner, sig, evidence))
    return out


def _table_transitions(prose: str, states: Set[str],
                       seen: Set[Tuple[str, str, str]]
                       ) -> List[Tuple[str, str, str, str]]:
    out: List[Tuple[str, str, str, str]] = []
    lines = _TABLE_LINE_RE.findall(prose)
    if len(lines) < 2:
        return out
    header = _row_cells("|" + lines[0] + "|")
    low = [h.lower() for h in header]

    def _find_col(keys: List[str]) -> Optional[int]:
        for i, h in enumerate(low):
            if any(k in h for k in keys):
                return i
        return None

    by_lower = {s.lower(): s for s in states}
    cur_col = _find_col(["current state", "state", "from"])
    nxt_col = _find_col(["next state", "next", "to", "destination"])
    if cur_col is None or nxt_col is None or cur_col == nxt_col:
        return out
    cond_col = _find_col(["condition", "input", "when", "event"])
    for raw in lines[1:]:
        cells = _row_cells("|" + raw + "|")
        if set("".join(cells)) <= set("-: "):   # separator row
            continue
        if max(cur_col, nxt_col) >= len(cells):
            continue
        src = _resolve_state(cells[cur_col], by_lower)
        dst = _resolve_state(cells[nxt_col], by_lower)
        if src is None or dst is None:
            continue
        cond = ""
        if cond_col is not None and cond_col < len(cells):
            cond = cells[cond_col].strip()
        key = (src, cond, dst)
        if key in seen:
            continue
        seen.add(key)
        out.append((src, cond, dst, "table row: | " + " | ".join(cells) + " |"))
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def extract(prompt_text: str) -> List[Dict]:
    """Extract a stated FSM's states + transitions from `prompt_text`.

    Returns a list of dicts (each shaped for `spec_coverage_check.ChecklistItem`):
    one `fsm_state` item per stated NAMED state and one `fsm_transition` item per
    stated (state, condition -> next).

    §4.05 no-leak gate: require >= 2 distinct named states AND >= 1 explicit
    transition. A vague "implement a state machine" with no enumerated states /
    no explicit transition returns []. chip-AGNOSTIC: keys on FSM structure
    (state-name shape + transition statement), never a problem id."""
    if not prompt_text or not prompt_text.strip():
        return []

    full = prompt_text
    code = _strip_block_and_line_comments(full)
    # prose = the full text WITHOUT verilog comments (markdown lives outside
    # comments; code lives inside fenced blocks but the matchers are robust to it).
    prose = code

    states, state_ev = _collect_states(prose, code)

    # transitions anchor states; both endpoints of every collected transition are
    # — by construction — already in `states` (the matchers resolve only known
    # states), so the transition pass adds no new state. It is run after the state
    # pass purely to attribute the stated edges.
    transitions = _collect_transitions(prose, states)

    # §4.05 HARD GATE — no fabrication.
    if len(states) < 2 or len(transitions) < 1:
        return []

    items: List[Dict] = []
    # one fsm_state item per named state
    for nm in states:
        items.append({
            "kind": "fsm_state",
            "requirement": "FSM has a state named " + nm
                           + "; the design must implement it and the TB must "
                           + "drive the FSM through it.",
            "evidence": state_ev.get(nm, nm),
            "coverage_tokens": [nm],
            "state": nm,
            "next_state": "",
            "condition": "",
        })
    # one fsm_state_output item per explicit state-owned one-cycle assertion.
    # The generated implementation contract is Moore-shaped: asserted from the
    # CURRENT named state, deasserted everywhere else.  That avoids the
    # transition-arm/NBA phase skew captured by Issue #1950.
    for owner, signal, ev in _collect_state_outputs(prose, states):
        items.append({
            "kind": "fsm_state_output",
            "requirement": ("In state " + owner + ", output " + signal
                            + " is asserted high for exactly one cycle and "
                            + "deasserted outside that state."),
            "evidence": ev,
            "coverage_tokens": [owner, signal],
            "state": owner,
            "next_state": "",
            "condition": "",
            "signal": signal,
            "asserted_value": 1,
            "duration_cycles": 1,
        })
    # one fsm_transition item per stated edge
    for src, cond, dst, ev in transitions:
        cond_txt = (" when " + cond) if cond else ""
        if src:
            req = ("In state " + src + cond_txt
                   + ", the FSM transitions to " + dst
                   + "; the TB must exercise this edge.")
            tokens = sorted({src, dst})
        else:
            # source not resolvable from the prompt — the destination edge is
            # still stated; do not fabricate a source.
            req = ("The FSM transitions to " + dst + cond_txt
                   + "; the TB must exercise this edge.")
            tokens = [dst]
        items.append({
            "kind": "fsm_transition",
            "requirement": req,
            "evidence": ev,
            "coverage_tokens": tokens,
            "state": src,
            "next_state": dst,
            "condition": cond,
        })
    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="PROGRAM-FIRST structural extractor for stated FSMs "
                    "(states + transitions). chip-AGNOSTIC, §4.05 no-leak.")
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
        print("NO STATED FSM (no >=2 named states + >=1 explicit transition) "
              "-> [] (no fabrication)")
        return 0

    states = [it for it in items if it["kind"] == "fsm_state"]
    trans = [it for it in items if it["kind"] == "fsm_transition"]
    outputs = [it for it in items if it["kind"] == "fsm_state_output"]
    print("STATES (" + str(len(states)) + "):")
    for it in states:
        print("  - " + it["state"] + "   [" + it["evidence"][:70] + "]")
    print("TRANSITIONS (" + str(len(trans)) + "):")
    for it in trans:
        cond = (" when " + it["condition"]) if it["condition"] else ""
        print("  - " + it["state"] + cond + " -> " + it["next_state"])
        print("      evidence: " + it["evidence"][:90])
    print("STATE OUTPUTS (" + str(len(outputs)) + "):")
    for it in outputs:
        print("  - " + it["state"] + ": " + it["signal"] + " = 1 (one cycle)")
        print("      evidence: " + it["evidence"][:90])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
