#!/usr/bin/env python3
"""signoff_metrics_aggregate.py — write the sign-off metrics THIS flow measured.

ENFORCEMENT: blocking

The declaration is TRUE of this program and of how it is wired, and both halves
had to be made true together. Step 37.4's gate clause is a plain
``program_exit_zero``, so the flow blocks on ``--check``; but until
``phase3_one_shot_runner.step_signoff_metrics_aggregate`` existed, NO runner
spawned this program at all, so its verdict could not stop the step it guards
and `flow_gate_enforcement_audit` classified it AUDIT_ONLY. Declaring
``blocking`` over that wiring would have been a contradiction — the exact shape
that register refuses. The runner now spawns it inline and branches on the
status, so the claim above is one the audit can check rather than one it has to
take on trust.

WHY THIS PROGRAM EXISTS
=======================
Four programs read ``phase3/final/metrics.json`` and NOTHING wrote it. Measured
at v1.16.2 over the whole worktree::

    grep -rn "final/metrics.json"  ->  5 readers, 0 writers
      tapeout_docs_gen.py:392   ic_release_docs_gen.py:146
      _ic_release_artefacts.py:12   release_docs_check.py:851
      flow/phase1_phase2_phase3.yaml (a comment)

``phase3/final/`` was not even a directory ``_path_layout`` defined; no run tree
and no published benchmark-data cell contains one. The 18 keys those readers
want are OpenLane-2 / LibreLane metric names, and this flow drives OpenROAD,
magic, netgen, KLayout and OpenSTA DIRECTLY -- it never runs LibreLane's Classic
flow, which is the thing that would have written that file. So step 37.5ic could
not produce ONE of its six document outputs for ANY design: not spm, not sha256,
not aes. Completing a route does not change that, because the missing artefact is
not a layout, it is the summary of the checks that were run ON the layout.

Every number those 18 keys ask for is ALREADY on the tree, in the per-checker
report the checker itself wrote. This program is the aggregator over exactly
those reports, and nothing else. It measures nothing itself and re-decides
nothing: it reads a verdict a checker already recorded and copies it under the
name the document generators read.

THE THREE RULES THIS PROGRAM IS BUILT ON
========================================
1.  **A key whose source is absent is NOT_MEASURED, with the reason, and it is
    still WRITTEN.** Never a default, never omitted. A downstream reader must be
    able to tell "measured 0" from "nobody looked"; those two are the difference
    between a clean sign-off and a document that launders an empty run
    (`_ic_release_artefacts` exists because that exact laundering was measured).
    Omitting the key is the same lie by another route: `tapeout_docs_gen.g`
    returns NOT_MEASURED for an absent key too, so a reader cannot distinguish
    "this run had no antenna report" from "this aggregator has no rule for
    antenna". Written-with-a-reason can be distinguished; absent cannot.

2.  **Every key carries provenance**: the project-relative source path and its
    sha256, in ``__provenance__`` inside the metrics file and in full in
    ``reports/phase3/signoff_metrics_aggregate.json``. A number in a datasheet
    whose report nobody can name is a number nobody can check.

3.  **Attribution is READ, never guessed from a filename.** The DRC keys are
    per-TOOL (`magic__`, `klayout__`, `route__`) and this flow's DRC audit
    records the tool in ``summary.producers[].producer``. A filename is a
    convention; the producer field is the audit's own measurement. Never bridge
    one tool's count to another tool's key -- the router reporting 0 while the
    KLayout sign-off deck reports 2 real violations is a MEASURED state of this
    flow, and renaming one into the other is how it disappears.

WHAT IT DOES NOT DO
===================
* It does not decide whether the design is releasable. ``release_blockers``
  in `tapeout_docs_gen` owns that verdict and this program never anticipates it:
  a run with dirty metrics gets a metrics file stating exactly how dirty.
* It does not re-run or re-judge any checker. If two checkers disagree, both
  are reported under their own keys and the disagreement stays visible.
* It does not fail the run. Exit 0 with the file written is the answer for a
  tree with no reports at all -- every key NOT_MEASURED with the reason. Exit 2
  is reserved for a project directory that does not exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl  # noqa: E402
# BOTH DECLARED ARTEFACTS GO OUT THROUGH THE ATOMIC WRITER (vibe-ic#1082/#1470).
# `phase3/final/metrics.json` and `reports/phase3/signoff_metrics_aggregate.json`
# are DECLARED report destinations -- five programs read the first of them -- and
# a declared destination written with a plain `write_text` is a file a reader can
# catch half-written or, on a serialisation error, find truncated in place.
# `atomic_artifact_write_check` names exactly that and it named this program.
import _atomic_artefact as _atomic  # noqa: E402

NOT_MEASURED = "NOT_MEASURED"
SCHEMA = "vibeic.signoff_metrics.v1"
REPORT_REL = "reports/phase3/signoff_metrics_aggregate.json"


# ── the measured cell ────────────────────────────────────────────────────────
class Cell:
    """One key's answer: a value, or NOT_MEASURED with the reason it is."""

    __slots__ = ("value", "source", "reason", "basis")

    def __init__(self, value, source: str = "", reason: str = "",
                 basis: str = ""):
        self.value = value
        self.source = source
        self.reason = reason
        self.basis = basis

    @property
    def measured(self) -> bool:
        return self.value != NOT_MEASURED


def unmeasured(reason: str, source: str = "") -> Cell:
    return Cell(NOT_MEASURED, source, reason)


def _sha256(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:
        return ""


def _json(project: Path, rel: str) -> Optional[dict]:
    p = project / rel
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _text(project: Path, rel: str) -> Optional[str]:
    p = project / rel
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


# ── DRC: one rule per TOOL, attributed by the audit's own producer field ─────
#: The DRC audit reports this flow writes. Both are read for EVERY DRC key --
#: which key a report answers is decided by the producer it RECORDS, not by
#: which of these two names it has.
_DRC_AUDITS = ("reports/phase3/drc_signoff.json", "reports/phase3/drc_router.json")


def _drc_for_tool(project: Path, tool: str) -> Cell:
    """``real_violation_total`` from the DRC audit whose producer IS ``tool``.

    `real_violation_total` and not `summary_violation_total`: the audit
    distinguishes what a report's own summary line CLAIMS from what its records
    corroborate, and the corroborated total is the one a sign-off document may
    state. Two audits attributed to the same tool is a contradiction this
    program reports rather than resolves by picking.
    """
    hits = []
    for rel in _DRC_AUDITS:
        d = _json(project, rel)
        if not d:
            continue
        summary = d.get("summary") or {}
        for prod in (summary.get("producers") or []):
            if (prod.get("producer") or "").lower() != tool:
                continue
            total = summary.get("real_violation_total")
            if isinstance(total, bool) or not isinstance(total, int):
                continue
            hits.append((rel, total))
            break
    if not hits:
        seen = sorted({(p.get("producer") or "unattributed")
                       for rel in _DRC_AUDITS
                       for p in ((_json(project, rel) or {}).get("summary")
                                 or {}).get("producers", [])})
        return unmeasured(
            f"no DRC report in this run is attributed to {tool!r} "
            f"(producers found: {', '.join(seen) if seen else 'none'}), so this "
            f"run carries no {tool} DRC count -- absent is not zero")
    if len(hits) > 1:
        return unmeasured(
            f"{len(hits)} DRC audits are attributed to {tool!r} "
            f"({', '.join(r for r, _ in hits)}); which one is the sign-off "
            f"count is a contradiction this program reports rather than settles")
    rel, total = hits[0]
    return Cell(total, rel, basis="summary.real_violation_total")


def _density(project: Path) -> Cell:
    """Density violations, from the sign-off DRC deck that checked for them.

    The DRC audit records which rule CATEGORIES a report carried. A deck that
    printed no density category did not check density on this run, and a zero
    written over that would be the vacuous clean number this whole module
    exists to refuse.
    """
    for rel in _DRC_AUDITS:
        d = _json(project, rel)
        if not d:
            continue
        summary = d.get("summary") or {}
        cats = [str(c).lower() for c in (summary.get("categories_found") or [])]
        if "density" not in cats:
            continue
        total = summary.get("real_violation_total")
        if isinstance(total, int) and not isinstance(total, bool):
            return Cell(total, rel, basis="summary.real_violation_total "
                                          "(deck carried a density category)")
    return unmeasured(
        "no DRC report in this run carries a 'density' rule category, so no "
        "density violation count was produced by any deck this run ran")


# ── LVS: the audited terminal verdict, and the four counts it implies ────────
def _lvs_from_runner_verdict(project: Path, key: str, missing: str) -> Cell:
    """Fall back to the runner's OWN canonical LVS verdict file.

    `lvs.json` is netgen's `-json` triage sidecar, and netgen derives its name
    from the LOGFILE stem. The flow has a second LVS arm -- the POWER-AWARE
    compare, which writes `lvs_power_aware.rpt` -- and when that arm is the one
    that matches, no `lvs.json` is written at all.

    MEASURED on `spm` (gf180mcuD, image 0.3.46): once the well ties the #684
    prune had removed were restored, the power-aware compare stopped reporting
    a conclusive non-match and became the ACCEPTED arm on its first attempt
    (`LVS_MATCH_POWER_VERIFIED`, per-cell PG connectivity on 15690 instances,
    a STRONGER result than the plain compare). `reports/phase3/lvs.json`
    vanished with it and all four LVS keys went NOT_MEASURED on a run whose
    LVS is better than the one that measured them. `lvs_verdict.json` is
    written by `phase3_one_shot_runner:_run_extraction_lvs` on EVERY arm and is
    the verdict of record; read it. A non-PASS is still not a count.
    """
    rel = "reports/phase3/lvs_verdict.json"
    d = _json(project, rel)
    if not d:
        return unmeasured(
            f"{missing} and {rel}: neither is present, so this run recorded no "
            f"LVS verdict under any of the three files its own producers write")
    status = str(d.get("status") or d.get("result") or "").strip().upper()
    finding = str(d.get("finding") or "").strip().upper()
    if status == "PASS" and finding.startswith("LVS_MATCH"):
        return Cell(0, rel, basis=f"status=PASS finding={finding} "
                                  f"(netgen: circuits match uniquely)")
    if not status:
        return unmeasured(f"{rel}: carries no LVS status", rel)
    return unmeasured(
        f"{rel}: the recorded LVS status is {status!r} (finding {finding!r}), "
        f"not a match. A non-match is not a count: this record states THAT the "
        f"netlists differ and carries no per-class total for {key}", rel)


def _lvs(project: Path, key: str) -> Cell:
    """The netgen LVS verdict this flow already recorded.

    A MATCH is netgen stating the circuits match uniquely, which is zero errors
    and zero unmatched devices, nets and pins -- that is what the verdict
    MEANS, not an inference over it. Anything else is NOT a licence to write a
    count: a mismatched run states THAT it mismatched, and the per-class totals
    are not in the record, so they stay NOT_MEASURED and the reader sees the
    mismatch.

    TWO PRODUCERS WRITE THIS FILE AND THEY DO NOT AGREE ON WHERE THE VERDICT
    LIVES.  `eda_report_audit:lvs` / `lvs_report_check` put it at
    `summary.terminal_verdict`; the netgen-report parser puts it at the TOP
    LEVEL as `verdict` with `summary` holding the per-class counts instead.
    This reader used to know only the first spelling, so on a run whose
    `lvs.json` came from the second one it saw `summary.terminal_verdict`
    missing and reported all four LVS keys NOT_MEASURED with the reason "the
    LVS audit recorded no terminal verdict" -- while the same file said
    `verdict: "match"`, `unmatched_devices 0/0`, `unmatched_nets 0/0` two lines
    up.  MEASURED on `spm` (image 0.3.46, plugin v1.17.42): 4 of the 18 keys
    unmeasured under a reason the record contradicts.  Read BOTH spellings; the
    reason for an honest miss now names both.
    """
    rel = "reports/phase3/lvs.json"
    d = _json(project, rel)
    if not d:
        return _lvs_from_runner_verdict(project, key, rel)
    summary = d.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    raw = summary.get("terminal_verdict")
    where = "summary.terminal_verdict"
    if not isinstance(raw, str) or not raw.strip():
        raw = d.get("verdict")
        where = "verdict"
    verdict = (raw or "").strip().upper() if isinstance(raw, str) else ""
    if verdict == "MATCH":
        return Cell(0, rel, basis=f"{where}=MATCH "
                                  "(netgen: circuits match uniquely)")
    if not verdict:
        return unmeasured(
            f"{rel}: carries no LVS verdict under either spelling this flow's "
            f"producers use (summary.terminal_verdict or verdict)", rel)
    return unmeasured(
        f"{rel}: the recorded LVS verdict ({where}) is {verdict!r}, not MATCH. "
        f"A non-match is not a count: this record states THAT the netlists "
        f"differ and carries no per-class total for {key}", rel)


# ── antenna ─────────────────────────────────────────────────────────────────
def _antenna(project: Path, field: str) -> Cell:
    rel = "reports/phase3/antenna.json"
    d = _json(project, rel)
    if not d:
        return unmeasured(f"{rel}: absent or unreadable, so this run performed "
                          f"no antenna check whose result could be counted")
    v = d.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        return unmeasured(f"{rel}: carries no integer {field!r}", rel)
    if d.get("routing_incomplete") is True:
        return unmeasured(
            f"{rel}: records routing_incomplete=true — an antenna count taken "
            f"over a partially routed design is not a sign-off count", rel)
    return Cell(v, rel, basis=field)


# ── timing ──────────────────────────────────────────────────────────────────
def _slack(project: Path, field: str) -> Cell:
    """Worst slack from the post-route sign-off corner record.

    That record is the one gate that already chose WHICH corner governs; taking
    the number from the raw report instead would make this program a second
    corner-selection policy, and two policies is how one stops being enforced.
    """
    rel = "reports/phase3/sta/post_route_signoff_corner.json"
    d = _json(project, rel)
    if not d:
        return unmeasured(f"{rel}: absent or unreadable, so no post-route "
                          f"sign-off corner was recorded for this run")
    v = d.get(field)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return unmeasured(f"{rel}: carries no numeric {field!r}", rel)
    return Cell(float(v), rel, basis=field)


#: OpenSTA prints `tns <label> <value>`, and this flow's multicorner sign-off
#: report puts the SETUP and the HOLD analysis in their own `=== SETUP ...` /
#: `=== HOLD ...` sections. MEASURED on a real run: the HOLD section's line is
#: also spelled `tns max` -- the label is OpenSTA's, not the analysis's. So the
#: section is the authority for which analysis a number belongs to and the
#: label is not, and a reader that keyed on `max` vs `min` would have filed the
#: setup TNS twice and called the second one hold.
_TNS_RE = re.compile(r"^tns\s+\S+\s+(-?\d+(?:\.\d+)?)\s*$", re.M)
_SECTION_RE = re.compile(r"^===\s*(SETUP|HOLD)\b", re.M | re.I)


def _tns_from(text: str, want: str) -> Optional[float]:
    """The TNS of the ``want`` ('setup'/'hold') analysis, or None.

    A report with NO section headers carries one analysis, and this flow writes
    the setup one there; a hold number read out of it would be the setup number
    under another name, so hold gets nothing.
    """
    marks = [(m.start(), m.group(1).lower()) for m in _SECTION_RE.finditer(text)]
    if not marks:
        return (float(_TNS_RE.search(text).group(1))
                if want == "setup" and _TNS_RE.search(text) else None)
    bounds = [(pos, marks[i + 1][0] if i + 1 < len(marks) else len(text), name)
              for i, (pos, name) in enumerate(marks)]
    for start, end, name in bounds:
        if name != want:
            continue
        hit = _TNS_RE.search(text, start, end)
        if hit:
            return float(hit.group(1))
    return None


def _tns(project: Path, want: str) -> Cell:
    """Total negative slack, from the STA report the corner record cites.

    Read from the report that record NAMES rather than from a fixed filename:
    the run states which report its verdict came from, and a second, differently
    named report on the same tree is a different corner.
    """
    rec_rel = "reports/phase3/sta/post_route_signoff_corner.json"
    rec = _json(project, rec_rel)
    cited = (rec or {}).get("report") or ""
    rel = ""
    if cited:
        # The record may cite an absolute path from the machine that ran it.
        cand = Path(cited)
        try:
            rel = str(cand.relative_to(project.resolve()))
        except Exception:
            rel = "" if cand.is_absolute() else cited
        if not rel or not (project / rel).is_file():
            tail = cand.name
            for probe in (f"reports/phase3/{tail}", f"phase3/stage3/sta/{tail}"):
                if (project / probe).is_file():
                    rel = probe
                    break
    if not rel or not (project / rel).is_file():
        return unmeasured(
            f"{rec_rel}: names no readable STA report on this tree "
            f"({cited or 'no report field'}), so no total-negative-slack table "
            f"can be attributed to the sign-off corner")
    value = _tns_from(_text(project, rel) or "", want)
    if value is None:
        return unmeasured(
            f"{rel}: carries no total-negative-slack line for the {want} "
            f"analysis, so this run recorded no {want} TNS", rel)
    return Cell(value, rel, basis=f"the `tns` line of the {want.upper()} section")


#: OpenSTA sign-off reports declare which check types were REQUESTED. The same
#: reports carry an explicit semantics line saying an empty table means no
#: violation -- and carve out max_fanout, and only max_fanout, as the check
#: whose table is empty BY CONSTRUCTION when the SDC declares no limit. So a
#: declared max_slew / max_capacitance check with no violation rows is a
#: measured zero; an UNDECLARED one is NOT_MEASURED. This program follows the
#: report's own stated semantics rather than inventing a reading of silence.
_DECLARED_RE = re.compile(r"^SIGNOFF_CHECK_TYPES_REPORTED\s+(.+)$", re.M)


def _drv(project: Path, check: str) -> Cell:
    rel = "reports/phase3/sta_spef_based.rpt"
    text = _text(project, rel)
    if text is None:
        return unmeasured(f"{rel}: absent or unreadable, so this run recorded "
                          f"no design-rule check of any kind")
    declared = set()
    for line in _DECLARED_RE.findall(text):
        declared.update(line.split())
    if check not in declared:
        return unmeasured(
            f"{rel}: does not declare {check} in SIGNOFF_CHECK_TYPES_REPORTED, "
            f"so the check was never requested and an empty report is silence, "
            f"not a zero", rel)
    rows = text.count("VIOLATED")
    return Cell(rows, rel,
                basis=f"{check} declared in SIGNOFF_CHECK_TYPES_REPORTED; "
                      f"{rows} row(s) marked VIOLATED in this report")


# ── geometry ────────────────────────────────────────────────────────────────
_DIEAREA_RE = re.compile(
    r"^DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)", re.M)
_UNITS_RE = re.compile(r"^UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", re.M)


def _die_bbox(project: Path) -> Cell:
    """``design__die__bbox`` in MICRONS, from the run's own shipped DEF.

    The readers parse this as four floats and print a width and a height, so it
    must be the die the run SHIPPED. The DEF the sign-off GDS was written from
    is the authority; a floorplan DEF from before any downsize retry is a die
    that no longer exists.
    """
    pnr = _pl.pnr_dir(project)
    # In the order the run itself finishes them: the last DEF a run writes is
    # the one its GDS came from. Named explicitly rather than by mtime, which
    # a copy of a tree does not preserve.
    for name in ("filled.def", "routed.def", "post_hold.def", "post_cts.def",
                 "floorplan.def"):
        p = pnr / name
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")[:200000]
        m = _DIEAREA_RE.search(text)
        if not m:
            continue
        um = _UNITS_RE.search(text)
        units = float(um.group(1)) if um else 0.0
        if units <= 0:
            return unmeasured(
                f"phase3/stage3/pnr/{name}: DIEAREA is in database units and "
                f"the DEF declares no UNITS DISTANCE MICRONS, so it cannot be "
                f"converted to the microns the readers print",
                f"phase3/stage3/pnr/{name}")
        x0, y0, x1, y1 = (int(t) / units for t in m.groups())
        return Cell(f"{x0:g} {y0:g} {x1:g} {y1:g}",
                    f"phase3/stage3/pnr/{name}",
                    basis="DIEAREA / UNITS DISTANCE MICRONS")
    return unmeasured("no DEF under phase3/stage3/pnr/ carries a DIEAREA, so "
                      "this run has no die geometry to state")


def _xor(project: Path) -> Cell:
    """GDS-vs-layout XOR difference count.

    No step of this flow runs a layout-versus-GDS XOR today; there is no report
    to read and this key is NOT_MEASURED for every design until one exists. It
    is written anyway, with this reason, so that its absence is a stated fact of
    the run rather than a key a reader silently never finds.
    """
    return unmeasured(
        "no step of this flow produces a GDS-vs-layout XOR report, so no XOR "
        "difference count exists for any design on this flow")


# ── the table: one row per key the release readers read ─────────────────────
#: Each row is (metric key, human label, resolver). The keys and their spelling
#: come from `tapeout_docs_gen.MANUFACTURABILITY` / `.ELECTRICAL` plus
#: `die_geometry`; a key added there and missing here is caught by
#: `test_signoff_metrics_aggregate.py::test_every_key_the_readers_read_has_a_rule`.
RULES: list[tuple[str, str, Callable[[Path], Cell]]] = [
    ("route__drc_errors", "Routing DRC",
     lambda p: _drc_for_tool(p, "openroad")),
    ("magic__drc_error__count", "Magic DRC",
     lambda p: _drc_for_tool(p, "magic")),
    ("klayout__drc_error__count", "KLayout DRC",
     lambda p: _drc_for_tool(p, "klayout")),
    ("klayout__density_error__count", "Density", _density),
    ("antenna__violating__nets", "Antenna — violating nets",
     lambda p: _antenna(p, "net_violations")),
    ("antenna__violating__pins", "Antenna — violating pins",
     lambda p: _antenna(p, "pin_violations")),
    ("design__lvs_error__count", "LVS errors",
     lambda p: _lvs(p, "design__lvs_error__count")),
    ("design__lvs_unmatched_device__count", "LVS unmatched devices",
     lambda p: _lvs(p, "design__lvs_unmatched_device__count")),
    ("design__lvs_unmatched_net__count", "LVS unmatched nets",
     lambda p: _lvs(p, "design__lvs_unmatched_net__count")),
    ("design__lvs_unmatched_pin__count", "LVS unmatched pins",
     lambda p: _lvs(p, "design__lvs_unmatched_pin__count")),
    ("design__xor_difference__count", "GDS vs layout XOR", _xor),
    ("timing__setup__ws", "Setup worst slack (ns)",
     lambda p: _slack(p, "setup_worst_slack_ns")),
    ("timing__setup__tns", "Setup total negative slack",
     lambda p: _tns(p, "setup")),
    ("timing__hold__ws", "Hold worst slack (ns)",
     lambda p: _slack(p, "hold_worst_slack_ns")),
    ("timing__hold__tns", "Hold total negative slack",
     lambda p: _tns(p, "hold")),
    ("design__max_slew_violation__count", "Max-slew violations",
     lambda p: _drv(p, "max_slew")),
    ("design__max_cap_violation__count", "Max-cap violations",
     lambda p: _drv(p, "max_capacitance")),
    ("design__die__bbox", "Die bounding box (um)", _die_bbox),
]


def aggregate(project: Path) -> tuple[dict, dict]:
    """``(metrics, report)`` — every key answered, measured or not."""
    metrics: dict = {}
    provenance: dict = {}
    rows = []
    for key, label, resolve in RULES:
        try:
            cell = resolve(project)
        except Exception as exc:                       # a broken artefact is a
            cell = unmeasured(                         # reason, never a crash
                f"reading the source for this key raised "
                f"{type(exc).__name__}: {exc}")
        metrics[key] = cell.value
        entry = {"measured": cell.measured}
        if cell.source:
            entry["source"] = cell.source
            entry["sha256"] = _sha256(project / cell.source)
        if cell.basis:
            entry["basis"] = cell.basis
        if not cell.measured:
            entry["reason"] = cell.reason
        provenance[key] = entry
        rows.append({"key": key, "label": label, "value": cell.value, **entry})
    metrics["__provenance__"] = provenance
    measured = sum(1 for r in rows if r["measured"])
    report = {
        "schema": SCHEMA,
        "program": "signoff_metrics_aggregate",
        "project": str(project),
        "keys": len(rows),
        "measured": measured,
        "not_measured": len(rows) - measured,
        "rows": rows,
    }
    return metrics, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="signoff_metrics_aggregate",
        description="aggregate this run's sign-off reports into "
                    "phase3/final/metrics.json")
    ap.add_argument("project_dir", nargs="?", default=".")
    ap.add_argument("--check", action="store_true",
                    help="do not write: exit 1 unless phase3/final/metrics.json "
                         "exists and states what this run's reports state now")
    ap.add_argument("--json", default="",
                    help=f"where the full record goes (default: {REPORT_REL})")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"[CANNOT CHECK] signoff_metrics_aggregate — {project} is not a "
              f"directory; there is no run to summarise")
        return 2

    metrics, report = aggregate(project)
    out = _pl.phase3_final_dir(project) / "metrics.json"

    # ── --check: the gate's clause ──────────────────────────────────────────
    # It must be able to FAIL on a real tree, or wiring it would add a clause
    # that answers the same way for every design -- the vacuous shape
    # `test_step_37_5ic_gate_is_not_vacuous` exists to refuse. It fails on two
    # states a run can really be in: no metrics file at all, and a metrics file
    # that no longer states what this run's own reports state (a stale summary
    # is worse than none, because the documents built on it look current).
    if args.check:
        if not out.is_file():
            print(f"[FAIL] signoff_metrics_aggregate --check — "
                  f"{out.relative_to(project)} is absent: this run has no "
                  f"sign-off metrics record, so every release document reading "
                  f"it would be written over nothing")
            return 1
        try:
            on_disk = json.loads(out.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[FAIL] signoff_metrics_aggregate --check — "
                  f"{out.relative_to(project)} is unreadable ({exc})")
            return 1
        drifted = [k for k, _, _ in RULES if on_disk.get(k) != metrics[k]]
        if drifted:
            print(f"[FAIL] signoff_metrics_aggregate --check — "
                  f"{len(drifted)} key(s) no longer state what this run's "
                  f"reports state: {', '.join(drifted)}. Re-run the producer.")
            return 1
        print(f"[PASS] signoff_metrics_aggregate --check — all "
              f"{len(RULES)} key(s) agree with this run's own reports "
              f"({report['measured']} measured, {report['not_measured']} "
              f"NOT_MEASURED with a stated reason)")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    _atomic.write_json(out, metrics, indent=2, sort_keys=True)
    rep = Path(args.json) if args.json else project / REPORT_REL
    rep.parent.mkdir(parents=True, exist_ok=True)
    _atomic.write_json(rep, report, indent=2)

    print(f"[PRODUCED] signoff_metrics_aggregate — {report['measured']} of "
          f"{report['keys']} sign-off key(s) measured, "
          f"{report['not_measured']} NOT_MEASURED with a stated reason; "
          f"wrote {out.relative_to(project) if out.is_relative_to(project) else out}")
    for row in report["rows"]:
        if row["measured"]:
            print(f"  {row['key']} = {row['value']}   <- {row['source']}")
        else:
            print(f"  {row['key']} = NOT_MEASURED   ({row['reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
