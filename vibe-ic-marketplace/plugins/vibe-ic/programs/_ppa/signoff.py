#!/usr/bin/env python3
"""_ppa/signoff.py — the physical, reliability and equivalence feasibility axes,
read out of the sign-off artefacts the flow ALREADY writes.

WHY THIS MODULE EXISTS
======================
`_ppa/feasibility.py` proves nine axes from nine canonical metric names. Grep
each of those names across `programs/` and seven of them are produced by nothing
but `feasibility.py` itself — while a real run measures every one of them:

    DRC        0 items over 145 registered rule categories
    LVS        circuits match uniquely
    antenna    0 net / 0 pin violations
    IR         0.024 % of VDD against a declared 10 % budget
    EM         2431 segments analysed
    LEC        64/64 cells proven

None of it is in canonical record form, so the gate reads none of it, so no
candidate can ever be FEASIBLE, so "both sides feasible" — one of the four
conditions a head-to-head requires — can never hold. The evidence EXISTS and is
unreachable. That is what this module fixes, and it is the only thing it fixes.

WHAT IT WILL NOT DO
===================
**It never invents a number.** Every reader below answers one of two ways: the
artefact states the fact (`MEASURED`, with the value the artefact printed), or
it does not (`NOT_MEASURED`, with a reason naming what is missing). There is no
third branch. A missing producer is not a licence to write a zero, and a zero
written because nothing was read is the exact failure the whole PPA contract
exists to refuse.

**It never decides feasibility.** It emits records. `_ppa/feasibility.py` decides,
and it is the only thing that decides. Two modules that both know what "clean"
means is how the two of them come to disagree.

**It never re-derives a rule another program owns.** DRC's three-way
discriminator is `fixtures/ppa/drc/zero_three_ways/expected.json`'s decision
table, implemented here as that table and not as an eleventh near-miss of it.
The layout shape count it needs comes from `drc_vacuous_pass_check`'s own
artefact, because that program already measures it and a second measurement
would be a second answer.

WHAT A ZERO HAS TO EARN
=======================
`reports/phase3/drc_signoff.json` saying `real_violation_total: 0` is not
sufficient to emit `physical.drc.violations = 0`. The fixture tree proves why:
`ran_and_found_none/drc.xml` and `ran_on_empty_layout/drc.xml` are BYTE-IDENTICAL
(sha256:0abbbf4d…, 702 bytes each) — one is a real deck over real geometry, the
other the same deck over a layout with no shapes in it. No parser of the report
can tell them apart because the answer is not in the report. So the DRC reader
requires all three facts — categories registered, items counted, shapes measured
— and emits `NOT_MEASURED` naming which one was missing when it cannot.

Antenna, IR and equivalence each carry the same shape of trap and each is
refused the same way: `antenna.json` with `routing_incomplete: true` is a check
over a design the router did not finish; `ir_drop.json` with no declared budget
supports no violation count; `lec.json` proving RTL against a PRE-layout netlist
establishes nothing about the netlist that became the GDS.

STAGE
=====
`_ppa/metrics.py` requires `scope.stage`, and none of these artefacts states one.
It is NOT guessed: each source declares the stage of the flow step that writes it
together with a `stage_basis` sentence naming the input that makes it that stage,
and both are carried into the record's `provenance`. A reader who disagrees can
see exactly what the claim rests on. Fabricating a stage would make two
incomparable numbers look comparable, which is what `scope` exists to prevent.

CORNER-INDEPENDENCE
===================
DRC, LVS, antenna, IR, EM and equivalence are single measurements over one
database. They are NOT emitted once per timing corner. A contract that wants them
adjudicated declares their views under `required_views_by_axis` (see
`_ppa/feasibility.policy_from_document`); duplicating one measurement under N
fabricated corner scopes to make it addressable would put N records carrying one
source hash into an index whose whole job is to notice when two numbers claim to
be the same fact.

chip/PDK/vendor-AGNOSTIC: no design, PDK, foundry or tool version literal
decides anything here. Every value comes from the run's own artefacts.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_METRIC = "vibeic.ppa.metric.v1"
SCHEMA_BUNDLE = "vibeic.ppa.signoff_records.v1"

MEASURED = "MEASURED"
NOT_MEASURED = "NOT_MEASURED"

PARSER = "_ppa/signoff.py"

#: The verdict literals `_ppa/feasibility.py`'s LVS and equivalence axes accept.
#: Named here so this module cannot drift from the gate it feeds; the gate is
#: still the only thing that adjudicates them.
LVS_MATCH = "MATCH"
EQUIVALENCE_PROVEN = "PROVEN"


# ---------------------------------------------------------------------------
# a reading
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Reading:
    """What one artefact supports for one metric. `MEASURED` xor a reason.

    There is no field for "probably zero". A reader returns a value or it
    returns why it could not, and the constructor below is what makes those the
    only two shapes a record can take.
    """
    status: str
    value: Any = None
    reason: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @staticmethod
    def measured(value: Any, **prov: Any) -> "Reading":
        return Reading(MEASURED, value, "", dict(prov))

    @staticmethod
    def absent(reason: str, **prov: Any) -> "Reading":
        return Reading(NOT_MEASURED, None, reason, dict(prov))


Reader = Callable[[Optional[Mapping[str, Any]], "RunTree"], Reading]


@dataclass(frozen=True)
class Source:
    """One canonical metric, the artefact it is read from, and how.

    `stage` and `stage_basis` travel together on purpose. A stage with no stated
    basis is an assertion; with one it is a claim a reader can check against the
    flow step that wrote the file.
    """
    metric: str
    unit: str
    rel: str
    tool: str
    stage: str
    stage_basis: str
    reader: Reader


# ---------------------------------------------------------------------------
# the run tree
# ---------------------------------------------------------------------------
class RunTree:
    """Read-only access to one run directory, with hashing and caching.

    Caching matters for correctness and not only for speed: two readers over one
    artefact must see one document and cite one digest, or the index they feed
    will see two facts where the run produced one.
    """

    def __init__(self, root: "str | pathlib.Path") -> None:
        self.root = pathlib.Path(root)
        self._docs: Dict[str, Any] = {}
        self._shas: Dict[str, Optional[str]] = {}

    def sha256(self, rel: str) -> Optional[str]:
        if rel not in self._shas:
            try:
                data = (self.root / rel).read_bytes()
            except OSError:
                self._shas[rel] = None
            else:
                self._shas[rel] = "sha256:" + hashlib.sha256(data).hexdigest()
        return self._shas[rel]

    def json(self, rel: str) -> Optional[Mapping[str, Any]]:
        """The document, or None — which covers absent, unreadable AND not-JSON.

        The three are collapsed HERE and separated by the caller, which checks
        `sha256(rel)` first: a file that hashes but does not parse is a different
        finding from a file that is not there, and both are NOT_MEASURED with
        different reasons.
        """
        if rel not in self._docs:
            try:
                doc = json.loads((self.root / rel).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = None
            self._docs[rel] = doc if isinstance(doc, Mapping) else None
        return self._docs[rel]


# ---------------------------------------------------------------------------
# helpers -- deliberately strict about what counts as a number
# ---------------------------------------------------------------------------
def _int(v: Any) -> Optional[int]:
    """An int, or None. `True` is not 1 here: a boolean count is a parse defect."""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


# ---------------------------------------------------------------------------
# DRC -- the three-way discriminator, implemented as the fixture's table
# ---------------------------------------------------------------------------
#: `fixtures/ppa/drc/zero_three_ways/expected.json`'s `discriminator.rules`,
#: in order. The fixture states it as a decision table precisely so that every
#: lane implements the same rule; this is that table and the fixture is the test.
DRC_DISCRIMINATOR = (
    ("items > 0", "the deck reported items -- a violation count, not a clean"),
    ("categories == 0", "deck registered no rule"),
    ("categories > 0 and items == 0 and shapes == 0", "nothing was checked"),
    ("categories > 0 and items == 0 and shapes > 0", "earned clean"),
)


def _drc_shapes(run: RunTree) -> Tuple[Optional[int], str]:
    """The largest shape count `drc_vacuous_pass_check` measured, and where.

    Largest and not sum: the artefact carries one measurement per candidate
    layout file it bound, and the question the discriminator asks is "did the
    deck run over geometry at all", which one populated layout answers. Summing
    would let a dozen empty layouts add up to a non-zero.
    """
    doc = run.json(DRC_VACUITY_REL)
    if not isinstance(doc, Mapping):
        return None, f"{DRC_VACUITY_REL} is absent, unreadable or not a document"
    summary = doc.get("summary")
    if not isinstance(summary, Mapping):
        return None, f"{DRC_VACUITY_REL} carries no `summary`"
    per_file = summary.get("per_file")
    if not isinstance(per_file, Sequence) or isinstance(per_file, (str, bytes)):
        return None, f"{DRC_VACUITY_REL} carries no `summary.per_file` list"
    best: Optional[int] = None
    for entry in per_file:
        if not isinstance(entry, Mapping):
            continue
        for m in (entry.get("layout_measures") or []):
            if not isinstance(m, Mapping):
                continue
            n = _int(m.get("shapes"))
            if n is not None and (best is None or n > best):
                best = n
    if best is None:
        return None, (f"{DRC_VACUITY_REL} bound no layout and therefore measured "
                      "no shapes; the deck's zero cannot be told from a deck "
                      "that ran over nothing")
    return best, ""


def read_drc(doc: Optional[Mapping[str, Any]], run: RunTree) -> Reading:
    """`physical.drc.violations`, and only when the zero is EARNED.

    Three facts are needed and the report carries two of them. The third —
    whether the layout the deck ran over contained geometry — is not in the
    report and never can be (the fixture's two byte-identical reports are the
    proof), so it is read from the vacuity artefact. Missing any one of the three
    is NOT_MEASURED naming which.
    """
    if not isinstance(doc, Mapping):
        return Reading.absent("the DRC sign-off artefact is absent, unreadable "
                              "or not a document")
    summary = doc.get("summary")
    if not isinstance(summary, Mapping):
        return Reading.absent("the DRC sign-off artefact carries no `summary`")
    cats = summary.get("categories_found")
    n_cats = len(cats) if isinstance(cats, Sequence) and not isinstance(
        cats, (str, bytes)) else None
    items = _int(summary.get("real_violation_total"))
    shapes, shapes_why = _drc_shapes(run)
    prov = {"categories_found": n_cats, "real_violation_total": items,
            "layout_shapes": shapes,
            "discriminator": "fixtures/ppa/drc/zero_three_ways"}

    if items is None:
        return Reading.absent(
            "the DRC sign-off artefact carries no integer "
            "`summary.real_violation_total`, so it states no item count",
            **prov)
    # Rule 1. A measured item count is a fact about the design and it stands
    # whatever the vacuity evidence says -- items cannot be reported by a deck
    # that never ran.
    if items > 0:
        return Reading.measured(items, rule=DRC_DISCRIMINATOR[0][0], **prov)
    if n_cats is None:
        return Reading.absent(
            "the DRC sign-off artefact carries no `summary.categories_found`, "
            "so it cannot be told whether the deck registered any rule at all",
            **prov)
    # Rule 2. Zero items from a deck that registered zero rules is not a clean:
    # there were no rules to violate.
    if n_cats == 0:
        return Reading.absent(
            "the deck registered ZERO rule categories, so a zero item count "
            "cannot be an earned clean -- there were no rules to violate "
            "(fixtures/ppa/drc/zero_three_ways: deck_never_ran)", **prov)
    if shapes is None:
        return Reading.absent(
            "the layout the deck ran over could not be measured, so a zero item "
            "count cannot be told from a deck that ran over nothing: "
            + shapes_why, **prov)
    # Rule 3. Zero items over a layout with no shapes is a statement about the
    # layout, not about the design.
    if shapes <= 0:
        return Reading.absent(
            "the layout the deck ran over contains no measured shapes, so a "
            "zero item count is a statement about the layout being empty "
            "(fixtures/ppa/drc/zero_three_ways: ran_on_empty_layout)", **prov)
    # Rule 4. All three facts present and consistent: the zero is earned.
    return Reading.measured(
        0, rule=DRC_DISCRIMINATOR[3][0],
        earned=f"{n_cats} rule categories over a layout of {shapes} shapes",
        **prov)


# ---------------------------------------------------------------------------
# LVS -- a VERDICT, with the top-level circuit it is about
# ---------------------------------------------------------------------------
def read_lvs(doc: Optional[Mapping[str, Any]], run: RunTree) -> Reading:
    """`physical.lvs.verdict` — never a count.

    LVS answers "do these two circuits match, and which circuit was compared".
    It does not produce a violation count, and encoding "matched" as the integer
    0 would put a number where a verdict belongs and invite a downstream reader
    to do arithmetic on it. The axis proves this metric with `verdict_in`, so the
    record carries the verdict; the top-level circuit rides in `provenance`,
    because a match between two circuits nobody named is not a fact about this
    design.
    """
    if not isinstance(doc, Mapping):
        return Reading.absent("the LVS verdict artefact is absent, unreadable "
                              "or not a document")
    raw = doc.get("status")
    if raw is None:
        raw = doc.get("result")
    status = str(raw or "").strip().upper()
    top = doc.get("top_cell") or doc.get("top") or doc.get("cell")
    prov = {"declared_status": status or None, "top_cell": top,
            "finding": doc.get("finding")}
    if not status:
        return Reading.absent(
            "the LVS verdict artefact declares no `status` and no `result`, so "
            "it states no verdict", **prov)
    if status == "PASS":
        # PASS is the runner's spelling; MATCH is the axis's. Translating here
        # rather than widening the axis keeps ONE list of what an LVS pass looks
        # like, and it lives in the gate.
        return Reading.measured(LVS_MATCH, **prov)
    # Everything else is reported VERBATIM. INCOMPLETE and WARN are not
    # failures and must not be mapped to one; they are verdicts the axis does
    # not accept, which is a different sentence and a different fix.
    return Reading.measured(status, **prov)


# ---------------------------------------------------------------------------
# antenna
# ---------------------------------------------------------------------------
def read_antenna(doc: Optional[Mapping[str, Any]], run: RunTree) -> Reading:
    """`physical.antenna.violations` — net + pin, and only over a routed design.

    An antenna check over an incompletely routed design has not checked the
    design that would be manufactured, so its zero is not this design's zero.
    The runner records that state in its own artefact and it is honoured here
    rather than being read past.
    """
    if not isinstance(doc, Mapping):
        return Reading.absent("the antenna artefact is absent, unreadable or "
                              "not a document")
    prov = {"mode": doc.get("mode"),
            "net_violations": doc.get("net_violations"),
            "pin_violations": doc.get("pin_violations"),
            "routing_incomplete": doc.get("routing_incomplete"),
            "pins_unaccessed": doc.get("pins_unaccessed")}
    if doc.get("routing_incomplete"):
        return Reading.absent(
            "the antenna check ran on an incompletely routed design, so its "
            "count is not a count for the design that would be manufactured",
            **prov)
    nets, pins = _int(doc.get("net_violations")), _int(doc.get("pin_violations"))
    if nets is None or pins is None:
        # The runner writes null for both when it could not read counts out of
        # the tool log. Null is not zero and is not read as zero.
        return Reading.absent(
            "the antenna artefact carries no integer `net_violations` and "
            "`pin_violations` pair, so it states no violation count", **prov)
    return Reading.measured(nets + pins, **prov)


# ---------------------------------------------------------------------------
# IR drop -- a count against a DECLARED budget, and the drop itself
# ---------------------------------------------------------------------------
def read_ir_violations(doc: Optional[Mapping[str, Any]], run: RunTree) -> Reading:
    """`power.ir.violations` — 0 or 1 against the budget the artefact declares.

    The budget is never supplied here. The artefact carries `budget_pct_vdd` and
    the basis it came from; without it there is no line to be over and no
    violation count can exist, so the reading is NOT_MEASURED. A default budget
    invented in this file would be a design-specific number living in
    chip-agnostic source, and would turn every unmeasured supply into a pass.
    """
    if not isinstance(doc, Mapping):
        return Reading.absent("the IR artefact is absent, unreadable or not a "
                              "document")
    worst, budget = _num(doc.get("worst_ir_pct_vdd")), _num(doc.get("budget_pct_vdd"))
    prov = {"worst_ir_pct_vdd": worst, "budget_pct_vdd": budget,
            "budget_basis": doc.get("budget_basis"),
            "supply_measured": doc.get("supply_measured"),
            "supply_model": doc.get("supply_model")}
    if doc.get("supply_measured") is False:
        return Reading.absent(
            "the IR artefact reports that the supply voltage was NOT measured, "
            "so its drop has no percentage-of-VDD reading and no budget to be "
            "compared against", **prov)
    if worst is None:
        return Reading.absent(
            "the IR artefact states no `worst_ir_pct_vdd`", **prov)
    if budget is None:
        return Reading.absent(
            "the IR artefact declares no `budget_pct_vdd`, so there is no line "
            "for the measured drop to be over and no violation count exists",
            **prov)
    return Reading.measured(0 if worst <= budget else 1, **prov)


def read_ir_worst_drop(doc: Optional[Mapping[str, Any]], run: RunTree) -> Reading:
    """`power.ir.worst_drop_v` — the drop in volts, budget or no budget.

    Emitted separately because the axis's second proof group compares it against
    a limit the CONTRACT declares. That path works on a run whose artefact
    carries no budget of its own, which is why the two are not folded together.
    """
    if not isinstance(doc, Mapping):
        return Reading.absent("the IR artefact is absent, unreadable or not a "
                              "document")
    uv = _num(doc.get("worst_ir_uv"))
    prov = {"worst_ir_uv": uv, "supply_voltage_v": doc.get("supply_voltage_v"),
            "supply_measured": doc.get("supply_measured")}
    if uv is None:
        return Reading.absent("the IR artefact states no `worst_ir_uv`", **prov)
    return Reading.measured(uv / 1e6, conversion="worst_ir_uv / 1e6", **prov)


# ---------------------------------------------------------------------------
# EM -- the count is in the DENSITY screen, not in the measurement emitter
# ---------------------------------------------------------------------------
def _em_screen(run: RunTree) -> Tuple[Optional[Mapping[str, Any]], str]:
    """The current-density screen's report, or why there isn't one."""
    for rel in EM_SCREEN_RELS:
        doc = run.json(rel)
        if isinstance(doc, Mapping):
            return doc, rel
    return None, ""


def read_em_violations(doc: Optional[Mapping[str, Any]], run: RunTree) -> Reading:
    """`reliability.em.violations` — from the density screen, never from em.json.

    `reports/phase3/em.json` is a MEASUREMENT emitter: it states how many
    segments were analysed and the maximum segment current, and it says so in
    its own payload (`verdict: "MEASURED"`, with a comment that the sign-off
    PASS/FAIL is decided downstream). It carries no violation count and no
    current limit, and "the tool reported no violations" is not what it says. A
    zero read off it would be exactly the vacuous pass the fixture tree exists
    to prevent.

    The count exists in `em_current_density_check.py`'s report, which screens
    every segment against the PDK's Jmax and lists the offenders. Its SKIPPED
    verdict — report present, Jmax present, nothing mapped — is carried through
    as NOT_MEASURED with the screen's own message, never as a clean.
    """
    screen, rel = _em_screen(run)
    if screen is None:
        return Reading.absent(
            "no current-density screen report was found (looked for "
            + ", ".join(EM_SCREEN_RELS) + "). The EM measurement artefact "
            "carries a segment count and a maximum segment current but NO "
            "violation count and NO declared current limit, so no violation "
            "count can be established from it: run "
            "`em_current_density_check.py <em_report> --tech-lef … --json …`")
    verdict = str(screen.get("verdict") or "").upper()
    summary = screen.get("summary") if isinstance(
        screen.get("summary"), Mapping) else {}
    prov = {"screen_artefact": rel, "screen_verdict": verdict,
            "margin": screen.get("margin"),
            "segments_screened": summary.get("segments_screened"),
            "segments_unscreened": summary.get("segments_unscreened"),
            "worst_utilization": summary.get("worst_utilization")}
    if verdict == "SKIPPED":
        return Reading.absent(
            "the current-density screen returned SKIPPED, which is a "
            "could-not-judge and never a clean: "
            + _first_message(screen), **prov)
    if verdict == "FAIL":
        n = _int(screen.get("offender_count"))
        if n is None:
            return Reading.absent(
                "the current-density screen returned FAIL but states no "
                "integer `offender_count`", **prov)
        return Reading.measured(n, **prov)
    if verdict == "PASS":
        # PASS means every SCREENED segment was under the margined Jmax. The
        # screen states how many it could not screen, and that number rides
        # along: a pass over 3 of 2431 segments is a different fact from a pass
        # over all of them, and the reader is entitled to see which it got.
        return Reading.measured(0, **prov)
    return Reading.absent(
        f"the current-density screen states verdict {verdict or 'nothing'!r}, "
        "which is neither PASS, FAIL nor SKIPPED", **prov)


def read_em_worst_ratio(doc: Optional[Mapping[str, Any]], run: RunTree) -> Reading:
    """`reliability.em.worst_ratio` — J / Jmax, for the contract-limit proof.

    `worst_utilization` is already that ratio (unit 1), so the axis's
    `limit_max` group can be proved against a limit the contract declares even
    on a run whose screen margin differs from the contract's.
    """
    screen, rel = _em_screen(run)
    if screen is None:
        return Reading.absent(
            "no current-density screen report was found, so no J/Jmax ratio "
            "exists (looked for " + ", ".join(EM_SCREEN_RELS) + ")")
    summary = screen.get("summary") if isinstance(
        screen.get("summary"), Mapping) else {}
    ratio = _num(summary.get("worst_utilization"))
    prov = {"screen_artefact": rel, "screen_verdict": screen.get("verdict"),
            "segments_screened": summary.get("segments_screened")}
    if ratio is None:
        return Reading.absent(
            "the current-density screen states no `summary.worst_utilization`, "
            "so no segment was screened against a Jmax and no ratio exists",
            **prov)
    return Reading.measured(ratio, **prov)


def _first_message(doc: Mapping[str, Any]) -> str:
    for f in (doc.get("findings") or []):
        if isinstance(f, Mapping) and f.get("message"):
            return str(f["message"])
    return "the screen states no message"


# ---------------------------------------------------------------------------
# equivalence -- RTL against WHICH netlist
# ---------------------------------------------------------------------------
#: A gate-netlist name containing one of these is a post-layout netlist. Matched
#: on the netlist the proof itself names, never on the directory the report was
#: filed in: the run that produced F-16 filed a pre-layout proof under a
#: post-layout report path.
_POST_LAYOUT_TOKENS = ("pnr", "route", "routed", "postlayout", "post_layout")


def read_equivalence(doc: Optional[Mapping[str, Any]], run: RunTree) -> Reading:
    """`equivalence.verdict` — and about the netlist that became the GDS.

    A logical-equivalence proof of RTL against the SYNTHESIS netlist is a real
    and useful proof, and it is not this axis. The gate side of the proof has to
    be the routed netlist, or the proof says nothing about what was streamed.
    Measured on a real run: `reports/lec.json` proved RTL against a post-DFT
    synthesis netlist and the run's own post-layout LEC step failed outright, so
    a `PROVEN` read off that file would have been a claim about a different
    netlist.
    """
    if not isinstance(doc, Mapping):
        return Reading.absent("the LEC artefact is absent, unreadable or not a "
                              "document")
    gate = str(doc.get("gate") or doc.get("gate_netlist") or "")
    verdict = str(doc.get("verdict") or "").upper()
    prov = {"declared_verdict": verdict or None, "gate": gate or None,
            "equivalent": doc.get("equivalent"), "golden": doc.get("golden")}
    if not verdict:
        return Reading.absent("the LEC artefact declares no `verdict`", **prov)
    if verdict != "PASS" or not doc.get("equivalent"):
        # A failed or inconclusive proof is a MEASURED verdict the axis does not
        # accept. Reporting it as NOT_MEASURED would hide a real finding behind
        # "could not check".
        return Reading.measured(verdict, **prov)
    if not gate:
        return Reading.absent(
            "the LEC artefact proves an equivalence but names no gate netlist, "
            "so it cannot be told whether the proven pair involved the netlist "
            "that became the layout", **prov)
    if not any(t in gate.lower() for t in _POST_LAYOUT_TOKENS):
        return Reading.absent(
            f"the proven pair is RTL against {gate!r}, which names no "
            "post-layout netlist. The routed netlist that became the layout was "
            "not the gate side of this proof, so it establishes no post-route "
            "equivalence", **prov)
    return Reading.measured(EQUIVALENCE_PROVEN, **prov)


# ---------------------------------------------------------------------------
# where the flow puts these
# ---------------------------------------------------------------------------
DRC_SIGNOFF_REL = "reports/phase3/drc_signoff.json"
DRC_VACUITY_REL = "reports/phase3/drc_vacuous.json"
LVS_REL = "reports/phase3/lvs_verdict.json"
ANTENNA_REL = "reports/phase3/antenna.json"
IR_REL = "reports/phase3/ir_drop.json"
EM_REL = "reports/phase3/em.json"
LEC_REL = "reports/lec.json"

#: The current-density screen writes wherever `--json` points. These are the
#: names the flow and its docs use, in preference order; the first that parses
#: wins and the record names which one it was.
EM_SCREEN_RELS: Tuple[str, ...] = (
    "reports/phase3/em_current_density.json",
    "reports/phase3/em_density.json",
    "reports/phase3/em_signoff.json",
)

SOURCES: Tuple[Source, ...] = (
    Source("physical.drc.violations", "count", DRC_SIGNOFF_REL, "klayout",
           "signed_off_gds",
           "the sign-off DRC deck is applied to the streamed layout, so its "
           "verdict is about the geometry that would be manufactured",
           read_drc),
    Source("physical.lvs.verdict", "verdict", LVS_REL, "netgen",
           "post_route_extracted",
           "LVS compares the netlist EXTRACTED from the routed layout against "
           "the gate netlist, so the measurement stands on the extraction",
           read_lvs),
    Source("physical.antenna.violations", "count", ANTENNA_REL, "openroad",
           "post_route",
           "the antenna check runs over the routed design database; it needs "
           "no extracted parasitics, so it is post_route and not "
           "post_route_extracted",
           read_antenna),
    Source("power.ir.violations", "count", IR_REL, "openroad-psm",
           "post_route",
           "static IR is solved over the routed power grid; the solve reads the "
           "routed database and no SPEF",
           read_ir_violations),
    Source("power.ir.worst_drop_v", "V", IR_REL, "openroad-psm",
           "post_route",
           "same solve as `power.ir.violations`, reported in volts rather than "
           "as a count against the artefact's own budget",
           read_ir_worst_drop),
    Source("reliability.em.violations", "count", EM_REL, "openroad-psm",
           "post_route",
           "the per-segment currents are solved over the routed power grid; the "
           "screen that turns them into a count reads that same solve",
           read_em_violations),
    Source("reliability.em.worst_ratio", "1", EM_REL, "openroad-psm",
           "post_route",
           "same solve as `reliability.em.violations`, as the worst J/Jmax "
           "ratio rather than as a count against the screen's own margin",
           read_em_worst_ratio),
    Source("equivalence.verdict", "verdict", LEC_REL, "yosys",
           "post_route",
           "the axis is about the netlist that became the layout, so the stage "
           "is the routed one; a proof over a pre-layout gate netlist is "
           "refused by the reader rather than filed under an earlier stage",
           read_equivalence),
)


# ---------------------------------------------------------------------------
# record construction
# ---------------------------------------------------------------------------
def _parser_sha256() -> str:
    return "sha256:" + hashlib.sha256(
        pathlib.Path(__file__).read_bytes()).hexdigest()


#: What a record cites for provenance when the artefact it names is not there.
#: 64 zeros is a well-formed digest of nothing and it is deliberately NOT a real
#: hash: it can never collide with a file, so an index that ever compares two of
#: them is comparing two absences.
ABSENT_DIGEST = "sha256:" + "0" * 64


def _record(src: Source, reading: Reading, digest: Optional[str],
            scope_extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """One `vibeic.ppa.metric.v1` record. MEASURED carries a value; nothing else does.

    `scope` never carries a None or an empty string. `_ppa/metrics.py` refuses
    those as sentinels — two records with an unknown corner would otherwise
    compare as the SAME corner — so a key whose value is unknown is left out and
    the reason is recorded in `provenance` instead.
    """
    scope: Dict[str, Any] = {"stage": src.stage, "tool": src.tool}
    for k, v in (scope_extra or {}).items():
        if v is not None and v != "":
            scope[k] = v
    rec: Dict[str, Any] = {
        "schema": SCHEMA_METRIC,
        "metric": src.metric,
        "status": reading.status,
        "unit": src.unit,
        "scope": scope,
        "source": {"path": src.rel, "sha256": digest or ABSENT_DIGEST,
                   "tool": src.tool, "parser": PARSER,
                   "parser_sha256": _parser_sha256()},
        "provenance": {"stage_basis": src.stage_basis,
                       **{k: v for k, v in (reading.provenance or {}).items()}},
    }
    if reading.status == MEASURED:
        rec["value"] = reading.value
    else:
        rec["reason"] = reading.reason or "the artefact does not support this metric"
    return rec


def build_records(run: "str | pathlib.Path | RunTree",
                  sources: Sequence[Source] = SOURCES
                  ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Every source's record, plus a per-source note. Never fewer than one each.

    A source whose artefact is absent gets a NOT_MEASURED record and NOT an
    omitted one: §2 — "a report prints the literal NOT_MEASURED row; it does not
    omit it". An omitted row and a met row look the same to anything that scans a
    table for violations and finds none.
    """
    tree = run if isinstance(run, RunTree) else RunTree(run)
    records: List[Dict[str, Any]] = []
    notes: List[Dict[str, Any]] = []
    for src in sources:
        digest = tree.sha256(src.rel)
        doc = tree.json(src.rel)
        if digest is None:
            reading = Reading.absent(
                f"{src.rel} is absent or unreadable: this is NOT_MEASURED and "
                "it is not a zero")
        elif doc is None:
            reading = Reading.absent(
                f"{src.rel} exists ({digest}) but is not a JSON object, so it "
                "states nothing this metric can be read from")
        else:
            reading = src.reader(doc, tree)
        records.append(_record(src, reading, digest))
        notes.append({"metric": src.metric, "status": reading.status,
                      "artefact": src.rel, "present": digest is not None,
                      "reason": reading.reason or None})
    return records, notes


def bundle(run: "str | pathlib.Path | RunTree",
           sources: Sequence[Source] = SOURCES) -> Dict[str, Any]:
    """The records as a document, with the census a reader needs to judge it.

    `measured` / `not_measured` are counted here rather than left to the caller
    so that a report of this run cannot quote a different census from the one
    the records support.
    """
    tree = run if isinstance(run, RunTree) else RunTree(run)
    records, notes = build_records(tree, sources)
    measured = [r for r in records if r["status"] == MEASURED]
    return {
        "schema": SCHEMA_BUNDLE,
        "run": str(tree.root),
        "parser": PARSER,
        "parser_sha256": _parser_sha256(),
        "census": {"records": len(records), "measured": len(measured),
                   "not_measured": len(records) - len(measured)},
        "notes": notes,
        "records": records,
    }
