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


def _has_reset(text: str) -> bool:
    return bool(re.search(r"\breset\b|\brst\b|\bpor\b", text, re.I))


def _detect_latency(text: str) -> Optional[str]:
    """Return a human latency phrase if the spec states one, else None."""
    if _SRC._detect_latency(text):
        return "registered / single-cycle latency"
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
_WORKED_EXAMPLE_RE = re.compile(
    r"(0[xXbB][0-9A-Fa-f_]+|\d+)\s*(?:->|→|=>|=)\s*(0[xXbB][0-9A-Fa-f_]+|\d+)")

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
            coverage_tokens=["latency", "cycle", "@(posedge", "@(negedge",
                             "#", "posedge", "negedge"]))

    # --- Enumerated set(s) + the outside-the-set / default boundary ---
    for m in _ENUM_SET_RE.finditer(spec_text):
        members = _split_enum_members(m.group(1))
        if len(members) < 2:
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
        key = (m.group(1), m.group(2))
        if key in seen_examples:
            continue
        seen_examples.add(key)
        items.append(ChecklistItem(
            kind="worked_example",
            requirement=f"worked example: {m.group(1)} -> {m.group(2)}",
            evidence=m.group(0),
            coverage_tokens=[m.group(1), m.group(2)]))

    # --- Signed-ness / byte order / overflow / handshake (structural facts) ---
    for rx, kind, label in (
        (_SIGNED_RE, "signedness", "signed-ness"),
        (_BYTEORDER_RE, "byte_order", "bit/byte order & packing"),
        (_OVERFLOW_RE, "overflow", "overflow / saturation / rounding"),
        (_HANDSHAKE_RE, "handshake", "handshake / protocol timing"),
    ):
        mm = rx.search(spec_text)
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
            outside = tb_values_norm - members_norm if members_norm else set()
            it.covered = bool(outside)
            it.coverage_note = (
                f"TB stimulates outside-the-set value(s) {sorted(outside)}"
                if outside else
                "TB only stimulates listed members; no outside-the-set value")
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

    enum_members_all: List[str] = []
    for it in items:
        if it.kind == "enum_set":
            enum_members_all += it.coverage_tokens

    attribute_coverage(items, tb_text, enum_members_all)

    gaps = [it for it in items if it.covered is False]
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

    # block decision: only TESTBENCH-COVERAGE GAPs gate (and only in --strict)
    report["pass"] = (len(gaps) == 0)
    report["strict"] = strict
    report["blocked"] = bool(strict and gaps)
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
