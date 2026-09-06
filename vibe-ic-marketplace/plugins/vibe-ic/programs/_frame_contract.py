#!/usr/bin/env python3
"""_frame_contract.py — typed FRAME-CONTRACT extraction from the design INPUT.

Shared, program-first extraction library for the framed-serial-receiver defect
class of vibe-ic#2035 family F4:

    "Framed serial receiver forwards raw fields, adds latency or ignores
     inter-frame space"

Three DISTINCT defects are packed into that one sentence and this module keeps
them distinct, because a reader cannot act on a single boolean:

  1. MAPPING     — the receiver forwards the raw field instead of applying the
                   decode/remap table the input declares.
  2. LATENCY     — the output appears later than the contract states.
  3. INTER-FRAME — the gap BETWEEN frames is part of the protocol and is not
                   enforced, so back-to-back frames are accepted.

(2) and (3) are two constraints on the SAME time axis. A checker that only ever
tests one of them at a time passes a design that violates their combination, so
the extractor returns them in one `FrameContract` and the consumer reports them
COMPOSED — see `FrameContract.composition_line()`.

THE UNIT IS NEVER DEFAULTED. A temporal claim needs three things from the input:
a UNIT (clock cycles? bit periods? symbol times?), a BOUND (exactly / at-least /
at-most, plus a value), and the EVENT PAIR the bound is between. Any element the
input does not structurally state is recorded in `TemporalBound.missing` and the
consumer must route it to AI BY NAME. Assuming "cycles" because the input did not
say is exactly the failure this issue is about, relocated to a new place.

Cross-unit comparison is likewise REFUSED, not guessed: a latency stated in bit
periods or symbol times cannot be compared against a register-stage count unless
the input also states the oversampling ratio. `TemporalBound.comparable_to_cycles`
is True only for `unit == 'cycle'`.

This module reads the design INPUT only (§4.05): prompt / L-doc prose and the
prose-bearing fields of a JSON contract. It never reads a golden output, a
reference flow or a published result.

chip-AGNOSTIC: every pattern here is English protocol vocabulary plus Verilog
literal syntax. No IC name, vendor, process node, SKU or benchmark identifier.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "FieldMapping", "TemporalBound", "FrameContract",
    "extract_frame_contract", "input_prose_from_json", "parse_int_literal",
    "literal_forms",
]

# ---------------------------------------------------------------------------
# literals
# ---------------------------------------------------------------------------

#: A Verilog sized literal (`3'b010`, `4'hA`, `8'd12`), a C hex (`0x1f`) or a
#: bare decimal. Kept deliberately narrow: a bare decimal is only accepted as a
#: TABLE cell, never harvested from free prose.
_SIZED_RE = re.compile(r"(?:(\d+)\s*)?'\s*([bBoOdDhH])\s*([0-9a-fA-FxXzZ_]+)")
_HEX0X_RE = re.compile(r"0[xX]([0-9a-fA-F_]+)")
_DEC_RE = re.compile(r"\d+")

_RADIX = {"b": 2, "o": 8, "d": 10, "h": 16}

_NUM_WORD = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def parse_int_literal(tok: str) -> Optional[int]:
    """Parse one literal token to an int, or None when it is not a literal or
    carries x/z (an unknown is not a value a table can be checked against)."""
    tok = tok.strip()
    m = _SIZED_RE.fullmatch(tok)
    if m:
        digits = m.group(3).replace("_", "")
        if re.search(r"[xXzZ]", digits):
            return None
        try:
            return int(digits, _RADIX[m.group(2).lower()])
        except ValueError:
            return None
    m = _HEX0X_RE.fullmatch(tok)
    if m:
        try:
            return int(m.group(1).replace("_", ""), 16)
        except ValueError:
            return None
    if _DEC_RE.fullmatch(tok):
        return int(tok)
    # a bare binary/hex string in a markdown cell: `000`, `1A` are ambiguous, so
    # only an all-binary-digit token of length >= 2 is accepted, as binary.
    if re.fullmatch(r"[01]{2,}", tok):
        return int(tok, 2)
    return None


def literal_forms(value: int) -> List[str]:
    """Every textual form `value` can plausibly take in Verilog source.

    Used to answer "does this RTL contain this constant at all?" — a membership
    question, deliberately generous, because the consumer only ever uses a HIT
    to STAY SILENT. Being generous here can only ever suppress a finding, never
    manufacture one."""
    out = [str(value), f"'d{value}", f"'h{value:x}", f"'h{value:X}",
           f"'b{value:b}", f"'o{value:o}", f"0x{value:x}", f"0x{value:X}"]
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
# mapping
# ---------------------------------------------------------------------------

@dataclass
class FieldMapping:
    """A declared decode / remap / encoding table from a source field to a
    destination signal."""
    entries: List[Tuple[int, int]]           # (input value, output value)
    dst: Optional[str] = None                # destination signal, when resolved
    src: Optional[str] = None                # source field, when resolved
    missing: List[str] = field(default_factory=list)
    raw: str = ""

    @property
    def discriminating(self) -> List[Tuple[int, int]]:
        """Rows where the output DIFFERS from the input. A row that maps a value
        to itself cannot distinguish "table applied" from "field forwarded", so
        it is not evidence either way."""
        return [(a, b) for a, b in self.entries if a != b]

    @property
    def evidencable_outputs(self) -> List[int]:
        """Discriminating output values that a source scan can actually evidence.

        0 and 1 are excluded: they occur in essentially every RTL body (reset
        values, single-bit constants), so finding one proves nothing and NOT
        finding one is not achievable. Excluding them makes the absence test
        falsifiable instead of decorative."""
        return sorted({b for _, b in self.discriminating if b not in (0, 1)})


#: "... maps to ...", "... is decoded as ...", "the following encoding"
_MAP_INTRO_RE = re.compile(
    r"\b(?:maps?\s+to|mapped\s+to|mapping|decoded?\s+(?:as|to|into)|"
    r"decoding|encoded?\s+(?:as|to|into)|encoding|translat(?:es?|ed|ion)\s+"
    r"(?:to|into)?|look\s?-?up\s+table|remaps?\s+to|substitut(?:es?|ed|ion))\b",
    re.IGNORECASE)

#: one arrow row: `3'b000 -> 4'h1`, `000 => 1`, `3'b001 : 4'h2`
_ARROW_ROW_RE = re.compile(
    r"^[\s|*\-]*(?P<a>[0-9a-fA-FxXzZ_']+(?:\s*'\s*[bodhBODH]\s*[0-9a-fA-FxXzZ_]+)?)"
    r"\s*(?:->|=>|-->|==>|→|:|maps?\s+to)\s*"
    r"(?P<b>[0-9a-fA-FxXzZ_']+(?:\s*'\s*[bodhBODH]\s*[0-9a-fA-FxXzZ_]+)?)"
    r"\s*[|\s]*(?:#.*)?$")

#: one markdown table row with exactly two value cells
_MD_ROW_RE = re.compile(r"^\s*\|([^|]+)\|([^|]+)\|\s*$")


def _table_rows(text: str) -> List[Tuple[int, int, str]]:
    """Every (in, out, raw-line) row of a two-column value table in `text`."""
    rows: List[Tuple[int, int, str]] = []
    for line in text.splitlines():
        m = _ARROW_ROW_RE.match(line)
        if not m:
            m2 = _MD_ROW_RE.match(line)
            if not m2:
                continue
            a_tok, b_tok = m2.group(1).strip(), m2.group(2).strip()
        else:
            a_tok, b_tok = m.group("a").strip(), m.group("b").strip()
        a_tok = a_tok.strip("`* ")
        b_tok = b_tok.strip("`* ")
        a, b = parse_int_literal(a_tok), parse_int_literal(b_tok)
        if a is None or b is None:
            continue
        rows.append((a, b, line.strip()))
    return rows


def _resolve_endpoints(text: str, first_row_pos: int,
                       inputs: Sequence[str],
                       outputs: Sequence[str]) -> Tuple[Optional[str],
                                                        Optional[str]]:
    """Resolve (src, dst) from the prose introducing the table.

    dst must be a declared OUTPUT named in the introduction; src is any other
    identifier named there (it is frequently a FIELD of the frame, not a port,
    so it is not required to be an input)."""
    pre = text[max(0, first_row_pos - 400):first_row_pos]
    toks = re.findall(r"`([A-Za-z_]\w*)`|\b([A-Za-z_]\w*)\b", pre)
    names = [a or b for a, b in toks]
    outs = [n for n in names if n in set(outputs)]
    dst = outs[-1] if outs else None
    # The SOURCE is reporting-only: the RTL half of the mapping rule is
    # destination-centric, so a source the prose names only in words ("the type
    # field") must not be back-filled from a nearby port. Confine the search to
    # the sentence that introduces the table and accept only a BACKTICKED name:
    # a prose author who means a signal writes it as one, and back-filling the
    # nearest declared port instead reports a source the input never named.
    sent = re.split(r"(?<=[.;!?])\s+", pre)[-1] if pre else ""
    src = None
    for m in re.finditer(r"`([A-Za-z_]\w*)`", sent):
        if m.group(1) != dst:
            src = m.group(1)
    return src, dst


def extract_field_mapping(text: str, inputs: Sequence[str],
                          outputs: Sequence[str]) -> Optional[FieldMapping]:
    """Extract the declared field-mapping table, or None when the input states
    none.

    Requires ALL of: a mapping-intent phrase, >= 2 table rows, >= 2 distinct
    output values, and >= 1 discriminating row. A one-row table, a table whose
    outputs are all the same value, and a pure identity table are each unable to
    tell "applied the table" from "forwarded the field", so none of them is a
    contract this module will report."""
    intro = _MAP_INTRO_RE.search(text)
    if not intro:
        return None
    rows = _table_rows(text[intro.end():])
    if len(rows) < 2:
        return None
    entries = [(a, b) for a, b, _ in rows]
    if len({b for _, b in entries}) < 2:
        return None
    fm = FieldMapping(entries=entries, raw="\n".join(r[2] for r in rows[:8]))
    if not fm.discriminating:
        return None
    first_row_pos = intro.end() + text[intro.end():].find(rows[0][2])
    fm.src, fm.dst = _resolve_endpoints(text, max(first_row_pos, 0),
                                        inputs, outputs)
    if fm.dst is None:
        fm.missing.append("destination signal not named beside the table")
    if not fm.evidencable_outputs:
        fm.missing.append(
            "every mapped output value is 0 or 1, which no source scan can "
            "evidence either way")
    return fm


# ---------------------------------------------------------------------------
# temporal
# ---------------------------------------------------------------------------

@dataclass
class TemporalBound:
    """One bound on the time axis, with its three mandatory elements kept
    separate so an absent one is reported and never invented."""
    kind: str                       # 'latency' | 'interframe'
    unit: Optional[str] = None      # 'cycle' | 'bit_period' | 'symbol_time'
    bound: Optional[str] = None     # 'exactly' | 'at_least' | 'at_most'
    value: Optional[int] = None
    event_from: Optional[str] = None
    event_to: Optional[str] = None
    missing: List[str] = field(default_factory=list)
    raw: str = ""

    @property
    def comparable_to_cycles(self) -> bool:
        """A bound may be compared against a register-stage count ONLY when the
        input stated its unit AND that unit is the clock cycle. Bit periods and
        symbol times need an oversampling ratio the input has not stated; a
        comparison across them would be a guess wearing a number."""
        return self.unit == "cycle" and self.value is not None


_UNIT_RE = re.compile(
    r"\b(?P<clk>clock\s+cycles?|clk\s+cycles?|cycles?)\b"
    r"|\b(?P<bit>bit\s+(?:periods?|times?|intervals?)|bit-?times?)\b"
    r"|\b(?P<sym>symbol\s+(?:times?|periods?|intervals?)|baud\s+periods?)\b",
    re.IGNORECASE)

_BOUND_AT_LEAST_RE = re.compile(
    r"\b(?:at\s+least|no\s+fewer\s+than|not\s+less\s+than|minimum\s+of|"
    r"a\s+minimum|>=)\b", re.IGNORECASE)
_BOUND_AT_MOST_RE = re.compile(
    r"\b(?:at\s+most|no\s+more\s+than|no\s+later\s+than|within|"
    r"maximum\s+of|not\s+more\s+than|<=)\b", re.IGNORECASE)
_BOUND_EXACT_RE = re.compile(
    r"\b(?:exactly|precisely|in\s+the\s+same)\b", re.IGNORECASE)

_SAME_CYCLE_RE = re.compile(
    r"\bin\s+the\s+same\s+(?:clock\s+)?cycle\b", re.IGNORECASE)

_LATENCY_CUE_RE = re.compile(
    r"\b(?:latency|cycles?\s+(?:after|later)|after\s+the|"
    r"in\s+the\s+same\s+(?:clock\s+)?cycle|valid|available|presented|"
    r"asserted|appears?)\b", re.IGNORECASE)

_INTERFRAME_CUE_RE = re.compile(
    r"\b(?:inter-?\s?frame|between\s+(?:two\s+)?(?:consecutive\s+)?frames|"
    r"between\s+frames|frame\s+gap|gap\s+between|idle\s+(?:gap|period|time|"
    r"space)|separated\s+by|back-?to-?back\s+frames)\b", re.IGNORECASE)


_QUANTITY_RE = re.compile(
    r"\b\d+\b|\b(?:" + "|".join(_NUM_WORD) + r")\b", re.IGNORECASE)


def _states_a_bound(sentence: str) -> bool:
    """True iff the sentence actually EXPRESSES a bound, not merely mentions the
    subject.

    Measured over 4171 corpus documents on this base: keying only on the
    inter-frame VOCABULARY armed 68 documents, and the sentences were things
    like "transactions with request and response separated by time" and
    "/I1/ and /I2/ keep the link alive between frames" — prose that states no
    checkable quantity at all. Arming there produces an AI_REQUIRED line that is
    pure noise in a gate report. A bound needs a comparator phrase (or an
    exactness phrase) AND a quantity; the MIL-STD-1553 clause "a minimum of a
    4 us gap between messages" passes both and is correctly kept, then correctly
    refused later for stating a unit no register count can be compared to."""
    return bool(
        (_BOUND_AT_LEAST_RE.search(sentence) or _BOUND_AT_MOST_RE.search(sentence)
         or _BOUND_EXACT_RE.search(sentence))
        and _QUANTITY_RE.search(sentence))


def _unit_of(sentence: str) -> Optional[str]:
    m = _UNIT_RE.search(sentence)
    if not m:
        return None
    if m.group("clk"):
        return "cycle"
    if m.group("bit"):
        return "bit_period"
    return "symbol_time"


def _bound_of(sentence: str) -> str:
    if _BOUND_AT_LEAST_RE.search(sentence):
        return "at_least"
    if _BOUND_AT_MOST_RE.search(sentence):
        return "at_most"
    return "exactly"


def _value_of(sentence: str, unit_match: Optional[re.Match]) -> Optional[int]:
    """The count immediately preceding the unit token, in digits or in words."""
    if _SAME_CYCLE_RE.search(sentence):
        return 0
    if unit_match is None:
        # a bound with no unit token still carries its count; take the first
        # quantity in the sentence rather than reporting "no count stated"
        # alongside "no unit stated" and losing both.
        m = re.search(r"\b(\d+)\b", sentence)
        if m:
            return int(m.group(1))
        m = re.search(r"\b([A-Za-z]+)\b", sentence)
        for w in re.findall(r"\b([A-Za-z]+)\b", sentence):
            if w.lower() in _NUM_WORD:
                return _NUM_WORD[w.lower()]
        return None
    pre = sentence[:unit_match.start()]
    # "3 idle bit periods" / "two consecutive clock cycles": allow up to two
    # adjectives between the count and the unit token. Anything further away is
    # not a count OF that unit and must not be adopted as one.
    m = re.search(r"(\d+)(?:\s+[A-Za-z]+){0,2}\s*$", pre)
    if m:
        return int(m.group(1))
    m = re.search(r"\b([A-Za-z]+)(?:\s+[A-Za-z]+){0,2}\s*$", pre)
    if m and m.group(1).lower() in _NUM_WORD:
        return _NUM_WORD[m.group(1).lower()]
    return None


def _named_signals(sentence: str, known: Sequence[str]) -> List[str]:
    """Identifiers in `sentence` that the design actually declares, in order.

    Backticked names are taken even when the design does not declare them, so a
    prose event ("`stop_bit`") is still an EVENT NAME and not silently dropped."""
    out: List[str] = []
    for m in re.finditer(r"`([A-Za-z_]\w*)`|\b([A-Za-z_]\w*)\b", sentence):
        n = m.group(1) or m.group(2)
        if m.group(1) or n in set(known):
            if n not in out:
                out.append(n)
    return out


_SENT_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+|\n")

#: What ends the CLAUSE a stated bound belongs to. A semicolon ends one; so does
#: a sentence terminator followed by whitespace or end of text; so does a blank
#: line. A BARE single newline does NOT — that is a soft wrap in a written spec,
#: and stopping there would cut a clause in half and lose a denial written
#: across two lines.
_CLAUSE_END_RE = re.compile(r";|[.!?](?=\s|$)|\n[ \t]*\n")


def _sentences_pos(text: str) -> List[Tuple[str, int]]:
    """`_sentences` with each fragment's OFFSET into `text`."""
    out: List[Tuple[str, int]] = []
    pos = 0
    for m in _SENT_SPLIT_RE.finditer(text):
        chunk = text[pos:m.start()]
        c = chunk.strip()
        if c:
            out.append((c, pos + (len(chunk) - len(chunk.lstrip()))))
        pos = m.end()
    chunk = text[pos:]
    c = chunk.strip()
    if c:
        out.append((c, pos + (len(chunk) - len(chunk.lstrip()))))
    return out


def _sentences(text: str) -> List[str]:
    return [s for s, _ in _sentences_pos(text)]


def _clause_span(text: str, start: int, end: int) -> Tuple[int, int]:
    """The CLAUSE containing [start, end) — the unit a denial governs.

    Boundaries are located on BRACKET-BLANKED text (length-preserving, so the
    offsets index the original), the way `_prose_polarity` locates its own.
    """
    import _prose_polarity as _pp
    hay = _pp.blank_bracketed(text)
    lo = 0
    for m in _CLAUSE_END_RE.finditer(hay[:start]):
        lo = m.end()
    m = _CLAUSE_END_RE.search(hay, end)
    return lo, (m.start() if m else len(text))


def _denied(concept: str, text: str, frag: str, off: int) -> Optional[str]:
    """The denial word governing `frag`'s CLAUSE, or None. vibe-ic#712.

    WHY A CLAUSE AND NOT A SENTENCE. Measured on e1814e28d, before this guard,
    all three of these published the IDENTICAL contract
    `latency = exactly 3 cycles, frame -> valid`:

        "The output valid is asserted exactly 3 cycles after the input frame."
        "There is no 3 cycle latency between the input frame and the output valid."
        "The 3 cycle latency from frame to valid is removed; nothing replaces it."

    `spec_conformance_check._frame_contract_findings` then reports an ERROR per
    violated element, so a sentence saying the bound does NOT exist became a
    mandate the RTL was failed against — #706 (`pdk_target`) and #711
    (`die_area_budget_um`) in a third field.

    But the scope must be the clause the denial GOVERNS, not the sentence it
    sits in. #2035's own fixture says why:

        "Consecutive frames must be separated by at least 3 idle bit periods;
         a start bit seen sooner is not the start of a frame."

    That STATES an interframe bound and then qualifies it. A sentence-wide check
    reads the qualifier's "is not" and withdraws the bound the same sentence
    just declared — converting a false negative into a false positive, which is
    exactly what `_prose_polarity.concept_is_constitutive` warns a blanket check
    does. A clause-scoped one keeps it, and still catches "…is removed; nothing
    replaces it", where the denial is IN the clause that carries the number.

    `classify_denial` is used rather than a bare `is_denied` so a concept whose
    value a denial CONSTITUTES is never converted into a false suppression.
    """
    try:
        import _prose_polarity as _pp
    except ImportError:                       # noqa: BLE001 — library absent
        return None
    lo, hi = _clause_span(text, off, off + len(frag.rstrip(".;!?")))
    kind, word = _pp.classify_denial(concept, text[lo:hi])
    return word if kind == "negating" else None


def extract_latency_bound(text: str, inputs: Sequence[str],
                          outputs: Sequence[str],
                          internals: Sequence[str] = ()) -> Optional[TemporalBound]:
    """Extract a declared output latency, with every unresolved element NAMED."""
    known = list(inputs) + list(outputs) + list(internals)
    best: Optional[TemporalBound] = None
    for s, _off in _sentences_pos(text):
        if _INTERFRAME_CUE_RE.search(s):
            continue                        # that is the other bound
        um = _UNIT_RE.search(s)
        same = _SAME_CYCLE_RE.search(s)
        if not _LATENCY_CUE_RE.search(s):
            continue
        # A UNIT-LESS latency claim must still ARM. "valid at most 2 after
        # `frame_done`" states a bound whose unit the input simply omitted;
        # requiring a unit token to arm made exactly that claim INVISIBLE, and
        # the gate then reported `latency=NOT_STATED` — which asserts the input
        # said nothing about latency, and it did. Arming here is what lets the
        # missing unit be reported BY NAME instead of being defaulted or lost.
        # arm on: the same-cycle form; a unit token WITH a count beside it
        # ("valid 1 clock cycle after `done`" — the most natural phrasing, and
        # it carries no comparator word); or an explicit comparator bound.
        if not (same or (um and _value_of(s, um) is not None)
                or _states_a_bound(s)):
            continue
        if _denied("frame_latency", text, s, _off):
            continue                        # this CLAUSE denies the bound
        names = _named_signals(s, known)
        dsts = [n for n in names if n in set(outputs)]
        if not dsts:
            continue
        tb = TemporalBound(kind="latency", raw=s)
        tb.unit = "cycle" if same else _unit_of(s)
        tb.value = _value_of(s, um)
        tb.bound = _bound_of(s)
        tb.event_to = dsts[0]
        srcs = [n for n in names if n != tb.event_to]
        tb.event_from = srcs[-1] if srcs else None
        if tb.unit is None:
            tb.missing.append("unit not stated (cycles? bit periods? symbol "
                              "times?) — refusing to default it")
        if tb.value is None:
            tb.missing.append("no count stated beside the unit")
        if tb.event_from is None:
            tb.missing.append("the event the bound is measured FROM is not named")
        # prefer the most completely specified sentence
        score = (tb.unit is not None) + (tb.value is not None) + \
                (tb.event_from is not None)
        if best is None or score > ((best.unit is not None) +
                                    (best.value is not None) +
                                    (best.event_from is not None)):
            best = tb
    return best


def extract_interframe_bound(text: str,
                             inputs: Sequence[str] = (),
                             outputs: Sequence[str] = ()) -> Optional[TemporalBound]:
    """Extract a declared minimum inter-frame space, elements kept separate."""
    for s, _off in _sentences_pos(text):
        if not _INTERFRAME_CUE_RE.search(s):
            continue
        if not _states_a_bound(s):
            continue
        if _denied("frame_interframe", text, s, _off):
            continue                        # this CLAUSE denies the bound
        um = _UNIT_RE.search(s)
        tb = TemporalBound(kind="interframe", raw=s)
        tb.unit = _unit_of(s)
        tb.value = _value_of(s, um)
        tb.bound = _bound_of(s)
        tb.event_from, tb.event_to = "end of frame", "start of next frame"
        if tb.unit is None:
            tb.missing.append("unit not stated (cycles? bit periods? symbol "
                              "times?) — refusing to default it")
        if tb.value is None:
            tb.missing.append("no gap count stated beside the unit")
        return tb
    return None


# ---------------------------------------------------------------------------
# composition
# ---------------------------------------------------------------------------

NOT_STATED = "NOT_STATED"
AI_REQUIRED = "AI_REQUIRED"
SATISFIED = "SATISFIED"
VIOLATED = "VIOLATED"


@dataclass
class FrameContract:
    mapping: Optional[FieldMapping] = None
    latency: Optional[TemporalBound] = None
    interframe: Optional[TemporalBound] = None

    def any_stated(self) -> bool:
        return any(x is not None
                   for x in (self.mapping, self.latency, self.interframe))

    @staticmethod
    def composition_line(states: Dict[str, str], details: Dict[str, str]) -> str:
        """Render the JOINT verdict.

        Latency and inter-frame space are two constraints on the SAME time axis;
        reporting them one at a time lets a candidate that violates their
        COMBINATION read as two separate near-misses. This line states all three
        elements together and names every one that failed."""
        order = ("mapping", "latency", "interframe")
        head = " ".join(f"{k}={states.get(k, NOT_STATED)}" for k in order)
        stated = [k for k in order if states.get(k, NOT_STATED) != NOT_STATED]
        bad = [k for k in order if states.get(k) == VIOLATED]
        if bad:
            tail = (f"{len(bad)} of {len(stated)} stated element(s) FAILED: "
                    + ", ".join(bad))
        elif stated:
            tail = (f"all {len(stated)} stated element(s) hold TOGETHER"
                    if all(states[k] == SATISFIED for k in stated)
                    else f"{len(stated)} stated element(s), not all decidable")
        else:
            tail = "no frame-contract element stated by the input"
        why = "; ".join(f"{k}: {details[k]}" for k in order if details.get(k))
        return f"frame contract composition: {head} — {tail}." + (
            f" {why}" if why else "")


def extract_frame_contract(text: str, inputs: Sequence[str] = (),
                           outputs: Sequence[str] = (),
                           internals: Sequence[str] = ()) -> FrameContract:
    """Extract the whole frame contract from the design INPUT prose."""
    if not text:
        return FrameContract()
    return FrameContract(
        mapping=extract_field_mapping(text, inputs, outputs),
        latency=extract_latency_bound(text, inputs, outputs, internals),
        interframe=extract_interframe_bound(text, inputs, outputs),
    )


# ---------------------------------------------------------------------------
# JSON contracts carry input prose too
# ---------------------------------------------------------------------------

_PROSE_KEYS = ("description", "summary", "overview", "notes", "purpose",
               "behaviour", "behavior", "semantics", "detail", "details")


def input_prose_from_json(raw: str) -> str:
    """Assemble the INPUT prose a JSON contract carries.

    An L9 integration spec is a JSON contract, but it is not prose-free: every
    port entry carries a `description` recovered from the input docs (its
    sibling `evidence` field names the input file it came from), and the
    document itself may carry a summary. `spec_conformance_check.main()`
    discarded all of it, which left every prose-derived rule in that gate
    structurally dormant on the flow's own step-2 invocation.

    Returns '' on anything that is not parseable JSON — "could not read it" must
    not become "read it and it was empty" at a higher layer, and the caller
    treats '' as "no prose channel", not as "no contract"."""
    try:
        data = json.loads(raw)
    except Exception:                       # noqa: BLE001 — not JSON, no prose
        return ""
    out: List[str] = []

    def walk(node, depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(node, dict):
            for k in _PROSE_KEYS:
                v = node.get(k)
                if isinstance(v, str) and v.strip():
                    out.append(v.strip())
            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    walk(data)
    return "\n".join(dict.fromkeys(out))
