#!/usr/bin/env python3
"""area_signoff_baseline.py — resolve the sign-off value a design declares FOR
THE TECHNOLOGY THIS RUN BUILDS AGAINST, or refuse by name.

TWO METRICS, ONE LADDER (vibe-ic#2147). The same L7 table that states a
standard-cell AREA ceiling states a TOTAL POWER ceiling in the identical shape
and from the identical technology-bound baseline, so it goes through the
identical ladder rather than through a second reader that would answer
differently (measured in this repo: a second copy of "the same fact" answers
differently). The metric is a parameter; everything else here is shared.

CHIP_AGNOSTIC: strict — no process, vendor or PDK name anywhere in this file,
DOCSTRING INCLUDED. This is STRICTER than the repo-wide
`source_chip_agnostic_check`, which permits open-PDK names; that gate's PASS is
not this file's verdict.
`test_issue2136_area_signoff_baseline::test_the_program_names_no_process_or_vendor_token`
is, and it reads the WHOLE file. The rule is DECLARED HERE and not only in that
test because an author editing this file has to be able to see it — measured:
the ban shipped asserted-but-undeclared and
`test_chip_agnostic_strictness_is_declared_not_hidden` reddened on exactly that,
which is the rule working.

THE DEFECT THIS CLOSES (measured, vibe-ic#2136)
==============================================
An L7 verification plan states a baseline it MEASURED, and then turns that
measurement into an absolute sign-off row::

    ### 7.4.1 Baseline (top=..., <library-A>, TT corner)
    | stdcell area | **12,775 um^2** |

    ### 7.4.2 Sign-off Acceptance Range
    | stdcell area | (0, baseline x 1.3] = <= 16,608 um^2 | gate |

The baseline row is ATTRIBUTED — it names the standard-cell library it was
measured on.  The sign-off row is not: it carries only the product.  A reader
of the sign-off row alone sees an absolute area ceiling that looks like a
property of the DESIGN, and it is a property of ONE TECHNOLOGY.

Measured consequence: a run of the same design on a different, physically
larger open technology mapped to 57,024.71 um^2 (2180 cells).  Against the row
that is a 3.4x overshoot; against the row's own denominator it is not a
comparison at all, because that denominator was never measured on the library
this run used.  The lane declined to report pass/fail and said so, which is the
correct human answer and exactly the answer a program has to be able to give.

This is the same shape as ``database_unit_um`` (#2085) and as the clock period
(#2091): a TECHNOLOGY fact stated once, for one technology, and then read as if
it were universal.  `clock_target_provenance` is the model followed here — the
value never travels without the tier that produced it.

WHAT THIS PROGRAM DOES
======================
It reads the design INPUT for (a) a declared standard-cell area baseline and
its attribution, and (b) the acceptance rule applied to it, and answers ONE
question: *is there a valid denominator for the technology this run resolved?*

THE LADDER, highest authority first::

    declared_pdk_table              a technology-keyed area table row matching
                                    this run's library / PDK
    declared_baseline_technology    a baseline row whose own attribution names
                                    this run's technology family
    derived_reference_netlist       a reference-netlist area MEASURED in this
                                    run's own cell library, x the declared ratio
    not_determined                  NAMED REFUSAL                <-- never PASS

``NOT_DETERMINED`` IS THE LOAD-BEARING STATE.  It is not a soft PASS and it is
not a FAIL: a design measured against a denominator from another technology has
not been judged at all, and publishing either verdict would be a false
statement about the design.  Every refusal carries `reason`, the run's
technology, and the attribution text the document actually carried, so the
refusal is actionable rather than merely negative.

WHY THE BASELINE'S ATTRIBUTION GOVERNS THE THRESHOLD
====================================================
The absolute in the acceptance row is a PRODUCT of the baseline and a ratio the
same document states.  It inherits the baseline's attribution and has none of
its own.  So a threshold is usable exactly when the baseline behind it is, and
a document that states an absolute with no attributable baseline anywhere
declares no denominator at all.

HONESTY BOUNDARY (Sec 4.05)
===========================
Only the design INPUT is read.  Nothing is defaulted, interpolated, rounded or
scaled from a neighbouring technology.  Two baseline rows that match the run
and DISAGREE are AMBIGUOUS and resolve to nothing — picking one by document
order is how a cross-technology number gets published as a specification.  A
denied row is not a declaration (vibe-ic#712), consulted through the repo's one
negation vocabulary.

HOW THE STRICT DECLARATION ABOVE IS HONOURED: the run's technology names are
supplied by the CALLER from what the run resolved, and every other name comes
from the design's own document.  Two names belong to the same technology family
when one's leading family token is a prefix of the other's — a naming
convention, not a name.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402
from _prose_polarity import is_denied as _is_denied  # noqa: E402
# The repo's ONE spelling of "how a markdown table row is split", and of "does
# this row's key name the technology the caller resolved". A second copy of
# those facts is a second answer to them (measured elsewhere in this repo), so
# they are imported rather than restated.
from declared_clock_period import (  # noqa: E402
    _cells, _clean_key, _is_separator, match_rows)

#: The tier names. `NOT_DETERMINED_TIER` is a verdict, not an absence.
DECLARED_PDK_TABLE_TIER = "declared_pdk_table"
DECLARED_BASELINE_TIER = "declared_baseline_technology"
DERIVED_REFERENCE_TIER = "derived_reference_netlist"
NOT_DETERMINED_TIER = "not_determined"

#: The three verdicts a caller may publish. Nothing else is a verdict.
PASS = "PASS"
FAIL = "FAIL"
NOT_DETERMINED = "NOT_DETERMINED"

#: The disclosure a consumer MUST carry when the denominator is not this run's.
#: One constant so an emitter and a checker cannot drift apart.
NOT_DETERMINED_DISCLOSURE = (
    "standard-cell area was NOT judged: no area baseline is declared for the "
    "technology this run built against")

# ── THE METRIC IS A PARAMETER (vibe-ic#2147) ───────────────────────────────
#
# One L7 table states an AREA row and a POWER row, from ONE baseline table, in
# ONE shape, gated by ONE ratio sentence. Reading them with two readers is how
# a repo ends up with two answers to one fact, so the reader is shared and the
# metric — what its name looks like, what units it may be written in, and what
# unit it is compared in — is the only thing that varies.
#
# A `Metric` names no chip, vendor or technology. It names a QUANTITY.

# A metric cell naming the STANDARD-CELL area. `die area` and `core area` are
# deliberately NOT matched: they are different quantities with different
# ceilings, and `area_total_vs_budget_check` already owns the die comparison.
_CELL_AREA_METRIC_RE = re.compile(
    r"(?:std\s*[-_]?\s*cell|standard[\s_-]*cell|cell)\s*area"
    r"|標準(?:單元|元件|儲存格)?\s*面積"
    r"|單元\s*面積",
    re.IGNORECASE)
# A metric cell naming the design's TOTAL power. A per-domain, leakage-only or
# switching-only row is a component, not the total, and is not matched: a
# ceiling on the total may not be applied to one of its parts.
_TOTAL_POWER_METRIC_RE = re.compile(
    r"total\s*power|power\s*\(?\s*total|總(?:功耗|耗電|功率)|整體\s*功耗",
    re.IGNORECASE)

# The units each metric may be WRITTEN in, and the factor that takes a stated
# figure to the unit this program COMPARES in. A figure in any other unit is
# READ AND REFUSED, never converted on a guess.
# THE PATTERN IS WIDER THAN THE TABLE, DELIBERATELY. A pattern that matched
# only the units this program can convert would read a figure stated in any
# other unit as NO FIGURE AT ALL — "the design states no ceiling" and "the
# design states a ceiling this gate cannot convert" are different findings, and
# the second one must be reported rather than turned into the first. So the
# pattern accepts a unit SHAPE and `Metric.to_canonical` refuses the ones the
# table does not carry, recording each refusal with the text it read.
_UM2 = r"(?:[a-zA-Zµμ]{1,7})\s*(?:\^2|²|\*\*2|2)"
_AREA_UNITS = {"um^2": 1.0}
_POWER_UNIT_RE = r"(?:[a-zA-Zµμ]{0,2}\s*W)\b"
_POWER_UNITS = {"w": 1e6, "mw": 1e3, "uw": 1.0, "nw": 1e-3}

# `baseline x 1.3` in the spellings a document actually writes it in. The
# multiplier must be a NUMBER: `baseline x [0.5, 2.0]` is a two-sided range on
# a different (informational) metric and is not a ceiling.
_RATIO_RE = re.compile(
    r"baseline\s*[×xX\*]\s*(\d+(?:\.\d+)?)"
    r"|基準\s*[×xX\*]\s*(\d+(?:\.\d+)?)")
#: The comparator that turns a figure into an upper bound.
_UPPER_PREFIX = r"(?:≤|<=|≦|<|不超過|至多)\s*\*{0,2}\s*"
_NUMBER = r"(\d[\d,\s]*(?:\.\d+)?)"

# A header cell that names the technology key column. Same vocabulary as the
# period table's key column, for the same reason: it is how these documents
# spell "which technology this row is about".
_KEY_HDR_RE = re.compile(
    r"librar|library|pdk|std[\s_-]*cell|cell\s*lib|技術|製程", re.IGNORECASE)


def _norm_unit(raw: str) -> str:
    """A unit token reduced to its comparison key: no spaces, lowercased, and
    every spelling of `micro` folded to `u`."""
    t = re.sub(r"\s+", "", str(raw or "")).lower()
    t = t.replace("µ", "u").replace("μ", "u")
    t = t.replace("²", "^2").replace("**2", "^2").replace("um2", "um^2")
    t = t.replace("micron^2", "um^2").replace("micron", "um")
    return t


class Metric:
    """A quantity this reader can resolve. Names a QUANTITY, never a technology."""

    def __init__(self, key, label, metric_re, unit_pattern, units,
                 canonical_unit, hdr_re, prose_re, disclosure,
                 no_signoff_reason):
        self.key = key
        self.label = label
        self.metric_re = metric_re
        self.units = units
        self.canonical_unit = canonical_unit
        self.hdr_re = hdr_re
        self.prose_re = prose_re
        self.disclosure = disclosure
        #: The `reason` a caller matches on when the design states nothing.
        #: A PUBLISHED name per metric, so #2136's area contract is unchanged.
        self.no_signoff_reason = no_signoff_reason
        self.value_re = re.compile(_NUMBER + r"\s*(" + unit_pattern + r")",
                                   re.IGNORECASE)
        self.upper_re = re.compile(_UPPER_PREFIX + _NUMBER + r"\s*("
                                   + unit_pattern + r")", re.IGNORECASE)

    def to_canonical(self, value, unit_text):
        """`value` in :attr:`canonical_unit`, or None when the unit is not one
        this metric accepts. An unrecognised unit is a REFUSAL, not a guess."""
        f = self.units.get(_norm_unit(unit_text))
        return None if f is None else value * f


METRIC_CELL_AREA = Metric(
    key="cell_area", label="standard-cell area",
    metric_re=_CELL_AREA_METRIC_RE, unit_pattern=_UM2, units=_AREA_UNITS,
    canonical_unit="um^2",
    hdr_re=re.compile(r"area|面積", re.IGNORECASE),
    prose_re=re.compile(r"area|面積", re.IGNORECASE),
    # ONE copy of the sentence. `NOT_DETERMINED_DISCLOSURE` is what the L7
    # emitter and every consumer import; the metric carries the same object so
    # the two cannot drift into asserting different strings.
    disclosure=NOT_DETERMINED_DISCLOSURE,
    no_signoff_reason="no_area_signoff_stated")

METRIC_TOTAL_POWER = Metric(
    key="total_power", label="total power",
    metric_re=_TOTAL_POWER_METRIC_RE, unit_pattern=_POWER_UNIT_RE,
    units=_POWER_UNITS, canonical_unit="uW",
    hdr_re=re.compile(r"power|功耗|耗電|功率", re.IGNORECASE),
    prose_re=re.compile(r"power|功耗|耗電|功率", re.IGNORECASE),
    disclosure=("total power was NOT judged: no power baseline is declared "
                "for the technology this run built against"),
    no_signoff_reason="no_power_signoff_stated")

#: Every metric this reader knows, by key.
METRICS = {m.key: m for m in (METRIC_CELL_AREA, METRIC_TOTAL_POWER)}

#: A markdown heading line, which is where a baseline table states its scope.
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
#: How far back to look for an attribution when the document has no heading.
_ATTRIBUTION_FALLBACK_LINES = 12
#: Shortest family token that may be matched by prefix. Two-and-three-character
#: prefixes collide across unrelated families; four does not, measured against
#: every technology name this repo's registry carries.
_MIN_FAMILY_LEN = 4


# ── technology-name identity, by convention rather than by name ─────────────
def family(name: str) -> str:
    """The leading family token of a technology name, lowercased.

    A standard-cell library is conventionally spelled ``<family>_<...>`` and a
    PDK ``<family><variant>``, so the family token is the run of characters up
    to the first separator. No name is recognised here — only a shape.
    """
    t = str(name or "").strip().lower().strip("`*")
    t = re.split(r"[_\-. /]", t, 1)[0]
    return re.sub(r"[^a-z0-9]", "", t)


def same_family(a: str, b: str) -> bool:
    """True when two technology names belong to one family.

    A PDK name and a library name from the same family differ by a variant
    suffix on one side or the other, so the test is PREFIX in either direction
    over the family tokens — never equality, which would make a library and its
    own PDK read as different technologies.
    """
    fa, fb = family(a), family(b)
    if len(fa) < _MIN_FAMILY_LEN or len(fb) < _MIN_FAMILY_LEN:
        return False
    return fa.startswith(fb) or fb.startswith(fa)


def _text_names_family(text: str, candidates: Sequence[str]) -> Optional[str]:
    """The first token in ``text`` belonging to a candidate's family, or None."""
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9_\-.]{2,}", text or ""):
        for cand in candidates:
            if same_family(tok, cand):
                return tok
    return None


# ── numbers ────────────────────────────────────────────────────────────────
def _num(raw: str) -> Optional[float]:
    """A figure written with thousands separators, or None."""
    try:
        v = float(re.sub(r"[,\s]", "", str(raw)))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


# ── reading the design's own area statements ───────────────────────────────
def _attribution(lines: Sequence[str], row_idx: int) -> Tuple[str, int]:
    """The scope a table row's value is stated under, and the line it starts on.

    A baseline table states WHAT IT MEASURED in its heading or in the caption
    between the heading and the table — never inside the value row, which is
    why the row alone is not enough to attribute the number.
    """
    for i in range(row_idx, -1, -1):
        if _HEADING_RE.match(lines[i]):
            return "\n".join(lines[i:row_idx + 1]), i + 1
    lo = max(0, row_idx - _ATTRIBUTION_FALLBACK_LINES)
    return "\n".join(lines[lo:row_idx + 1]), lo + 1


def parse_signoff_statements(text: str, metric: "Metric",
                             source: str = "") -> Dict[str, object]:
    """Every BASELINE, CEILING and RATIO ``metric`` has in ``text``.

    A row is classified by WHAT ITS CELLS SAY, not by the section number it
    sits under, so a document that numbers its sections differently is read
    identically:

      * a cell carrying ``baseline x <n>``            -> a ratio;
      * a cell carrying a comparator in front of a
        figure in one of this metric's units          -> a ceiling;
      * a cell carrying a bare figure and neither of
        the above                                     -> a measured baseline.

    Every figure is returned in ``metric.canonical_unit``. A figure whose unit
    this metric does not accept is RECORDED in ``unreadable_units`` and used
    for nothing — an unconvertible number is a refusal, not a guess.
    """
    out: Dict[str, object] = {"baselines": [], "ceilings": [], "ratios": [],
                              "unreadable_units": []}
    lines = text.splitlines()
    for j, line in enumerate(lines):
        cells = _cells(line)
        if not cells or _is_separator(cells):
            continue
        if not metric.metric_re.search(cells[0] or ""):
            continue
        # vibe-ic#712 — a RETIRED row is not a declaration. The row is the
        # record, so the row is the scope: a denial one row up must not retire
        # the row below it.
        if _is_denied(line):
            continue
        attribution, attribution_line = _attribution(lines, j)
        base = {"source": source, "line": j + 1, "row": line.strip()[:300],
                "attribution": attribution.strip()[:600],
                "attribution_line": attribution_line}

        def _canon(m):
            raw = _num(m.group(1))
            if raw is None:
                return None
            got = metric.to_canonical(raw, m.group(2))
            if got is None:
                out["unreadable_units"].append(
                    dict(base, stated=m.group(0).strip(),
                         reason=(f"{m.group(2)!r} is not a unit "
                                 f"{metric.label} is compared in "
                                 f"({metric.canonical_unit})")))
            return got

        for cell in cells[1:]:
            rm = _RATIO_RE.search(cell)
            if rm:
                val = _num(rm.group(1) or rm.group(2))
                if val:
                    out["ratios"].append(dict(base, ratio=val))
            um = metric.upper_re.search(cell)
            if um:
                val = _canon(um)
                if val:
                    out["ceilings"].append(dict(base, value=val))
                continue
            if rm:
                continue
            am = metric.value_re.search(cell)
            if am:
                val = _canon(am)
                if val:
                    out["baselines"].append(dict(base, value=val))
    # THE ACCEPTANCE RATIO IS AS OFTEN STATED IN PROSE AS IN A ROW. The
    # measured document writes it in the paragraph above the table ("area /
    # power within baseline x 1.3") as well as inside the row, and a keyed
    # table states it only in prose. A ratio read here is subject to the same
    # two rules as one read from a row: a denied line declares nothing, and two
    # DIFFERENT ratios anywhere in the document refuse rather than vote — so a
    # prose line about a different quantity cannot quietly displace the right
    # one, it can only make the document ambiguous.
    for j, line in enumerate(lines):
        if _cells(line):
            continue                      # rows are handled above
        if not metric.prose_re.search(line):
            continue
        if _is_denied(line):
            continue
        rm = _RATIO_RE.search(line)
        if not rm:
            continue
        val = _num(rm.group(1) or rm.group(2))
        if val:
            attribution, attribution_line = _attribution(lines, j)
            out["ratios"].append({
                "source": source, "line": j + 1, "row": line.strip()[:300],
                "attribution": attribution.strip()[:600],
                "attribution_line": attribution_line, "ratio": val})
    return out


def parse_area_statements(text: str, source: str = "") -> Dict[str, object]:
    """:func:`parse_signoff_statements` for the standard-cell area metric.

    Kept because it is the name #2136 published and the shape its tests read;
    ``value_um2`` is the same number as ``value``, in the same unit.
    """
    got = parse_signoff_statements(text, METRIC_CELL_AREA, source=source)
    for key in ("baselines", "ceilings"):
        for row in got[key]:                      # type: ignore[index]
            row["value_um2"] = row["value"]
    return got


def parse_keyed_tables(text: str, metric: "Metric",
                       source: str = "") -> List[Dict[str, object]]:
    """Rows of every table that keys ``metric`` by technology.

    The portable way to state a per-technology baseline is a keyed table, the
    same shape `declared_clock_period` reads for the clock period. A table
    qualifies when one header cell names this metric's quantity and another
    names a library/PDK key.
    """
    rows: List[Dict[str, object]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        hdr = _cells(lines[i])
        if hdr is None or i + 1 >= len(lines):
            i += 1
            continue
        sep = _cells(lines[i + 1])
        if sep is None or not _is_separator(sep):
            i += 1
            continue
        val_col = next((n for n, c in enumerate(hdr)
                        if metric.hdr_re.search(c or "")), None)
        key_col = next((n for n, c in enumerate(hdr)
                        if _KEY_HDR_RE.search(c or "")), None)
        if val_col is None or key_col is None or val_col == key_col:
            i += 1
            continue
        j = i + 2
        while j < len(lines):
            row = _cells(lines[j])
            if row is None:
                break
            if _is_separator(row):
                j += 1
                continue
            if max(val_col, key_col) < len(row) and not _is_denied(lines[j]):
                key = _clean_key(row[key_col])
                cell = row[val_col] or ""
                um = metric.upper_re.search(cell) or metric.value_re.search(cell)
                raw = _num(um.group(1)) if um else None
                val = (metric.to_canonical(raw, um.group(2))
                       if (um and raw is not None) else None)
                if key and val:
                    rows.append({"key": key, "value": val, "value_um2": val,
                                 "source": source, "line": j + 1,
                                 "row": lines[j].strip()[:300],
                                 "ceiling": bool(metric.upper_re.search(cell))})
            j += 1
        i = j
    return rows


def parse_area_key_tables(text: str, source: str = "") -> List[Dict[str, object]]:
    """:func:`parse_keyed_tables` for the standard-cell area metric."""
    return parse_keyed_tables(text, METRIC_CELL_AREA, source=source)


def _blank_report(candidates: Sequence[str],
                  metric: "Metric") -> Dict[str, object]:
    """The report shape. Every field exists on every path, so a consumer never
    has to ask whether a key is missing or merely unanswered.

    ``threshold`` / ``baseline`` / ``derived`` are in ``unit``. The ``_um2``
    aliases are published for the standard-cell area metric ONLY, because that
    is the name #2136 shipped and the L7 emitter's readers use it; they are the
    same numbers, never a second answer.
    """
    return {
        "metric": metric.key,
        "metric_label": metric.label,
        "unit": metric.canonical_unit,
        "threshold": None,
        "baseline": None,
        "derived": None,
        "ratio": None,
        "tier": NOT_DETERMINED_TIER,
        "determined": False,
        "reason": "",
        "candidates": [c for c in candidates if c],
        "matched_name": None,
        "source": None,
        "line": None,
        "row": "",
        "baseline_attribution": "",
        "baseline_source": None,
        "baseline_line": None,
        "baseline_row": "",
        "attributions_seen": [],
        "signoff_row_found": False,
        "unreadable_units": [],
        "note": "",
        "disclosure": "",
        "would_have_stated": "",
    }


#: The keys the standard-cell area metric also publishes under its #2136 names.
_UM2_ALIASES = (("threshold_um2", "threshold"), ("baseline_um2", "baseline"),
                ("derived_um2", "derived"))


def _with_aliases(rep: Dict[str, object]) -> Dict[str, object]:
    """Republish the area metric's values under the names #2136 shipped."""
    if rep.get("metric") == METRIC_CELL_AREA.key:
        for alias, canonical in _UM2_ALIASES:
            rep[alias] = rep.get(canonical)
    return rep


def _refuse(rep: Dict[str, object], metric: "Metric", reason: str,
            note: str) -> Dict[str, object]:
    rep["tier"] = NOT_DETERMINED_TIER
    rep["determined"] = False
    rep["reason"] = reason
    rep["note"] = note
    rep["disclosure"] = metric.disclosure
    rep["would_have_stated"] = (
        f"a {metric.label} baseline attributed to "
        f"'{(rep['candidates'] or ['the target technology'])[0]}' — either a "
        f"technology-keyed {metric.label} table row naming it, or a baseline "
        "table whose own heading names it — would make this a specification "
        "for this run")
    return _with_aliases(rep)


def resolve_texts(items: Sequence[Tuple[str, str]],
                  candidates: Sequence[str],
                  *,
                  metric: "Metric" = METRIC_CELL_AREA,
                  reference_value: Optional[float] = None,
                  reference_cite: str = "",
                  reference_area_um2: Optional[float] = None,
                  reference_area_cite: str = "") -> Dict[str, object]:
    """Resolve ``metric``'s threshold for ``candidates`` over ``(name, text)`` docs.

    ``candidates`` are the technology names THIS RUN resolved (its std-cell
    library, its PDK, or both). An empty list is not a licence to fall back to
    whatever the document states first — it means the run's technology is not
    known here, and the answer is a refusal.

    ``reference_value`` is a baseline MEASURED in this run's own cell library,
    in ``metric.canonical_unit``. ``reference_area_um2`` is #2136's name for it
    and means the same thing for the area metric.
    """
    if reference_value is None and reference_area_um2 is not None:
        reference_value, reference_cite = (reference_area_um2,
                                           reference_cite or reference_area_cite)
    cands = [c.strip() for c in candidates if c and str(c).strip()]
    rep = _blank_report(cands, metric)

    stmts: Dict[str, List[Dict[str, object]]] = {
        "baselines": [], "ceilings": [], "ratios": [], "unreadable_units": []}
    keyed: List[Dict[str, object]] = []
    for name, text in items:
        if not isinstance(text, str) or not text:
            continue
        got = parse_signoff_statements(text, metric, source=name)
        for k in stmts:
            stmts[k].extend(got[k])          # type: ignore[arg-type]
        keyed.extend(parse_keyed_tables(text, metric, source=name))

    rep["unreadable_units"] = stmts["unreadable_units"]
    rep["signoff_row_found"] = bool(
        stmts["baselines"] or stmts["ceilings"] or keyed)
    rep["attributions_seen"] = sorted({
        str(b["attribution"]).splitlines()[0].strip()
        for b in stmts["baselines"]})

    if not cands:
        return _refuse(
            rep, metric, "run_technology_not_supplied",
            "the technology this run builds against was not supplied, so no "
            "baseline can be attributed to it; a threshold resolved without "
            "one is a threshold from whichever technology the document "
            "happened to state first")

    if not rep["signoff_row_found"]:
        # "NOTHING WAS STATED" and "SOMETHING WAS STATED THAT THIS GATE CANNOT
        # CONVERT" are different findings and get different names. Collapsing
        # them would turn a document that DOES declare a ceiling into one that
        # does not, which is the shape of every defect in this file's history.
        if stmts["unreadable_units"]:
            return _refuse(
                rep, metric, "signoff_unit_not_comparable",
                f"the design states a {metric.label} figure this gate cannot "
                f"compare: "
                + "; ".join(f"{u['source']}:{u['line']} {u['stated']!r} — "
                            f"{u['reason']}"
                            for u in stmts["unreadable_units"][:3]))
        return _refuse(
            rep, metric, metric.no_signoff_reason,
            f"the design input states no {metric.label} baseline and no "
            f"{metric.label} ceiling")

    # ── tier 1: a technology-keyed table row ──────────────────────────────
    hits = match_rows(keyed, cands)
    if hits:
        values = sorted({round(float(h["value"]), 6) for h in hits})
        if len(values) > 1:
            return _refuse(
                rep, metric, "declared_table_ambiguous",
                f"{len(hits)} technology-keyed {metric.label} row(s) match "
                f"{cands} and they declare DIFFERENT values {values} "
                f"{metric.canonical_unit}; refusing to pick one. Rows: "
                + "; ".join(f"{h['source']}:{h['line']} {h['row']}"
                            for h in hits))
        best = sorted(hits, key=lambda h: (str(h["key"]).count("*"),
                                           -len(str(h["key"]))))[0]
        rep.update({"tier": DECLARED_PDK_TABLE_TIER, "determined": True,
                    "matched_name": best["key"], "source": best["source"],
                    "line": best["line"], "row": best["row"]})
        if best["ceiling"]:
            rep["threshold"] = float(best["value"])
        else:
            rep["baseline"] = float(best["value"])
        ratio = _one_ratio(stmts["ratios"])
        if ratio is not None:
            rep["ratio"] = ratio
        if rep["threshold"] is None:
            if ratio is None:
                return _refuse(
                    rep, metric, "no_acceptance_rule",
                    f"a baseline of {rep['baseline']:g} {metric.canonical_unit} "
                    f"is declared for '{best['key']}' at "
                    f"{best['source']}:{best['line']}, but the document states "
                    "no acceptance rule (no ceiling and no 'baseline x <n>' "
                    "multiplier) to turn it into one")
            rep["threshold"] = round(float(rep["baseline"]) * ratio, 6)
            rep["derived"] = rep["threshold"]
        rep["note"] = (
            f"the design declares {rep['threshold']:g} {metric.canonical_unit} "
            f"for '{best['key']}' (matched {cands}) at "
            f"{best['source']}:{best['line']} — {best['row']}")
        return _with_aliases(rep)

    # ── tier 2: a baseline row attributed to this run's technology ─────────
    mine = [b for b in stmts["baselines"]
            if _text_names_family(str(b["attribution"]), cands)]
    if mine:
        values = sorted({round(float(b["value"]), 6) for b in mine})
        if len(values) > 1:
            return _refuse(
                rep, metric, "declared_baseline_ambiguous",
                f"{len(mine)} {metric.label} baseline(s) are attributed to "
                f"{cands} and they DISAGREE {values} {metric.canonical_unit}; "
                "refusing to pick one. Rows: "
                + "; ".join(f"{b['source']}:{b['line']} {b['row']}"
                            for b in mine))
        best = mine[0]
        rep.update({
            "tier": DECLARED_BASELINE_TIER, "determined": True,
            "baseline": float(best["value"]),
            "matched_name": _text_names_family(str(best["attribution"]), cands),
            "source": best["source"], "line": best["line"], "row": best["row"],
            # The ceiling's citation overwrites `source`/`line` below when the
            # document states one, so the BASELINE's own citation is kept in
            # its own fields. Provenance that survives only in `note` is
            # provenance a consumer has to parse English to reach.
            "baseline_source": best["source"], "baseline_line": best["line"],
            "baseline_row": best["row"],
            "baseline_attribution": best["attribution"]})
        ratio = _one_ratio(stmts["ratios"])
        rep["ratio"] = ratio
        if ratio is not None:
            rep["derived"] = round(float(best["value"]) * ratio, 6)
        # The document's OWN stated ceiling is the design's number and wins over
        # the product, which can differ from it by the document's rounding. Both
        # travel, so a reader can see the rounding rather than guess at it.
        ceilings = sorted({round(float(c["value"]), 6)
                           for c in stmts["ceilings"]})
        if len(ceilings) > 1:
            return _refuse(
                rep, metric, "declared_ceiling_ambiguous",
                f"the document states {len(ceilings)} DIFFERENT {metric.label} "
                f"ceilings {ceilings} {metric.canonical_unit}; refusing to "
                "pick one")
        if ceilings:
            cite = stmts["ceilings"][0]
            rep["threshold"] = ceilings[0]
            rep["note"] = (
                f"the design states a {metric.label} ceiling of "
                f"{ceilings[0]:g} {metric.canonical_unit} at "
                f"{cite['source']}:{cite['line']}, from a baseline of "
                f"{rep['baseline']:g} {metric.canonical_unit} attributed to "
                f"'{rep['matched_name']}' at {best['source']}:{best['line']}"
                + (f" (ratio {ratio:g}, product {rep['derived']:g} "
                   f"{metric.canonical_unit})" if ratio is not None else ""))
            rep["source"] = cite["source"]
            rep["line"] = cite["line"]
            rep["row"] = cite["row"]
            return _with_aliases(rep)
        if ratio is None:
            return _refuse(
                rep, metric, "no_acceptance_rule",
                f"a baseline of {rep['baseline']:g} {metric.canonical_unit} is "
                f"attributed to '{rep['matched_name']}' at "
                f"{best['source']}:{best['line']}, but the document states no "
                "acceptance rule (no ceiling and no 'baseline x <n>' "
                "multiplier) to turn it into one")
        rep["threshold"] = rep["derived"]
        rep["note"] = (
            f"the design declares a baseline of {rep['baseline']:g} "
            f"{metric.canonical_unit} for '{rep['matched_name']}' at "
            f"{best['source']}:{best['line']} and an acceptance ratio of "
            f"{ratio:g}, giving {rep['threshold']:g} {metric.canonical_unit}")
        return _with_aliases(rep)

    # ── tier 3: measured in this run's own library ─────────────────────────
    if reference_value:
        ratio = _one_ratio(stmts["ratios"])
        if ratio is None:
            return _refuse(
                rep, metric, "no_acceptance_rule",
                f"a reference-netlist {metric.label} of "
                f"{float(reference_value):g} {metric.canonical_unit} was "
                "measured in this run's own cell library, but the document "
                "states no acceptance rule (no 'baseline x <n>' multiplier) to "
                "turn it into a threshold")
        rep.update({
            "tier": DERIVED_REFERENCE_TIER, "determined": True,
            "baseline": float(reference_value), "ratio": ratio,
            "matched_name": cands[0],
            "threshold": round(float(reference_value) * ratio, 6),
            "source": reference_cite or None, "row": ""})
        rep["derived"] = rep["threshold"]
        rep["note"] = (
            f"DERIVED for '{cands[0]}': the reference netlist measures "
            f"{float(reference_value):g} {metric.canonical_unit} in this run's "
            f"own cell library ({reference_cite or 'caller-supplied'}) and the "
            f"design's acceptance ratio is {ratio:g}, giving "
            f"{rep['threshold']:g} {metric.canonical_unit}")
        return _with_aliases(rep)

    # ── the refusal this issue exists for ─────────────────────────────────
    seen = rep["attributions_seen"] or ["(the baseline row states no scope)"]
    return _refuse(
        rep, metric, "baseline_not_attributed_to_this_technology",
        f"the design states a {metric.label} sign-off, but no baseline is "
        f"attributed to {cands}. What the document DOES attribute its baseline "
        f"to: {seen}. A ceiling derived from another technology's baseline is "
        "not a ceiling for this run, and reporting it as PASS or as FAIL would "
        "both be false statements about this design.")


def _one_ratio(ratios: Sequence[Dict[str, object]]) -> Optional[float]:
    """The single acceptance ratio the document states, or None.

    Two different ratios is a refusal, not a vote — the same rule the rest of
    this module follows.
    """
    vals = sorted({round(float(r["ratio"]), 6) for r in ratios})
    return vals[0] if len(vals) == 1 else None


def resolve(docs: Sequence[Path], candidates: Sequence[str],
            **kw) -> Dict[str, object]:
    """:func:`resolve_texts` over files on disk."""
    items: List[Tuple[str, str]] = []
    for d in docs:
        try:
            items.append((str(d), Path(d).read_text(errors="ignore")))
        except OSError:
            continue
    return resolve_texts(items, candidates, **kw)


# ── the verdict a consumer may publish ─────────────────────────────────────
def verdict(rep: Dict[str, object],
            measured_um2: Optional[float] = None,
            *, measured: Optional[float] = None) -> Dict[str, object]:
    """PASS / FAIL / NOT_DETERMINED for a measured figure of ``rep``'s metric.

    NOT_DETERMINED whenever the denominator is not this run's, whatever the
    measured figure is. A cross-technology FAIL is as wrong as a
    cross-technology PASS and this function will emit neither.

    The first parameter keeps #2136's name because that is what its callers
    pass; ``measured`` is the same value under the metric-neutral name, and the
    result carries BOTH spellings for the area metric.
    """
    if measured is None:
        measured = measured_um2
    unit = str(rep.get("unit") or "um^2")
    label = str(rep.get("metric_label") or "standard-cell area")
    out: Dict[str, object] = {
        "verdict": NOT_DETERMINED,
        "metric": rep.get("metric"),
        "unit": unit,
        "measured": float(measured) if measured is not None else None,
        "threshold": rep.get("threshold"),
        "tier": rep.get("tier"),
        "reason": rep.get("reason") or "",
        "note": rep.get("note") or ""}
    if rep.get("metric") == METRIC_CELL_AREA.key:
        out["measured_um2"] = out["measured"]
        out["threshold_um2"] = out["threshold"]
    if not rep.get("determined"):
        out["reason"] = rep.get("reason") or "not_determined"
        out["note"] = (rep.get("note")
                       or rep.get("disclosure") or NOT_DETERMINED_DISCLOSURE)
        return out
    if measured is None:
        out["reason"] = "no_measured_value"
        out["note"] = (f"a {label} threshold was resolved but this run "
                       f"published no {label} figure to compare against it")
        return out
    thr = float(rep["threshold"])
    out["verdict"] = PASS if float(measured) <= thr else FAIL
    out["reason"] = ""
    out["note"] = (f"{float(measured):g} {unit} measured against "
                   f"{thr:g} {unit} resolved via '{rep.get('tier')}'"
                   + (f" ({rep.get('source')}"
                      + (f":{rep.get('line')}" if rep.get("line") else "")
                      + ")" if rep.get("source") else ""))
    return out


# ── what the run built against, as far as the project itself says ──────────

#: Where a run records the library its synthesis actually loaded. The field is
#: `synth_area_stats_emit`'s own unit evidence, so this reads the SAME artefact
#: the area figure came out of — the figure and the library it is denominated
#: in cannot disagree.
_RUN_LIBERTY_FIELD = "stats.json::chip_area_unit_evidence.liberty"
_RUN_STATS_GLOBS: Sequence[str] = (
    "phase2/stage2/synth/stats.json",
    "steps/**/stats.json",
    "reports/**/stats.json",
)
#: The open_pdks tree layout: `<pdk>/libs.ref/<library>/lib/<file>.lib`. This is
#: a directory CONVENTION, not the name of any particular technology.
_LIBS_REF = "libs.ref"


def _dcp_library_name(liberty: str) -> str:
    """The std-cell library a liberty path names. One spelling, imported."""
    try:
        from declared_clock_period import library_name_from_liberty
    except Exception:                                        # pragma: no cover
        return ""
    return library_name_from_liberty(liberty)


def _pdk_from_liberty(liberty: str) -> str:
    """The PDK directory a liberty path sits under, or ''.

    Named by POSITION in the tree (`<pdk>/libs.ref/...`), never by matching a
    name — this file resolves technologies, it does not know any.
    """
    parts = Path(str(liberty or "")).parts
    if _LIBS_REF in parts:
        n = parts.index(_LIBS_REF)
        if n >= 1:
            return parts[n - 1]
    return ""


def _run_libraries(project: Path) -> List[str]:
    """Every liberty path this run's own synthesis artefacts name.

    More than one DISTINCT family here is a real ambiguity and is passed
    through as such: a run that loaded two families has not been built on one,
    and picking the first would be the #2136 defect with a different source.
    """
    out: List[str] = []
    seen = set()
    for pat in _RUN_STATS_GLOBS:
        for f in sorted(project.glob(pat)):
            if not f.is_file():
                continue
            try:
                doc = json.loads(f.read_text(errors="replace"))
            except Exception:
                continue
            if not isinstance(doc, dict):
                continue
            ev = doc.get("chip_area_unit_evidence")
            lib = (ev.get("liberty") if isinstance(ev, dict) else None)
            if not isinstance(lib, str) or not lib.strip():
                lib = doc.get("liberty")
            if not isinstance(lib, str) or not lib.strip():
                continue
            if lib in seen:
                continue
            seen.add(lib)
            out.append(lib)
    return out


def run_technology(project: Path, *, selected_pdk: str = "") -> Dict[str, object]:
    """The technology names THIS project declares, and whether they are one.

    A design that names two technology families has not chosen one, and a
    baseline resolved against the first of them would be a baseline for a run
    that may not be happening. That is `ambiguous`, and it refuses.
    """
    out: Dict[str, object] = {"candidates": [], "ambiguous": False,
                              "source": None, "note": ""}
    names: List[str] = []
    src = None
    selected_pdk = selected_pdk.strip()
    if selected_pdk.lower() == "auto":
        selected_pdk = ""
    # ── THE RUN'S OWN SYNTHESIS ARTEFACT FIRST (vibe-ic#2147) ──────────────
    #
    # An L-doc says what the design MAY be built on; the synthesis artefact
    # says what this run DID build on, and it is the only one of the two that
    # can be wrong about nothing. The measured design names two families in L19
    # and its stats.json names the single library the run loaded, down to the
    # corner file. When the artefact answers, the L-doc is not consulted — a
    # design's ambition may not overrule its own run.
    for liberty in _run_libraries(project):
        lib = _dcp_library_name(liberty)
        pdk = _pdk_from_liberty(liberty)
        for nm in (lib, pdk):
            if nm and nm not in names:
                names.append(nm)
        # The stats field is the citation. A host-installed Liberty path is
        # machine-local and must not be copied into an emitted L document.
        src = src or _RUN_LIBERTY_FIELD
    if names:
        # The selected run must not overwrite contrary measured-library evidence.
        if selected_pdk:
            names.append(selected_pdk)
        return _cluster(out, names, src)
    if selected_pdk:
        # L7 is emitted before L19; its caller already validated this run choice.
        return _cluster(out, [selected_pdk], "caller::pdk")
    l19 = project / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json"
    try:
        doc = json.loads(l19.read_text(errors="replace"))
        fields = doc.get("fields") or {}
    except Exception:
        doc, fields = {}, {}
    if isinstance(fields, dict):
        for key in ("std_cell_library", "pdk_target"):
            v = fields.get(key)
            if isinstance(v, str) and v.strip():
                names.append(v.strip())
                src = src or f"{l19.relative_to(project)}::fields.{key}"
        # Existing producer evidence distinguishes an explicit run choice from
        # the first scalar name in an unselected multi-PDK document declaration.
        evidence = doc.get("extraction_evidence") or {}
        choices = evidence.get("command_line", []) if isinstance(evidence, dict) else []
        target = fields.get("pdk_target")
        claims = [row.get("literal")
                  for row in (choices if isinstance(choices, list) else [])
                  if isinstance(row, dict)
                  and row.get("label") == "pdk_target (explicit run choice)"]
        explicit = (isinstance(target, str) and bool(target.strip())
                    and claims == [f"--pdk {target}"])
        alts = fields.get("pdk_target_alternates")
        if not explicit and isinstance(alts, list):
            for v in alts:
                if isinstance(v, str) and v.strip():
                    names.append(v.strip())
                    src = src or (f"{l19.relative_to(project)}::"
                                  "fields.pdk_target_alternates")
    if not names:
        cfg = project / "config.json"
        try:
            data = json.loads(cfg.read_text(errors="replace"))
        except Exception:
            data = {}
        if isinstance(data, dict):
            for key in ("STD_CELL_LIBRARY", "PDK"):
                v = data.get(key)
                if isinstance(v, str) and v.strip():
                    names.append(v.strip())
                    src = src or f"{cfg.relative_to(project)}::{key}"
    if not names:
        for key in ("STD_CELL_LIBRARY", "PDK"):
            v = os.environ.get(key, "")
            if v.strip():
                names.append(v.strip())
                src = src or f"env::{key}"
    return _cluster(out, names, src)


def _cluster(out: Dict[str, object], names: Sequence[str],
             src: Optional[str]) -> Dict[str, object]:
    """Fill ``out`` from ``names``, refusing when they span two families."""
    uniq: List[str] = []
    for n in names:
        if n not in uniq:
            uniq.append(n)
    # CLUSTER BY FAMILY, NOT BY TOKEN EQUALITY. A project that states BOTH its
    # std-cell library and its PDK — the ordinary, well-declared case — states
    # two DIFFERENT tokens for ONE technology, and comparing the tokens for
    # equality read that as two families and refused. Measured on this file's
    # own resolver before the fix: library + its own PDK came back
    # `ambiguous: True`, which would have turned every properly-declared
    # project into NOT_DETERMINED and made the whole fix inert on the case it
    # exists for. `same_family` is the repo's one answer to "are these the same
    # technology" and it is the answer here too.
    clusters: List[List[str]] = []
    for n in uniq:
        for c in clusters:
            if same_family(n, c[0]) or family(n) == family(c[0]):
                c.append(n)
                break
        else:
            clusters.append([n])
    out["source"] = src
    if len(clusters) > 1:
        out["ambiguous"] = True
        out["note"] = (f"the project names {len(clusters)} technology families "
                       f"{[c[0] for c in clusters]} and has not chosen one, so "
                       "no run technology is determined here")
        return out
    out["candidates"] = uniq
    out["note"] = (f"resolved from {src}" if src else
                   "the project states no technology")
    return out


#: Where the L7 emitter publishes what it used, project-relative.
L7_FIELD = "area_signoff_baseline"


def resolve_for_run(project: Path, docs: Sequence[Tuple[str, str]],
                    *, metric: "Metric" = METRIC_CELL_AREA,
                    library: str = "", pdk: str = "",
                    reference_value: Optional[float] = None,
                    reference_cite: str = "") -> Dict[str, object]:
    """Resolve ``metric`` for a RUN, taking the technology the caller resolved.

    THE CALLER'S TECHNOLOGY WINS, and that is the whole point of this entry
    (vibe-ic#2147). A Phase-3 sign-off step knows the library it actually
    synthesised against; the project's own L-docs may name two families and
    have chosen neither. When the caller supplies nothing this falls back to
    what the project declares, which refuses when the project is ambiguous —
    never a silent pick.
    """
    cands = [c for c in (library, pdk) if c and str(c).strip()]
    if cands:
        tech = {"candidates": cands, "ambiguous": False,
                "source": "caller", "note": "supplied by the caller"}
    else:
        tech = run_technology(project)
    rep = resolve_texts(docs, [] if tech["ambiguous"] else tech["candidates"],
                        metric=metric, reference_value=reference_value,
                        reference_cite=reference_cite)
    if tech["ambiguous"]:
        rep["reason"] = "run_technology_ambiguous"
        rep["note"] = tech["note"]
    rep["run_technology"] = tech
    return rep


#: Where a design's L7-class input documents live, and what they are called.
L7_DOC_GLOBS: Sequence[str] = ("input/docs/**/L7*.md", "input/docs/**/L7*.txt",
                               "phase1/input_doc/L7*.txt",
                               "phase1/input_doc/L7*.md")


def l7_docs_of(project: Path) -> List[Tuple[str, str]]:
    """The ``(project-relative name, text)`` of every L7-class input document.

    A gate that has only a project path needs the same corpus the L7 emitter
    read, and it must be the SAME corpus: two definitions of "the L7 documents"
    is two answers to one question.
    """
    out: List[Tuple[str, str]] = []
    seen = set()
    for pat in L7_DOC_GLOBS:
        for f in sorted(project.glob(pat)):
            if not f.is_file():
                continue
            key = str(f.resolve())
            if key in seen:
                continue
            seen.add(key)
            try:
                out.append((str(f.relative_to(project)),
                            f.read_text(errors="ignore")))
            except (OSError, ValueError):
                continue
    return out


def resolve_for_project(project: Path, *,
                        metric: "Metric" = METRIC_CELL_AREA,
                        library: str = "", pdk: str = "",
                        reference_value: Optional[float] = None,
                        reference_cite: str = "") -> Dict[str, object]:
    """:func:`resolve_for_run` over the project's own L7 documents."""
    return resolve_for_run(project, l7_docs_of(project), metric=metric,
                           library=library, pdk=pdk,
                           reference_value=reference_value,
                           reference_cite=reference_cite)


def for_l7(project: Path, docs: Sequence[Tuple[str, str]], *,
           pdk: str = "") -> Optional[Dict]:
    """The block the L7 emitter writes, or None when the design states nothing.

    Returning None for a design that declares NEITHER sign-off is deliberate:
    the L7 documents of every such design stay byte-identical, so this
    disclosure adds a field exactly where there is something to disclose.

    The AREA resolution is the block itself — that is the shape #2136 shipped
    and its readers expect — and the POWER resolution rides in `power`, so one
    field carries both without either becoming a second answer to the other.
    """
    tech = run_technology(project, selected_pdk=pdk)
    cands = [] if tech["ambiguous"] else tech["candidates"]
    rep = resolve_texts(docs, cands, metric=METRIC_CELL_AREA)
    power = resolve_texts(docs, cands, metric=METRIC_TOTAL_POWER)
    if not (rep["signoff_row_found"] or power["signoff_row_found"]):
        return None
    if tech["ambiguous"]:
        for r in (rep, power):
            r["reason"] = "run_technology_ambiguous"
            r["note"] = tech["note"]
    rep["run_technology"] = tech
    power["run_technology"] = tech
    rep["power"] = power
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Resolve the sign-off threshold the design declares FOR "
                    "THIS RUN's technology, or refuse by name.")
    ap.add_argument("--docs-dir", help="the design's input/docs directory")
    ap.add_argument("--doc", action="append", default=[],
                    help="an explicit doc to read (repeatable)")
    ap.add_argument("--project", default=None,
                    help="a run directory; its own L7 documents are read")
    ap.add_argument("--metric", default=METRIC_CELL_AREA.key,
                    choices=sorted(METRICS), help="the quantity to resolve")
    ap.add_argument("--library", default="",
                    help="the std-cell library this run builds against")
    ap.add_argument("--pdk", default="", help="the PDK this run resolved")
    ap.add_argument("--reference-value", type=float, default=None,
                    help="a reference-netlist figure MEASURED in this run's "
                         "own cell library, in the metric's compare unit")
    ap.add_argument("--reference-area-um2", type=float, default=None,
                    help="#2136's name for --reference-value on the area metric")
    ap.add_argument("--reference-area-cite", default="")
    ap.add_argument("--reference-cite", default="")
    ap.add_argument("--measured", type=float, default=None,
                    help="this run's measured figure, in the compare unit")
    ap.add_argument("--measured-area-um2", type=float, default=None,
                    help="#2136's name for --measured on the area metric")
    ap.add_argument("--json", help="write the structured report here")
    args = ap.parse_args(argv)

    metric = METRICS[args.metric]
    docs: List[Tuple[str, str]] = []
    for d in [Path(x) for x in args.doc]:
        try:
            docs.append((str(d), d.read_text(errors="ignore")))
        except OSError:
            continue
    if args.docs_dir:
        d = Path(args.docs_dir)
        if d.is_dir():
            for f in sorted(x for x in d.rglob("*")
                            if x.is_file()
                            and x.suffix.lower() in (".md", ".txt")):
                try:
                    docs.append((str(f), f.read_text(errors="ignore")))
                except OSError:
                    continue
    project = Path(args.project) if args.project else Path(".")
    if args.project and not docs:
        docs = l7_docs_of(project)

    rep = resolve_for_run(
        project, docs, metric=metric, library=args.library, pdk=args.pdk,
        reference_value=(args.reference_value
                         if args.reference_value is not None
                         else args.reference_area_um2),
        reference_cite=args.reference_cite or args.reference_area_cite)
    rep["library"] = args.library
    rep["pdk"] = args.pdk
    measured = (args.measured if args.measured is not None
                else args.measured_area_um2)
    rep["verdict"] = verdict(rep, measured)
    if args.json:
        atomic_write_text(Path(args.json), json.dumps(rep, indent=2) + "\n")
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    # 0 = a threshold was resolved (and, if measured, met);
    # 1 = resolved and the measured figure exceeds it;
    # 2 = NOT_DETERMINED — no valid denominator for this run's technology.
    if not rep["determined"]:
        return 2
    return 1 if rep["verdict"]["verdict"] == FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
