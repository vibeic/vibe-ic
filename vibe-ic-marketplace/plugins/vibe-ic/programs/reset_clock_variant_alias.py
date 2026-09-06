#!/usr/bin/env python3
"""Reset/clock spelling proposals and explicit public-interface adaptation.

Recognizing equivalent spellings is not authorization to change an interface.
`plan_aliases` only proposes same-role/same-polarity renames; automatic callers
must require a requested public contract before applying them. The standalone
CLI mutation requires explicit SOURCE=TARGET mappings and never guesses names;
an already-canonical interface may return a named no-op without a mapping.
The emitters also accept explicit maps for intentional compatibility wrappers.

ABSOLUTE GUARANTEE — POLARITY IS NEVER CROSSED
----------------------------------------------
An active-LOW reset (`reset_n`, `rstn`, `nreset`, `resetb`, …) only ever maps to
another active-low name; an active-HIGH reset (`reset`, `rst`, `areset`) only to
an active-high name. `emit_variant_alias_wrapper` RAISES on any cross-polarity
rename. Wiring an active-high reset to an active-low port name would silently
inverts the reset semantic — that must never happen.

HONEST LIMIT
------------
Only the closed set of reset/clock spellings below is recognised. Recognition
does not prove the design's electrical semantics; callers must supply a valid
interface contract. An unknown spelling is not silently reinterpreted.

chip-AGNOSTIC: only the generic reset/clock spelling sets are baked in.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Standard reset spellings, split by polarity. Active-low names carry an
# explicit low-asserted marker (`_n`/`n`/`_b`/`b` suffix or `n` prefix).
_RESET_ACTIVE_LOW = frozenset({
    "rst_n", "rstn", "reset_n", "resetn", "arst_n", "arstn",
    "nrst", "nreset", "n_rst", "n_reset", "rst_b", "resetb", "reset_b",
})
_RESET_ACTIVE_HIGH = frozenset({
    "rst", "reset", "arst", "areset", "rst_i", "reset_i",
})
# Canonical target spelling per reset polarity.
_RESET_CANON = {"active_low": "rst_n", "active_high": "rst"}

# Standard clock spellings (no polarity) + canonical target.
_CLOCK_NAMES = frozenset({"clk", "clock", "clk_i", "clock_i", "clk_in"})
_CLOCK_CANON = "clk"


def classify_reset(name: str) -> Optional[str]:
    """Return 'active_low' / 'active_high' if `name` is a recognised standard
    reset spelling, else None."""
    n = name.lower()
    if n in _RESET_ACTIVE_LOW:
        return "active_low"
    if n in _RESET_ACTIVE_HIGH:
        return "active_high"
    return None


def is_clock(name: str) -> bool:
    return name.lower() in _CLOCK_NAMES


def equivalent_variants(name: str) -> List[str]:
    """Standard spellings equivalent to `name` (same reset polarity, or the
    clock set), EXCLUDING `name` itself. [] when `name` is not recognised."""
    n = name.lower()
    pol = classify_reset(n)
    if pol == "active_low":
        pool = _RESET_ACTIVE_LOW
    elif pol == "active_high":
        pool = _RESET_ACTIVE_HIGH
    elif is_clock(n):
        pool = _CLOCK_NAMES
    else:
        return []
    return sorted(v for v in pool if v != n)


def canonical_variant(name: str) -> Optional[str]:
    """The canonical target spelling for `name`'s polarity/role, else None."""
    pol = classify_reset(name)
    if pol:
        return _RESET_CANON[pol]
    if is_clock(name):
        return _CLOCK_CANON
    return None


def _same_class(a: str, b: str) -> bool:
    """True iff a and b are reset of the SAME polarity, or both clocks."""
    pa, pb = classify_reset(a), classify_reset(b)
    if pa or pb:
        return pa is not None and pa == pb
    return is_clock(a) and is_clock(b)


def plan_aliases(port_names: List[str],
                 contract_ports: "Optional[set]" = None) -> Dict[str, str]:
    """Propose canonical same-polarity renames; this is NOT mutation authority.

    Skips a port if the canonical name would collide with another EXISTING port
    OR with a canonical name ALREADY ASSIGNED to an earlier port in this plan —
    so a design declaring two same-polarity variants (e.g. `reset_n` AND `rstn`,
    both → `rst_n`) never produces a duplicate wrapper port (ORGANIC #518
    adversarial review). Only the first such variant is canonicalised; the rest
    keep their original spelling. POLARITY-SAFE by construction.

    `contract_ports` pins source spellings that must remain public. None/empty
    suppresses no proposals, but does not authorize any of them: a mutating
    caller must separately check that the requested interface names the target
    and does not require the source. Naming two resets does not authorize
    combining them. This helper itself never writes RTL."""
    existing = {p.lower() for p in port_names}
    contract = {c.lower() for c in (contract_ports or set())}
    assigned_targets: set = set()
    plan: Dict[str, str] = {}
    for p in port_names:
        canon = canonical_variant(p)
        if canon is None or canon == p.lower():
            continue
        if p.lower() in contract:
            # The design's OWN contract declares this spelling — it IS the
            # public name. Preserve the original spelling; do not alias.
            continue
        if canon in existing:
            continue  # would collide with a real port — skip
        if canon in assigned_targets:
            continue  # another same-polarity variant already took this name
        # canonical_variant guarantees same class; assert it explicitly.
        if not _same_class(p, canon):
            continue
        plan[p] = canon
        assigned_targets.add(canon)
    return plan


# ORGANIC #689 — design-contract reader. The design's OWN contract (the staged
# prompt / external-interface doc) is the FIRST-CLASS source of the TB-facing
# reset/clock port spelling, on par with the #618 staged-SDC pin and the #518
# L9 native-port pin. When the contract already declares a STANDARD reset/clock
# spelling, that spelling is part of the public interface, so the adapter must
# NOT rename it (doing so makes the wrapper expose a different port → a hard
# `port <X> is not a port` elaboration FAIL).

# Files (in any project layout) that carry the design's own port contract:
# the verbatim external-interface / prompt / description text + the parsed L3.
_CONTRACT_GLOBS = (
    "phase1/generated_docs/L3*.json",   # parsed structured port list (best)
    "phase1/input_doc/L3*",             # verbatim external-interface doc (Path A)
    "phase1/input_doc/*",               # other staged vendor-doc extracts
    "input/docs/L3*",                   # legacy external-interface doc
    "input/docs/design_description*",   # auto-bridged prompt → description
    "input/docs/*",
    "input/phase1_prompt.md",           # Path B free-text prompt
    "phase1/input_prompt/*",            # Path B dialogue / fact-graph workspace
)
# A reset/clock spelling counts as CONTRACT-DECLARED only when it appears in a
# PORT-DECLARATION context — never from loose prose ("assert the reset"). The
# three port-naming contexts a design contract uses:
#   (1) a Verilog ANSI port decl  : `input clk,` / `input wire rst_n`
#   (2) a markdown / backtick name : `` `reset` `` or a `| reset |` table cell
#   (3) an explicit "port" phrasing: `port reset` / `signal clk` / `clk port`
# Each is anchored so a spelling buried in prose does not over-suppress.
_CONTRACT_NAME_TOKENS = "|".join(
    re.escape(n) for n in sorted(
        set(_RESET_ACTIVE_LOW) | set(_RESET_ACTIVE_HIGH) | set(_CLOCK_NAMES),
        key=len, reverse=True))
_CONTRACT_BACKTICK_RE = re.compile(rf"`\s*({_CONTRACT_NAME_TOKENS})\s*`",
                                   re.IGNORECASE)
_CONTRACT_TABLECELL_RE = re.compile(
    rf"\|\s*`?\s*({_CONTRACT_NAME_TOKENS})\s*`?\s*\|", re.IGNORECASE)
_CONTRACT_VERILOG_RE = re.compile(
    rf"\b(?:input|output|inout)\b[\w\s\[\]:.-]*?\b({_CONTRACT_NAME_TOKENS})\b",
    re.IGNORECASE)
_CONTRACT_PHRASE_RE = re.compile(
    rf"\b(?:port|signal|pin)\s+`?({_CONTRACT_NAME_TOKENS})`?\b"
    rf"|\b`?({_CONTRACT_NAME_TOKENS})`?\s+(?:port|signal|pin)\b",
    re.IGNORECASE)

# ORGANIC #518 reopen (round-11) — the DOMINANT RTLLM/VerilogEval port-contract
# form is a colon list under an `Input ports:` / `Output ports:` heading:
#     Input ports:
#         arstn: active-low async reset
#         clk:   system clock
# The four context regexes above (backtick / table cell / Verilog decl /
# `port <name>` phrasing) never match this `NAME: <description>` line, so the
# spec-declared reset/clock port (e.g. `arstn`) was NOT registered as a contract
# port → #518 canonicalised it (arstn -> rst_n) UNSUPPRESSED and the hidden TB
# binding `.arstn(arstn)` then `port 'arstn' is not a port of dut`-FAILed.
#
# Recognise a colon-form port LINE (multiline-anchored `^\s*<token>\s*:`) but
# ONLY inside an `Input/Output ports:` SECTION, so a stray `reset:` in loose
# prose elsewhere never over-suppresses (no-leak). The section runs from its
# heading to the next blank line / next `*** ports:` heading / EOF.
_CONTRACT_PORTSECTION_HDR_RE = re.compile(
    r"^[ \t>*#-]*\b(?:input|output|inout|i/o|in|out)\b[ \t]*ports?\s*[：:]?\s*$",
    re.IGNORECASE | re.MULTILINE)
_CONTRACT_COLON_LINE_RE = re.compile(
    rf"^[ \t>*#-]*`?\s*({_CONTRACT_NAME_TOKENS})\s*`?\s*[：:]",
    re.IGNORECASE | re.MULTILINE)


def _contract_ports_from_colon_form(text: str) -> set:
    """ORGANIC #518 reopen — reset/clock spellings declared in the RTLLM /
    VerilogEval `Input ports:` / `Output ports:` colon-form. A `NAME: <desc>`
    line registers ONLY when it sits inside such a port section (heading → next
    blank line / next ports heading / EOF), so a `reset:` in unrelated prose is
    never registered — the suppression stays scoped to genuine port contracts."""
    found: set = set()
    hdrs = list(_CONTRACT_PORTSECTION_HDR_RE.finditer(text))
    for k, h in enumerate(hdrs):
        start = h.end()
        # The section body ends at the next ports-heading, the first blank line
        # after the body began, or EOF — whichever comes first.
        nxt_hdr = hdrs[k + 1].start() if k + 1 < len(hdrs) else len(text)
        body = text[start:nxt_hdr]
        blank = re.search(r"\n[ \t]*\n", body)
        if blank:
            body = body[:blank.start()]
        for m in _CONTRACT_COLON_LINE_RE.finditer(body):
            found.add(m.group(1).lower())
    return found


def _contract_ports_from_text(text: str) -> set:
    """The reset/clock spellings declared as PORTS in one contract-doc `text`.
    Only port-declaration contexts count (backtick name / markdown table cell /
    Verilog port decl / explicit `port <name>` phrasing / `Input ports:` colon-
    form) — loose prose mentions of "reset"/"clock" do NOT register, so the
    suppression never over-fires."""
    found: set = set()
    for re_ in (_CONTRACT_BACKTICK_RE, _CONTRACT_TABLECELL_RE,
                _CONTRACT_VERILOG_RE):
        for m in re_.finditer(text):
            found.add(m.group(1).lower())
    for m in _CONTRACT_PHRASE_RE.finditer(text):
        tok = m.group(1) or m.group(2)
        if tok:
            found.add(tok.lower())
    found |= _contract_ports_from_colon_form(text)
    return found


def _contract_ports_from_l3_json(data) -> set:
    """Reset/clock spellings from a parsed L3 external-interface JSON's port
    list (whatever key carries it — `top_ports` / `ports` / `port_list` /
    `external_interface`). Each entry may be a bare name or a `{name: …}` dict.
    Only recognised standard reset/clock spellings are returned."""
    found: set = set()

    def _walk(obj):
        if isinstance(obj, dict):
            nm = obj.get("name") or obj.get("port") or obj.get("signal")
            if isinstance(nm, str) and (classify_reset(nm) or is_clock(nm)):
                found.add(nm.lower())
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                if isinstance(v, str) and (classify_reset(v) or is_clock(v)):
                    found.add(v.lower())
                else:
                    _walk(v)
    _walk(data)
    return found


def design_contract_ports(project: Path) -> set:
    """ORGANIC #689 — return the (lowercased) set of STANDARD reset/clock port
    spellings the design's OWN contract declares: the staged prompt /
    external-interface doc / parsed L3 port list.

    This is the design's TB-facing contract — the SAME ground-truth ranking as
    the #618 staged-SDC pin (:func:`sdc_constraints.staged_constrained_ports`)
    and the #518 L9 native-port pin. `plan_aliases(..., contract_ports=<this>)`
    drops the proposal for any port whose spelling is pinned here.

    Returns an EMPTY set when no contract doc is staged. An empty set is not
    permission to rename; the mutating caller needs explicit target authority.
    chip-AGNOSTIC: port-declaration grammar + the closed standard reset/clock
    spelling set; no chip/vendor/SKU literal."""
    pinned: set = set()
    seen: set = set()
    for pat in _CONTRACT_GLOBS:
        for f in sorted(project.glob(pat)):
            rp = f.resolve()
            if rp in seen or not f.is_file():
                continue
            seen.add(rp)
            try:
                raw = f.read_text(errors="replace")
            except OSError:
                continue
            if f.suffix == ".json":
                try:
                    pinned |= _contract_ports_from_l3_json(json.loads(raw))
                    continue
                except (ValueError, TypeError):
                    pass  # fall through to text scan on malformed JSON
            pinned |= _contract_ports_from_text(raw)
    return pinned


# ORGANIC #186 — recognised structured port-list keys in an L3 external-interface
# JSON / L9 integration spec. A LIST under one of these is an AUTHORITATIVE,
# COMPLETE enumeration of the top interface (the documented port contract), as
# opposed to loose prose that merely mentions a reset spelling.
_L3_PORTLIST_KEYS = frozenset({
    "top_ports", "ports", "port_list", "portlist", "external_interface",
    "interface", "interfaces", "pins", "pin_list", "signals", "io", "ios"})


def _all_port_names_from_l3_json(data) -> Optional[set]:
    """The COMPLETE lowercased set of top port names from a STRUCTURED L3 port
    table — or None when the JSON carries no recognisable port-list array. Only
    a LIST of port entries (bare-name strings, or dicts carrying a
    name/port/signal key) under a recognised port-list key counts as an
    authoritative enumeration; a bus suffix (`addr[7:0]`) is stripped to the
    bare name. chip-AGNOSTIC: pure structural walk, no chip literal."""
    found: set = set()
    got = False

    def _add(nm) -> None:
        nonlocal got
        if isinstance(nm, str):
            bare = re.sub(r"\[.*", "", nm).strip().lower()
            if bare:
                found.add(bare)
                got = True

    def _walk(obj) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if (isinstance(k, str) and k.lower() in _L3_PORTLIST_KEYS
                        and isinstance(v, list)):
                    for e in v:
                        if isinstance(e, str):
                            _add(e)
                        elif isinstance(e, dict):
                            _add(e.get("name") or e.get("port")
                                 or e.get("signal"))
                _walk(v)
        elif isinstance(obj, list):
            for e in obj:
                _walk(e)

    _walk(data)
    return found if got else None


# The structured, generated-doc sources whose port list is AUTHORITATIVE — a
# parsed L3 external-interface JSON port table (best), or the L9 integration
# spec's top_ports. Without an explicit enumeration, automatic callers must
# decline to infer a replacement interface.
_AUTHORITATIVE_L3_GLOBS = ("phase1/generated_docs/L3*.json",)
_AUTHORITATIVE_L9_GLOBS = (
    "phase1/**/L9_INTEGRATION_SPEC.json",
    "phase1/generated_docs/L9*.json")

# ORGANIC #186 r2 — the AUTHORED L3/L9 documents themselves. The round-1 fix
# only accepted a STRUCTURED JSON enumeration (`phase1/generated_docs/L3*.json`,
# L9 `top_ports`), but that JSON is a DOWNSTREAM EXTRACTION of the real source of
# truth: the L3 external-interface document's port table. Whenever phase-1 has
# not produced that JSON yet, or produced it with an EMPTY `top_ports` (a state
# the #689 note records as observed in the field: "L9 top_ports==[]"), the
# markdown port table is the ONLY authoritative enumeration on disk — and the
# round-1 fix read it as loose prose, so the #792 additive re-grafted the 9th
# reset port onto a documented N-port top. These globs are keyed on the LAYER
# FILENAME (L3 external-interface / L9 integration), never on content type, so a
# free-text prompt (`input/phase1_prompt.md`) or the auto-bridged
# `design_description.md` needs an explicit port enumeration to authorize edits.
_AUTHORITATIVE_DOC_GLOBS = (
    "phase1/input_doc/L3*",
    "phase1/input_doc/L9*",
    "input/docs/L3*",
    "input/docs/L9*",
)

# A markdown/pipe table row is an authoritative PORT-TABLE row only when one of
# its cells is a bare DIRECTION keyword — the column that makes the table an
# interface enumeration rather than a register map / prose table. The port NAME
# is the first cell (optionally backtick-quoted, optionally bus-suffixed). The
# direction column may sit anywhere and the header may be in ANY language (the
# sha256 L3 ships `| 訊號 | 寬度 | 方向 | 描述 |`), so the row is keyed on the
# direction VALUES, which are Verilog keywords. chip-AGNOSTIC: markdown table
# grammar + the closed Verilog direction set; no chip/vendor/SKU literal.
_MD_DIRECTIONS = frozenset({"input", "output", "inout"})
_MD_TABLE_ROW_RE = re.compile(r"^[ \t]*\|(.+)\|[ \t]*$", re.MULTILINE)
_MD_NAME_CELL_RE = re.compile(r"^[`*_\s]*([A-Za-z_]\w*)")
_ANY_COLON_PORT_LINE_RE = re.compile(
    r"^[ \t>*#-]*`?\s*([A-Za-z_]\w*)\s*`?\s*(?:\[[^\]]+\]\s*)?[：:]",
    re.MULTILINE)


def _all_port_names_from_port_table(text: str) -> Optional[set]:
    """The COMPLETE lowercased set of top port names from a MARKDOWN PORT TABLE
    — or None when the text carries no such table. A table row counts only when
    some cell is a bare Verilog direction keyword (input/output/inout); the name
    is taken from the FIRST cell with backticks/emphasis and any bus suffix
    (`address[7:0]`) stripped. At least two qualifying rows are required so a
    one-off prose mention can never masquerade as an interface enumeration.
    chip-AGNOSTIC: pure markdown/Verilog grammar, no chip literal."""
    found: set = set()
    for m in _MD_TABLE_ROW_RE.finditer(text):
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 2:
            continue
        if not any(c.strip(" `*_").lower() in _MD_DIRECTIONS for c in cells[1:]):
            continue
        nm = _MD_NAME_CELL_RE.match(cells[0])
        if not nm:
            continue
        bare = nm.group(1).strip().lower()
        # A header row ("| Signal | Dir |") has no direction VALUE cell, so it is
        # already excluded above; guard the direction keyword itself defensively
        # in case a table puts the direction first.
        if bare and bare not in _MD_DIRECTIONS:
            found.add(bare)
    return found if len(found) >= 2 else None


def _all_port_names_from_explicit_sections(text: str) -> Optional[set]:
    """Return a COMPLETE interface from explicit Input/Output ports sections.

    Free-form prose is not authoritative, but a document that labels both its
    input and output sections and enumerates ``name: description`` rows is an
    exact public-interface contract.  Treating that as "loose prose" caused the
    alias pass to append undocumented reset ports after a correct generator had
    already honored the prompt.
    """
    hdrs = list(_CONTRACT_PORTSECTION_HDR_RE.finditer(text))
    if not hdrs:
        return None
    kinds = set()
    found: set = set()
    for k, header in enumerate(hdrs):
        label = header.group(0).lower()
        if "i/o" in label or "inout" in label:
            kinds.update(("input", "output"))
        elif "output" in label or re.search(r"\bout\b", label):
            kinds.add("output")
        else:
            kinds.add("input")
        stop = hdrs[k + 1].start() if k + 1 < len(hdrs) else len(text)
        body = text[header.end():stop]
        blank = re.search(r"\n[ \t]*\n", body)
        if blank:
            body = body[:blank.start()]
        for match in _ANY_COLON_PORT_LINE_RE.finditer(body):
            found.add(match.group(1).lower())
    return found if len(found) >= 2 and kinds == {"input", "output"} else None


def authoritative_contract_ports(project: Path) -> Optional[set]:
    """ORGANIC #186 — the COMPLETE lowercased set of top port names when the
    design contract provides a STRUCTURED, AUTHORITATIVE enumeration of the top
    interface (an L3 external-interface JSON port table, or the L9 integration
    spec top_ports). None when only loose prose / free-text prompts are staged.

    The automatic adapter may use an enumerated target spelling only when the
    source spelling is not required. The enumeration does not assert that two
    listed resets are equivalent or can be combined. None is missing authority,
    not permission to guess a replacement."""
    names: set = set()
    got = False
    seen: set = set()
    for pat in _AUTHORITATIVE_L3_GLOBS + _AUTHORITATIVE_L9_GLOBS:
        for f in sorted(project.glob(pat)):
            rp = f.resolve()
            if rp in seen or not f.is_file():
                continue
            seen.add(rp)
            try:
                data = json.loads(f.read_text(errors="replace"))
            except (OSError, ValueError, TypeError):
                continue
            got_names = _all_port_names_from_l3_json(data)
            if got_names:
                names |= got_names
                got = True
    # ORGANIC #186 r2 — fall back to the AUTHORED L3/L9 document's own port
    # table. Consulted only when no structured JSON enumeration was found, so a
    # project that ships both keeps round-1 behavior byte-for-byte (§4.05
    # no-leak); the markdown table is the authoritative source exactly when the
    # JSON extraction is absent or empty.
    if not got:
        for pat in _AUTHORITATIVE_DOC_GLOBS:
            for f in sorted(project.glob(pat)):
                rp = f.resolve()
                if rp in seen or not f.is_file():
                    continue
                seen.add(rp)
                try:
                    raw = f.read_text(errors="replace")
                except OSError:
                    continue
                got_names = _all_port_names_from_port_table(raw)
                if got_names:
                    names |= got_names
                    got = True
    # A benchmark/free-text prompt is authoritative only when it carries an
    # explicit, complete Input-ports + Output-ports enumeration. Loose prose,
    # one-off `reset` mentions, and incomplete sections remain non-authoritative
    # and do not authorize automatic adaptation.
    if not got:
        for pat in ("input/phase1_prompt.md", "phase1/input_prompt/*",
                    "input/docs/design_description*"):
            for f in sorted(project.glob(pat)):
                rp = f.resolve()
                if rp in seen or not f.is_file():
                    continue
                seen.add(rp)
                try:
                    raw = f.read_text(errors="replace")
                except OSError:
                    continue
                got_names = _all_port_names_from_explicit_sections(raw)
                if got_names:
                    names |= got_names
                    got = True
    return names if got else None


# Word-boundary anchored: matches both spaced and COMPACT Verilog (#517 r3).
# ORGANIC #710 — also consume an OPTIONAL SystemVerilog package-qualified type
# (`pkg::type_t name`) between the net-type block and the port-name capture. A
# comportable/vendor-IP top exposes struct/enum bus ports like
# `input tlul_pkg::tl_h2d_t tl_i`; without the `(?:\w+::\w+\s+)?` arm the greedy
# final `(\w+)` grabbed the package QUALIFIER (`tlul_pkg`) as the port name —
# losing the real ports (tl_i/tl_o/idle_o) and emitting duplicate `tlul_pkg`
# pins. The arm fires ONLY when a literal `::` qualifier is present, so plain /
# ANSI ports (`input wire [7:0] x`, `input logic clk_i`, `inout io_pad`) are
# byte-for-byte unaffected (§4.05 no-leak). chip-AGNOSTIC: pure SV port grammar.
# ORGANIC #792 — the net-type / sign qualifiers that may sit between a port's
# direction keyword and its name. The historical set was just
# `wire|reg|logic|signed|unsigned`; the standard Verilog NET TYPES (`tri`,
# `tri0`, `tri1`, `wand`, `wor`, … — used by the additive dual-spelling reset
# wrapper to give an undriven alias a defined inactive default) were missing, so
# `input tri1 reset_n` parsed the net-type `tri1` AS the port name and dropped
# `reset_n`. Shared single source (Step-2.7 rule 3 — no hand-copied lists) so the
# three port-surface regexes never drift. Longest-first is irrelevant (each is a
# whole-word `\b` alternation) but kept readable.
# ORGANIC #801 (extends #792) — the SystemVerilog INTEGRAL / NUMERIC DATA TYPES
# were still missing from the same alternation. A spec may MANDATE a 2-state
# clock/data port (`Use bit for the clock input` → `input bit clk_in`), and the
# four-state `logic` was the only data type covered. With `bit` absent the final
# `(\w+)` grabbed the DATA TYPE (`bit`) as the port name and dropped the real
# port (`clk_in`) → a downstream latency TB emitted `reg bit;` + `.bit(bit)`
# (reserved SV keyword + non-existent port) → rc=2 compile crash. Same CLASS as
# #792 (a qualifier eaten as the name). Whole-word `\b` alternation →
# order-independent (`int` cannot pre-empt `integer`: the `\b` after a bare `int`
# fails on the `e`, so the engine backtracks to the longer arm). ADDITIVE — these
# are all SV reserved keywords, never legal port names, so a header with no SV
# data-type qualifier is matched byte-for-byte as before (§4.05 no-leak).
_NET_QUAL_RE = (r"(?:(?:wire|reg|logic|signed|unsigned|"
                r"tri|tri0|tri1|triand|trior|trireg|wand|wor|uwire|"
                r"supply0|supply1|"
                r"bit|byte|int|integer|shortint|longint|"
                r"time|real|shortreal|realtime)\b\s*)*")

_PORT_DECL_RE = re.compile(
    r"\b(input|output|inout)\b\s*"
    + _NET_QUAL_RE +
    r"(?:[A-Za-z_]\w*::\s*[A-Za-z_]\w*\s+)?"   # optional pkg::type_t prefix (#710)
    r"(\[[^\]]+\])?\s*(\w+)")


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


# ORGANIC #671 — preprocessor-directive tokens for the port-surface parser.
_PP_DIRECTIVE_RE = re.compile(
    r"^[ \t]*`(ifdef|ifndef|elsif|else|endif|define)\b[ \t]*(\w+)?",
    re.MULTILINE)


def _collect_inline_defines(text: str, base: "Optional[set]" = None) -> set:
    """ORGANIC #671 — the set of macros UNCONDITIONALLY `define-d in `text`
    (those sitting at preprocessor depth 0 — not nested inside an un-taken
    `ifdef arm). Mirrors the way an in-file `` `define X `` that itself sits
    under a gate only becomes visible when that gate is taken. Seeded by the
    compile-time `base` define-set (the -D flags the sv2v / compile uses)."""
    active: set = set(base or set())
    # Walk the directive stream tracking a take/skip stack so a `define inside
    # an un-taken arm does not leak into the active set.
    take_stack: List[bool] = []  # one bool per open `ifdef/`ifndef/`else region

    def _all_taken() -> bool:
        return all(take_stack)

    for m in _PP_DIRECTIVE_RE.finditer(text):
        kind, name = m.group(1), m.group(2)
        if kind == "define":
            if name and _all_taken():
                active.add(name)
        elif kind == "ifdef":
            take_stack.append(_all_taken() and (name in active))
        elif kind == "ifndef":
            take_stack.append(_all_taken() and (name not in active))
        elif kind == "elsif":
            if take_stack:
                # flip: this arm is taken iff no earlier arm in the chain was,
                # the enclosing context is taken, and the macro is defined.
                outer = all(take_stack[:-1]) if len(take_stack) > 1 else True
                take_stack[-1] = outer and (not take_stack[-1]) \
                    and (name in active)
        elif kind == "else":
            if take_stack:
                outer = all(take_stack[:-1]) if len(take_stack) > 1 else True
                take_stack[-1] = outer and (not take_stack[-1])
        elif kind == "endif":
            if take_stack:
                take_stack.pop()
    return active


def _resolve_preprocessor_arms(text: str,
                               defines: "Optional[set]" = None) -> str:
    """ORGANIC #671 — blank out the bodies of NOT-TAKEN `ifdef/`ifndef/`elsif/
    `else arms under the compile-time define-set `defines`, so a downstream
    port-list scan never binds a conditionally-compiled port (e.g. a formal /
    debug interface gated by a define the sv2v/compile set does NOT pass).

    The historical caller passed no define-set, taking EVERY arm — which over-
    counts ports inside never-compiled `ifdef arms and makes the generated TB
    bind pins the DUT does not expose. With `defines` = the SAME define-set the
    in-runner sv2v DUT conversion uses (e.g. {SIMULATION} or {SYNTHESIS}), an
    arm whose gating macro is absent is removed before the port regex runs, so
    the TB↔DUT port surfaces match. Newlines are preserved (bodies blanked, not
    deleted) so byte offsets and line structure are stable.

    chip-AGNOSTIC: pure `ifdef/`define grammar + the abstract compile define-set
    — no chip / vendor / macro-name literal."""
    if "`if" not in text:
        return text  # no conditional compilation — nothing to resolve
    active = _collect_inline_defines(text, defines)
    out: List[str] = []
    # take_stack[i] = is region i currently taken (under the enclosing context)
    take_stack: List[bool] = []
    seen_taken: List[bool] = []  # has ANY arm of this if-chain been taken yet

    def _ctx_taken() -> bool:
        return all(take_stack) if take_stack else True

    for line in text.splitlines(keepends=True):
        m = _PP_DIRECTIVE_RE.match(line)
        kind = m.group(1) if m else None
        name = m.group(2) if m else None
        if kind in ("ifdef", "ifndef"):
            outer = _ctx_taken()
            taken = outer and (
                (name in active) if kind == "ifdef" else (name not in active))
            take_stack.append(taken)
            seen_taken.append(taken)
            out.append(line)  # keep the directive line itself
            continue
        if kind == "elsif":
            if take_stack:
                outer = all(take_stack[:-1]) if len(take_stack) > 1 else True
                taken = outer and (not seen_taken[-1]) and (name in active)
                take_stack[-1] = taken
                seen_taken[-1] = seen_taken[-1] or taken
            out.append(line)
            continue
        if kind == "else":
            if take_stack:
                outer = all(take_stack[:-1]) if len(take_stack) > 1 else True
                taken = outer and (not seen_taken[-1])
                take_stack[-1] = taken
                seen_taken[-1] = seen_taken[-1] or taken
            out.append(line)
            continue
        if kind == "endif":
            if take_stack:
                take_stack.pop()
                seen_taken.pop()
            out.append(line)
            continue
        # ordinary body line: keep only when the enclosing context is taken;
        # else blank it (preserve the trailing newline so line structure holds).
        if _ctx_taken():
            out.append(line)
        else:
            out.append("\n" if line.endswith("\n") else "")
    return "".join(out)


def _module_header(text: str, module: str,
                   defines: "Optional[set]" = None
                   ) -> Optional[Tuple[Optional[str], str, List[str]]]:
    """Return (param_block, port_block, import_clauses) for
    `module <module> [import pkg::*;]* [#(...)] (...)`, SKIPPING/capturing an
    optional `#(parameter ...)` block (balanced-paren + string-literal aware)
    and CAPTURING any `import pkg::*;` clauses that sit between the module name
    and the param/port regions. None if not found. Same parameterized-module
    fix as #517 reopen — a clocked chip-top is often parameterized
    (`module foo #(parameter W=8) (...)`).

    The `import_clauses` list (ORGANIC #656) carries the verbatim
    `import pkg::*;` text the regex loop consumes, so the wrapper emitter can
    RE-EMIT them in the wrapper header — without it the wrapper references
    package-scoped port-width params (e.g. a bus-pkg width localparam) with no
    import in scope → a deterministic SV `use of undeclared identifier` error.

    ORGANIC #671 — when `defines` (the compile-time -D set the sv2v/iverilog
    DUT conversion uses) is supplied, NOT-TAKEN `ifdef/`ifndef/`elsif/`else
    arms are blanked BEFORE the port list is extracted, so a conditionally-
    compiled port (e.g. a formal/debug interface gated by a macro absent from
    the compile set) is never returned as a DUT port. `defines=None` preserves
    the historical take-every-arm behaviour exactly (no regression)."""
    text = _strip_comments(text)
    if defines is not None:
        text = _resolve_preprocessor_arms(text, defines)
    m = re.search(rf"\bmodule\s+{re.escape(module)}\b", text)
    if not m:
        return None
    i, n = m.end(), len(text)

    def _skip_ws(j: int) -> int:
        while j < n and text[j].isspace():
            j += 1
        return j

    def _skip_balanced(j: int) -> Optional[int]:
        # string-literal aware (#517 r3): a '(' inside "..." must not unbalance.
        depth = 0
        while j < n:
            c = text[j]
            if c == '"':
                j += 1
                while j < n and text[j] != '"':
                    if text[j] == "\\":
                        j += 1
                    j += 1
                j += 1
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return None

    i = _skip_ws(i)
    # ORGANIC #637 — consume any `import pkg::*;` clauses between
    # `module <name>` and the `#(...)`/`(...)` regions (the standard SV
    # ordering `module X import a_pkg::*; #(params) (ports);`). Without this
    # the `#`/`(` test below finds `import` and returns None, so the port
    # parser / clock-reset alias emitter see zero ports on any package-
    # importing top (REUSED-IP / IP-integration-wrapper class). Repeatable.
    # ORGANIC #656 — CAPTURE the consumed clauses (verbatim) so the wrapper
    # emitter can re-emit them; package-scoped port-width params only resolve
    # if the import is back in scope on the outer wrapper.
    import_clauses: List[str] = []

    def _consume_imports(k: int) -> int:
        # Consume any number of `import pkg::*;` clauses starting at k,
        # appending each (verbatim) to import_clauses; return the advanced
        # whitespace-skipped offset. #704 — factored out so it can run BOTH
        # before AND after the optional `#(...)` param block: the SV LRM
        # ordering is `module X import...; #(p) (ports);`, but some tops use
        # the reversed `module X #(p) import...; (ports);`. Tolerating both
        # keeps the header scan order-independent across
        # module / imports* / #(...) / imports* / (ports).
        nonlocal_k = k
        while True:
            im2 = re.match(r"import\s+[\w:\*\s,]+;", text[nonlocal_k:])
            if not im2:
                break
            import_clauses.append(im2.group(0).strip())
            nonlocal_k = _skip_ws(nonlocal_k + im2.end())
        return nonlocal_k

    i = _consume_imports(i)
    param_block: Optional[str] = None
    if i < n and text[i] == "#":
        i = _skip_ws(i + 1)
        if i < n and text[i] == "(":
            j = _skip_balanced(i)
            if j is None:
                return None
            param_block = text[i + 1:j - 1].strip()
            i = _skip_ws(j)
    # #704 — a second import-consumption pass for the reversed
    # `#(params) import pkg::*; (ports)` ordering.
    i = _consume_imports(i)
    if i < n and text[i] == "(":
        j = _skip_balanced(i)
        if j is None:
            return None
        return (param_block, text[i + 1:j - 1], import_clauses)
    return None


def _module_portlist_block(text: str, module: str,
                           defines: "Optional[set]" = None) -> Optional[str]:
    hdr = _module_header(text, module, defines)
    return None if hdr is None else hdr[1]


def parse_module_params(rtl_text: str, module: str
                        ) -> Tuple[Optional[str], List[str]]:
    """Return (raw_param_block, [param_names]) for `module <module> #(...)`.
    (None, []) when not parameterized. Mirrors leaf_typo_alias_emit so the
    reset/clock wrapper of a parameterized top forwards its parameters."""
    hdr = _module_header(rtl_text, module)
    if hdr is None or hdr[0] is None:
        return (None, [])
    return (hdr[0], re.findall(r"(\w+)\s*=", hdr[0]))


_LOCALPARAM_STMT_RE = re.compile(r"\blocalparam\b(?P<decl>[^;]*);",
                                 re.IGNORECASE)


def parse_module_localparams(rtl_text: str, module: str
                             ) -> List[Tuple[str, str]]:
    """ORGANIC-20260703 — return [(name, rhs_expr), ...] for every `localparam`
    declared in `module <module>`'s body, in SOURCE order.

    A localparam-derived PORT WIDTH — `output [DWIDTH_ACCUMULATOR-1:0] result`
    where `DWIDTH_ACCUMULATOR = 2*DWIDTH + $clog2(N)` is a body localparam —
    cannot be re-emitted verbatim on the ANSI-header alias wrapper: the wrapper's
    port list would reference an unbound identifier and iverilog ELABs
    `Unable to bind parameter DWIDTH_ACCUMULATOR`. The wrapper HOISTS the
    referenced localparam(s) into its `#(...)` parameter-port list; this parser
    supplies the (name, rhs) pairs for that hoist. chip-AGNOSTIC: pure SV
    localparam grammar; no chip / vendor literal."""
    body = _module_body(rtl_text, module)
    if not body:
        return []
    out: List[Tuple[str, str]] = []
    for m in _LOCALPARAM_STMT_RE.finditer(body):
        for piece in _split_top_level_commas(m.group("decl")):
            piece = piece.strip()
            eq = piece.find("=")
            if eq < 0:
                continue
            lhs, rhs = piece[:eq].strip(), piece[eq + 1:].strip()
            names = re.findall(r"[A-Za-z_]\w*", lhs)   # last ident = the name
            if names and rhs:
                out.append((names[-1], rhs))
    return out


def parse_module_imports(rtl_text: str, module: str) -> List[str]:
    """Return the verbatim `import pkg::*;` clauses (in source order) sitting
    between `module <module>` and its param/port regions; [] when there are
    none (ORGANIC #656). Mirrors parse_module_params so the reset/clock wrapper
    of a package-importing top RE-EMITS the imports its port widths depend on —
    package-scoped width params (e.g. a bus-pkg width localparam) only resolve
    on the outer wrapper if the import is back in scope there."""
    hdr = _module_header(rtl_text, module)
    if hdr is None:
        return []
    return list(hdr[2])


# ORGANIC #704 round-2 — split a port-list block on TOP-LEVEL commas only.
# A comma inside `[..]` (packed/unpacked width), `(..)` (function-call default
# like `$clog2(W)`) or `{..}` (concat) does NOT separate two ports.
def _split_top_level_commas(block: str) -> List[str]:
    parts: List[str] = []
    depth = 0
    buf: List[str] = []
    for ch in block:
        if ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


# A DIRECTIONLESS continuation port inside a comma-bundled group
# (`input clk, rst_n` → the `rst_n` segment carries no direction keyword):
# optional net-type, optional packed width, then the port name.
_CONT_PORT_RE = re.compile(
    r"^" + _NET_QUAL_RE +
    r"(\[[^\]]+\])?\s*(\w+)")


# ORGANIC #766 — NON-ANSI body port declaration:
# `input [3:0] foo, bar;` / `output reg q;` / `inout io_pad;`. The direction
# keyword leads, an optional net-type + optional packed width follow, then a
# comma-separated list of bare port names terminated by `;`. Mirrors the
# field-verified non-ANSI body scan in iface_conformance_v2 `_parse_module_match`
# (_NONANSI_PORT_RE) so the SHARED parser handles the same design class.
# (#766r2) each name may carry trailing UNPACKED-array dimension group(s)
# (`input [7:0] a [3:0];`). The unpacked dims are NOT captured into the bare-name
# list — `_parse_nonansi_body_ports` strips them — but tolerating them here keeps
# the port from being SILENTLY DROPPED (an §4.05 leak: a dropped non-ANSI array
# port floats in the latency TB and bypasses the ANSI path's rc=3 NOT_APPLICABLE
# guard, masking a real defect). The returned port re-enters classification with
# its PACKED width; the unpacked dim is recovered downstream from the RTL text.
_NONANSI_BODY_PORT_RE = re.compile(
    r"\b(input|output|inout)\b\s*"
    + _NET_QUAL_RE +
    r"(\[[^\]]+\])?\s*"
    r"((?:[A-Za-z_]\w*(?:\s*\[[^\]]+\])*\s*,\s*)*"
    r"[A-Za-z_]\w*(?:\s*\[[^\]]+\])*)\s*;")


def _module_body(text: str, module: str,
                 defines: "Optional[set]" = None) -> Optional[str]:
    """Return the BODY of `module <module>` — the text between the `;` that
    terminates the module header (`module <m> [#(...)] (...);`) and the module's
    matching `endmodule`. None when the module / header is not found. Used by the
    non-ANSI fallback in :func:`parse_module_ports` to read the in-body direction
    declarations of a header that lists only bare port names.

    Comment-strip + (optional) preprocessor-arm resolution match the header
    parser exactly so the body scan sees the same source surface the ANSI scan
    did. chip-AGNOSTIC: pure Verilog/SV module-body grammar."""
    text = _strip_comments(text)
    if defines is not None:
        text = _resolve_preprocessor_arms(text, defines)
    m = re.search(rf"\bmodule\s+{re.escape(module)}\b", text)
    if not m:
        return None
    # Find the `;` that ends the module header: the first ';' at paren depth 0
    # after the module name (string-literal aware so a ';' inside "..." in a
    # param default does not terminate the header early).
    i, n = m.end(), len(text)
    depth = 0
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif c == ";" and depth == 0:
            break
        i += 1
    if i >= n:
        return None
    body = text[i + 1:]
    em = re.search(r"\bendmodule\b", body)
    if em:
        body = body[:em.start()]
    return body


def _parse_nonansi_body_ports(body: str,
                              header_names: List[str]
                              ) -> List[Tuple[str, str, str]]:
    """ORGANIC #766 — bind each bare header port name to the direction/width
    declared for it in the module BODY (non-ANSI style). `header_names` is the
    ordered list of bare identifiers from the header port list; `body` is the
    module body. Returns [(dir, width, name), ...] in HEADER ORDER for the names
    that have a body direction declaration. Names with no body declaration are
    dropped (they are not real directioned ports). Mirrors the body scan in
    iface_conformance_v2 `_parse_module_match`."""
    dir_by_name: Dict[str, str] = {}
    width_by_name: Dict[str, str] = {}
    for pm in _NONANSI_BODY_PORT_RE.finditer(body):
        direction = pm.group(1)
        width = (pm.group(2) or "").strip()
        for nm in re.split(r"\s*,\s*", pm.group(3).strip()):
            # (#766r2) strip any trailing UNPACKED-array dimension(s) to recover
            # the bare identifier (`a [3:0]` -> `a`); the unpacked dim is handled
            # downstream by the latency TB builder, never silently dropped here.
            nm = re.split(r"\s*\[", nm.strip(), 1)[0].strip()
            if nm and nm not in dir_by_name:
                dir_by_name[nm] = direction
                width_by_name[nm] = width
    out: List[Tuple[str, str, str]] = []
    for nm in header_names:
        if nm in dir_by_name:
            out.append((dir_by_name[nm], width_by_name[nm], nm))
    return out


def parse_module_ports(rtl_text: str, module: str,
                       defines: "Optional[set]" = None
                       ) -> List[Tuple[str, str, str]]:
    """Parse `module <module>`'s ANSI port list as [(dir, width, name), ...].

    ORGANIC #671 — `defines` is the compile-time -D set the in-runner sv2v /
    iverilog DUT conversion uses (e.g. {"SIMULATION"} or {"SYNTHESIS"}). When
    supplied, a port inside an `ifdef <MACRO> arm whose MACRO is NOT in that set
    is NOT returned (it is not a real DUT port under that conversion). When
    `defines=None` (the legacy default) every arm is parsed exactly as before —
    no regression on callers that don't pass a define-set.

    ORGANIC #704 round-2 — COMMA-BUNDLED DIRECTIONLESS ports are no longer
    dropped. The prior `_PORT_DECL_RE.finditer(block)` only yielded ports that
    LED with a direction keyword, so a Verilog/SV port group that shares one
    direction across a comma list — `input clk, rst_n` / `input [7:0] a, b, c`
    (an extremely common top-level shape) — silently lost every member after the
    first. That made the l9 RTL-top pin checker report the dropped ports as
    "declared in L9 but missing from the RTL top" → a FALSE pin-mismatch FAIL on
    a perfectly valid design. The parser now walks the block by top-level comma
    segments, CARRYING the most-recent direction (and that group's width) onto
    each directionless continuation port — the same carry-forward Verilog ANSI
    semantics the historical l9-local parser implemented before it migrated here.

    Equivalence: for a port list with no comma-bundling (every port leads with
    its own direction) the result is byte-identical to the old finditer output;
    bundling only ADDS the previously-dropped continuation ports. A leading
    directionless token before ANY direction keyword is still skipped (non-ANSI
    header / stray), matching the old behaviour."""
    block = _module_portlist_block(rtl_text, module, defines)
    if block is None:
        return []
    # Strip any preprocessor DIRECTIVE marker lines (``ifdef``/`endif`/`else`/
    # `elsif`/`ifndef`/`define`) that survive inside the block. With `defines`
    # the not-taken ARM bodies are already blanked, but the `ifdef/`endif marker
    # lines themselves remain as inline text — and a comma segment that begins
    # with such a marker would hide the `output`/`input` keyword that follows it
    # (dropping a real direction-led port). The historical finditer scan ignored
    # them implicitly; the segment walk must remove them first. (Removing a
    # marker line never deletes a port — `_PP_DIRECTIVE_RE` only matches a line
    # that LEADS with a backtick directive keyword, never a port declaration.)
    block = _PP_DIRECTIVE_RE.sub("", block)
    out: List[Tuple[str, str, str]] = []
    cur_dir: Optional[str] = None
    cur_width = ""
    header_bare_names: List[str] = []  # #766 — bare names before any direction
    for seg in _split_top_level_commas(block):
        s = seg.strip()
        if not s:
            continue
        dm = _PORT_DECL_RE.match(s)
        if dm is not None:
            # Direction-led declaration — opens/re-opens a comma group and sets
            # the carried direction + width for any continuation ports after it.
            cur_dir = dm.group(1)
            cur_width = (dm.group(2) or "").strip()
            out.append((cur_dir, cur_width, dm.group(3)))
            continue
        if cur_dir is None:
            # Directionless token before ANY direction keyword. In an ANSI
            # header this is a stray; in a NON-ANSI header (`module foo(clk,
            # resetn,...); input clk; ...`) it is a bare port name whose
            # direction lives in the body. Record it for the #766 body-scan
            # fallback below (the ANSI scan still treats it as no port).
            bm = _CONT_PORT_RE.match(s)
            if bm is not None:
                header_bare_names.append(bm.group(2))
            continue  # directionless token before any direction → not an ANSI port
        cm = _CONT_PORT_RE.match(s)
        if cm is not None:
            w = (cm.group(1) or "").strip() or cur_width
            out.append((cur_dir, w, cm.group(2)))
    # ORGANIC #766 — NON-ANSI fallback. When the header carried ONLY bare port
    # names (no direction keyword anywhere in the port list, so the ANSI scan
    # found zero ports), the directions live in the module BODY. Scan the body
    # for `input|output|inout [w] name1, name2;` declarations and bind each bare
    # header name to its body direction/width — mirroring the field-verified
    # non-ANSI body scan in iface_conformance_v2 `_parse_module_match`. This is
    # ADDITIVE: it fires only when the ANSI scan produced no ports AND the header
    # had bare names, so every ANSI / comma-bundled header is byte-for-byte
    # unaffected (§4.05 no-leak). A name with no body direction is dropped, so a
    # bare non-port token never becomes a phantom port.
    if not out and header_bare_names:
        body = _module_body(rtl_text, module, defines)
        if body:
            out = _parse_nonansi_body_ports(body, header_bare_names)
    return out


def emit_variant_alias_wrapper(core_module: str,
                               ports: List[Tuple[str, str, str]],
                               rename_map: Dict[str, str],
                               wrapper_name: Optional[str] = None,
                               param_block: Optional[str] = None,
                               param_names: Optional[List[str]] = None,
                               import_block: Optional[List[str]] = None,
                               additive_reset_map: "Optional[Dict[str, str]]"
                               = None,
                               localparam_defs: "Optional[List[Tuple[str, str]]]"
                               = None) -> str:
    """Render a wrapper that exposes each renamed reset/clock port under its
    TB-facing variant name and wires it 1:1 to the core's original port; all
    other ports pass straight through. RAISES ValueError on a cross-polarity
    (or reset↔clock) rename — polarity is never crossed.

    When the core is PARAMETERIZED, the wrapper inherits the same `#(...)` block
    and forwards every parameter to the instance, so a parameterized clocked top
    elaborates (its `[W-1:0]` reset/clock-adjacent port widths resolve).

    When the core IMPORTS PACKAGES (ORGANIC #656), `import_block` carries the
    `import pkg::*;` clauses the parser consumed; they are re-emitted in the
    wrapper header (immediately after `module <wrapper>`, before the param
    header and the port list) so package-scoped port-width identifiers —
    e.g. a bus-pkg width localparam used as `[PKG_WIDTH-1:0]` in the inherited
    port decls — resolve on the outer wrapper instead of erroring as
    `use of undeclared identifier`. None/[] re-emits no import line.

    Explicit dual-spelling RESET compatibility: `additive_reset_map` maps a core
    reset to an intentionally requested equivalent input name. The caller must
    authorize the combined-reset semantics; names alone are insufficient.
    The automatic flow does not infer this map. For each such
    reset the wrapper exposes BOTH spellings as input ports and combines them
    POLARITY-SAFELY into the core's single reset port:
      * active-low : `tri1` pull (undriven alias → 1 = deasserted), AND-combine
      * active-high: `tri0` pull (undriven alias → 0 = deasserted), OR-combine
    so whichever spelling the TB binds drives the reset and the OTHER (undriven)
    alias defaults INACTIVE — never floating to `x`. REVISED per #115: the
    `tri0`/`tri1` pull no longer sits on the PORT faces — stock iverilog 11
    coerces a tri-typed input port to inout and rejects a reg-driven TB
    ("Unable to assign to unresolved wires"), breaking the DRIVEN spelling.
    Both faces are PLAIN inputs; the pull lives on INTERNAL `tri0`/`tri1` nets
    (an undriven face floats `z`, the continuous assign transfers it, the pull
    resolves it INACTIVE — IEEE 1364, honored by iverilog 11/12/14). Only
    VERILATOR keeps the pull on the port (`` `ifdef VERILATOR ``): it ties an
    unbound plain input to 0, never `z`, so an internal pull cannot fire there,
    while it accepts reg-driven tri ports. Yosys sees plain inputs + the plain
    combine. The `_NET_QUAL_RE` port parser skips the net-type, and the port
    NAME appears only once per declaration (the directive wraps only the
    qualifier token) so a take-every-arm parse never doubles the port.
    Disclosed limitation: under event-driven simulators an UNDRIVEN face now
    reads `z` when observed directly (hierarchically / in a VCD) — the pulled
    INACTIVE value lives on the internal `__rcvar_pull` net. Callers must account
    for this distinction when observing or driving an intentionally added port.
    Disjoint from `rename_map`."""
    additive = dict(additive_reset_map or {})
    for orig, new in list(rename_map.items()) + list(additive.items()):
        if not _same_class(orig, new):
            raise ValueError(
                f"refusing cross-polarity/role reset-clock alias "
                f"{orig!r} -> {new!r}: "
                f"{orig}={classify_reset(orig) or ('clock' if is_clock(orig) else '?')}, "
                f"{new}={classify_reset(new) or ('clock' if is_clock(new) else '?')}")
    for orig in additive:
        if classify_reset(orig) is None:
            raise ValueError(
                f"refusing additive dual-spelling alias on a NON-reset port "
                f"{orig!r}: the inactive-default pull is only polarity-safe for "
                f"resets (a clock has no inactive level).")
        if orig in rename_map:
            raise ValueError(
                f"port {orig!r} is in BOTH rename_map and additive_reset_map — "
                f"the additive (dual-port) and rename (1:1) paths are disjoint.")
    wrapper_name = wrapper_name or f"{core_module}_aliased"
    # Defensive duplicate-face guard (#518): the TB-facing port names must be
    # UNIQUE — a rename that collapses two ports onto one name (or an additive
    # canonical that collides with an existing port) would emit invalid Verilog
    # (`input rst_n, input rst_n`). plan_aliases already prevents this; reject any
    # hand-built map that doesn't.
    faces: List[str] = []
    for _d, _w, name in ports:
        if name in additive:
            faces.extend((name, additive[name]))   # both spellings are faces
        else:
            faces.append(rename_map.get(name, name))
    dupes = sorted({f for f in faces if faces.count(f) > 1})
    if dupes:
        raise ValueError(
            f"refusing reset/clock alias that produces duplicate wrapper "
            f"port name(s) {dupes}: a rename collapsed two ports onto one name.")
    # ORGANIC-20260703 — hoist inner LOCALPARAMS referenced by a port width into
    # the wrapper's parameter-port list. An ANSI-header wrapper re-emits each
    # port width verbatim; when a width is a FUNCTION of the inner module's
    # localparam (`output [DWIDTH_ACCUMULATOR-1:0] result`,
    # DWIDTH_ACCUMULATOR = 2*DWIDTH + $clog2(N)), the wrapper header references
    # an unbound identifier and iverilog ELABs `Unable to bind parameter
    # DWIDTH_ACCUMULATOR`. Re-declare the needed localparam(s) in the wrapper's
    # `#(...)` — AFTER the forwarded parameters they depend on, as `localparam`
    # (not overridable, and NOT forwarded to the inner, which keeps its own) —
    # so the width resolves on the wrapper too. Transitive over localparam refs.
    hoist_lines: List[str] = []
    if localparam_defs:
        lp_map: Dict[str, str] = {}
        lp_order: List[str] = []
        for _n, _rhs in localparam_defs:
            if _n not in lp_map:
                lp_order.append(_n)
            lp_map[_n] = _rhs
        param_set = set(param_names or [])
        width_ids: set = set()
        for _d, _w, _nm in ports:
            width_ids.update(re.findall(r"[A-Za-z_]\w*", _w or ""))
        needed: set = set()
        stack = [i for i in width_ids if i in lp_map and i not in param_set]
        while stack:
            nm = stack.pop()
            if nm in needed:
                continue
            needed.add(nm)
            for ref in re.findall(r"[A-Za-z_]\w*", lp_map[nm]):
                if ref in lp_map and ref not in param_set and ref not in needed:
                    stack.append(ref)
        hoist_lines = [f"localparam {nm} = {lp_map[nm]}"
                       for nm in lp_order if nm in needed]

    param_hdr = ""
    inst_params = ""
    if param_block and not hoist_lines:
        param_hdr = f" #(\n    {param_block}\n)"           # unchanged path
        if param_names:
            inst_params = " #(" + ", ".join(
                f".{p}({p})" for p in param_names) + ")"
    elif param_block or hoist_lines:
        _items: List[str] = []
        if param_block:
            _items.append(re.sub(r",\s*$", "", param_block.strip()))
        _items.extend(hoist_lines)
        param_hdr = " #(\n    " + ",\n    ".join(_items) + "\n)"
        if param_names:
            inst_params = " #(" + ", ".join(
                f".{p}({p})" for p in param_names) + ")"
    # ORGANIC #656 — re-emit the consumed `import pkg::*;` clauses on the
    # wrapper header so package-scoped port-width params resolve. Rendered
    # right after `module <wrapper>` and before `#(...)` / the port list,
    # matching the standard SV ordering `module X import pkg::*; #(p) (ports);`.
    import_hdr = ""
    if import_block:
        import_hdr = "\n  " + "\n  ".join(c.strip() for c in import_block)
    decls, conns, combine_wires = [], [], []
    for direction, width, name in ports:
        w = f" {width}" if width else ""
        if name in additive:
            canon = additive[name]
            pol = classify_reset(name)
            tri = "tri1" if pol == "active_low" else "tri0"
            op = "&" if pol == "active_low" else "|"
            net = f"{name}__rcvar_net"
            # Dual-spelling additive reset (#792), REVISED (#115): the tri0/tri1
            # net-type must NOT sit on the port faces for event-driven
            # simulators — stock iverilog 11 coerces a tri-typed input port to
            # inout and then rejects any TB that procedurally drives it with a
            # reg ("Unable to assign to unresolved wires"), which broke the
            # DRIVEN spelling outright (RTLLM up_down_counter /
            # sequence_detector / synchronizer under iverilog 11). Both faces
            # are therefore PLAIN inputs; the inactive-default pull moves to
            # INTERNAL tri0/tri1 nets: an undriven face floats z, the
            # continuous assign transfers the z, and the pull resolves it
            # INACTIVE (IEEE 1364 net resolution — verified on iverilog
            # 11/12/14). VERILATOR alone keeps the pull on the PORT (`ifdef
            # VERILATOR`): it ties an unbound plain input to 0 (never z) so an
            # internal pull cannot fire there, while it accepts reg-driven tri
            # ports without iverilog's coercion error; its combine stays
            # port-direct. Yosys sees plain inputs + the plain combine
            # (unchanged). The port NAME still appears ONCE per decl (the
            # directive wraps only the tri token) so a take-every-arm parse
            # never doubles the port.
            # net-type BEFORE the range (`input tri0 [0:0] r` is the legal
            # order; `input [0:0] tri0 r` is a syntax error — an inherited
            # ordering bug from the old emission, now fixed)
            for face in (name, canon):
                decls.append(
                    f"    {direction}\n`ifdef VERILATOR\n    {tri}\n`endif\n"
                    f"   {w} {face}" if w else
                    f"    {direction}\n`ifdef VERILATOR\n    {tri}\n`endif\n"
                    f"    {face}")
            combine_wires.append(
                f"`ifdef VERILATOR\n"
                f"    wire {net} = {name} {op} {canon};\n"
                f"`elsif YOSYS\n"
                f"    wire {net} = {name} {op} {canon};\n"
                f"`else\n"
                f"    {tri}{w} {name}__rcvar_pull;\n"
                f"    {tri}{w} {canon}__rcvar_pull;\n"
                f"    assign {name}__rcvar_pull = {name};\n"
                f"    assign {canon}__rcvar_pull = {canon};\n"
                f"    wire {net} = {name}__rcvar_pull {op} {canon}__rcvar_pull;\n"
                f"`endif")
            conns.append(f"        .{name}({net})")
        else:
            face = rename_map.get(name, name)
            decls.append(f"    {direction}{w} {face}")
            conns.append(f"        .{name}({face})")
    lines = [
        f"// {wrapper_name} — reset/clock NAME-VARIANT alias wrapper for "
        f"`{core_module}`",
        "// Exposes explicitly requested equivalent reset/clock port names.",
        "// The caller owns the public-interface and compatibility contract.",
        "// Polarity is preserved 1:1. Generated by reset_clock_variant_alias.py"
        " (#518/#792).",
        f"module {wrapper_name}{import_hdr}{param_hdr} (",
        ",\n".join(decls),
        ");",
        *combine_wires,
        f"    {core_module}{inst_params} u_{core_module} (",
        ",\n".join(conns),
        "    );",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


def _module_port_list_span(text: str, module_name: str):
    """Return (open_idx, close_idx) of the ANSI port-list parens of `module
    <module_name>` — the `(` after the (optional) `#(...)` param header through
    its balanced `)`. Returns None if the header is not a plain ANSI form we can
    edit safely (non-ANSI / port list in the body / unbalanced)."""
    m = re.search(rf"\bmodule\s+{re.escape(module_name)}\b", text)
    if not m:
        return None
    i = m.end()
    n = len(text)
    # skip a leading `import ...;` and a `#( ... )` param header (balanced)
    while i < n:
        while i < n and text[i] in " \t\r\n":
            i += 1
        if text.startswith("import", i):                # import pkg::*;
            semi = text.find(";", i)
            if semi == -1:
                return None
            i = semi + 1
            continue
        if i < n and text[i] == "#":
            i += 1
            while i < n and text[i] in " \t\r\n":
                i += 1
            if i >= n or text[i] != "(":
                return None
            depth = 0
            while i < n:
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            continue
        break
    while i < n and text[i] in " \t\r\n":
        i += 1
    if i >= n or text[i] != "(":                        # non-ANSI (no port parens)
        return None
    open_idx = i
    depth = 0
    while i < n:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return (open_idx, i)
        i += 1
    return None


def emit_variant_alias_flat(text: str, module_name: str,
                            rename_map: Dict[str, str]) -> Optional[str]:
    """FLAT alternative to `emit_variant_alias_wrapper`: instead of renaming the
    core to `<name>__rcvar_inner` and adding a wrapper that instantiates it, edit
    the module IN PLACE — rename each reset/clock port to its canonical spelling
    in the module's OWN ANSI header and add a 1-bit internal alias
    `wire <orig> = <canon>;` so the unchanged body still resolves. The result is a
    SINGLE FLAT module under the original name, so a whitebox testbench that binds
    the design's own internal signals hierarchically (`dut.<internal>`) still sees
    them — the two-level wrapper hid them one instance down (ORGANIC-20260704).

    Only the PURE-RENAME case is handled (reset/clock ports are 1-bit inputs and
    the rename is ALWAYS same-polarity — cross-polarity RAISES, exactly like the
    wrapper). Returns the transformed text, or None if it cannot apply safely
    (non-ANSI header, a port name not found uniquely in the header, additive
    dual-spelling) — the caller then falls back to the wrapper path. §4.05-safe:
    operates only on the design's own RTL text."""
    if not rename_map:
        return None
    for orig, new in rename_map.items():
        if not _same_class(orig, new):
            raise ValueError(
                f"refusing cross-polarity/role reset-clock alias {orig!r} -> {new!r}")
    span = _module_port_list_span(text, module_name)
    if span is None:
        return None
    open_idx, close_idx = span
    header = text[open_idx:close_idx + 1]
    new_header = header
    for orig, canon in rename_map.items():
        # The port NAME must appear exactly once as a declared identifier in the
        # ANSI port list. Rename that single whole-word occurrence to canonical;
        # bail (→ wrapper fallback) on 0 or >1 matches so we never mis-edit.
        pat = re.compile(rf"(?<![\w.]){re.escape(orig)}(?![\w])")
        hits = pat.findall(new_header)
        if len(hits) != 1:
            return None
        new_header = pat.sub(canon, new_header)
    # Inject the 1-bit internal aliases right after the port-list `)` (and any
    # trailing `;`). Body references to <orig> now resolve to `wire <orig>=<canon>`.
    after = close_idx + 1
    tail = text[after:]
    msemi = re.match(r"\s*;", tail)
    insert_at = after + msemi.end() if msemi else after
    aliases = "".join(
        f"\n  wire {orig} = {canon};  // rcvar flat alias (#rcvar-whitebox)"
        for orig, canon in rename_map.items())
    return (text[:open_idx] + new_header + text[after:insert_at]
            + aliases + text[insert_at:])


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit an explicitly requested reset/clock alias wrapper "
                    "with polarity preserved; no speculative port names.")
    ap.add_argument("--rtl", required=True, help="RTL file with the core module")
    ap.add_argument("--module", required=True, help="core (chip-top) module name")
    ap.add_argument("--out", default=None, help="wrapper output path")
    ap.add_argument("--alias", action="append", default=[],
                    metavar="SOURCE=TARGET",
                    help="explicit requested rename; required for mutation; repeatable")
    args = ap.parse_args(argv)
    rtl = Path(args.rtl)
    if not rtl.is_file():
        print(f"error: rtl not found: {rtl}", file=sys.stderr)
        return 2
    ports = parse_module_ports(rtl.read_text(errors="replace"), args.module)
    if not ports:
        print(f"error: module {args.module!r} not found / no ANSI ports.",
              file=sys.stderr)
        return 1
    if not args.alias:
        if not plan_aliases([p[2] for p in ports]):
            print("skip: reset/clock ports already canonical; no alias requested")
            return 0
        ap.error("--alias SOURCE=TARGET is required to change public port names")
    plan: Dict[str, str] = {}
    inputs = {name for direction, _, name in ports if direction == "input"}
    for requested in args.alias:
        match = re.fullmatch(r"([A-Za-z_]\w*)=([A-Za-z_]\w*)", requested)
        if not match:
            ap.error(f"invalid alias {requested!r}; expected SOURCE=TARGET")
        source, destination = match.groups()
        if source not in inputs or source in plan:
            ap.error(f"alias source {source!r} must be a unique existing input")
        plan[source] = destination
    try:
        wrapper = emit_variant_alias_wrapper(args.module, ports, plan)
    except ValueError as exc:
        ap.error(str(exc))
    out = Path(args.out) if args.out else rtl.with_name(f"{args.module}_aliased.v")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(wrapper)
    print(f"ok: wrote {out} (aliases={plan})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
