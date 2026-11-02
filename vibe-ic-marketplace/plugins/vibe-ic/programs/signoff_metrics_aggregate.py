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
import math
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set, Tuple

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
#: The DRC audits this summary reads. The MAGIC receipt is here because
#: `magic__drc_error__count` is read by `tapeout_docs_gen` and MEASURED on
#: spm run18L and run19 it said "Magic DRC NOT_MEASURED" — correctly, since
#: no report in either run was attributed to magic. A run that now produces
#: one must be able to state its count; a run that does not is unchanged,
#: because `_json` skips a file that is not there and the metric keeps the
#: same "absent is not zero" answer it has today.
_DRC_AUDITS = ("reports/phase3/drc_signoff.json",
               "reports/phase3/drc_signoff_magic.json",
               "reports/phase3/drc_router.json")


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


#: `Executing deck <name> from <...>/rule_decks/<file>.rb` -- KLayout's own line,
#: written once per deck it sources. The RULE DECK FILE is the identity used, not
#: the deck label, because the label is a rule number (V1.1, M2.3a) while the file
#: names the category.
_EXECUTED_DECK_RE = re.compile(
    r"^.*Executing deck\s+\S+\s+from\s+(\S*?/rule_decks/([A-Za-z0-9_]+)\.rb)\s*$",
    re.M)

#: Where a DRC audit records the files it actually read. A `.log` among them is the
#: tool transcript; that is where the executed-deck inventory lives.
_SCOPED_UNDER = "scoped_under"


def _executed_rule_decks(project: Path, audit: Dict[str, Any]
                         ) -> Tuple[Set[str], str]:
    """({rule-deck file stems the run's DRC log shows executed}, citation).

    R-0915-129. A CLEAN DRC report carries no rule categories at all -- there are
    no violations to categorise -- so `categories_found` cannot distinguish "the
    deck did not check density" from "the deck checked density and found nothing".
    Reading the log settles it, because KLayout writes one
    `Executing deck ... from .../rule_decks/<category>.rb` line per deck it sources.

    MEASURED on spm run21: `reports/phase3/drc_signoff.log` line 480 is
    `Executing deck density from .../gf180mcuD/libs.tech/klayout/tech/drc/
    rule_decks/density.rb`, one of 177 such lines naming 36 distinct rule decks --
    while `drc_signoff.json`'s `categories_found` is
    [spacing, width, antenna, via, enclosure] because the report is CLEAN
    (`real_violation_total: 0`). The sibling `precheck_klayout_drc.json` scopes the
    log as well as the report and does see density; this reader scoped only the
    report.

    The log is taken from the audit's OWN `scoped_under` list, so this reads what
    that report says it covered rather than guessing a filename. Returns an empty
    set when no log was scoped or none can be read -- and an empty set decides
    nothing, so a run with no transcript stays NOT_MEASURED.
    """
    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    scoped = [r for r in (summary.get(_SCOPED_UNDER) or []) if isinstance(r, str)]
    logs = [r for r in scoped if r.endswith(".log")]
    # Step31 scopes its native transcript when it publishes this audit. A
    # later release precheck is a different producer and cannot add authority
    # to an earlier metrics record merely by citing the same text report.
    decks: Set[str] = set()
    citation = ""
    for rel in dict.fromkeys(logs):
        if not isinstance(rel, str) or not rel.endswith(".log"):
            continue
        try:
            text = (project / rel).read_text(errors="replace")
        except OSError:
            continue
        for line, stem in _EXECUTED_DECK_RE.findall(text):
            decks.add(stem.lower())
            if stem.lower() == "density" and not citation:
                citation = f"{rel}: Executing deck ... from {line}"
    return decks, citation


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
    # THE CLEAN-REPORT CASE, R-0915-129. No report carried the category, which for
    # a report with ZERO violations says nothing either way. If the run's own DRC
    # transcript shows the density rule deck EXECUTED and that report's violation
    # total is 0, then density was checked and found nothing: a MEASURED zero, and
    # writing NOT_MEASURED over it withholds a number the run produced.
    for rel in _DRC_AUDITS:
        d = _json(project, rel)
        if not d:
            continue
        total = (d.get("summary") or {}).get("real_violation_total")
        if not isinstance(total, int) or isinstance(total, bool) or total != 0:
            continue
        decks, citation = _executed_rule_decks(project, d)
        if "density" in decks:
            return Cell(0, rel, basis=(
                "the run's own DRC transcript shows the density rule deck "
                "EXECUTED over a report with zero violations, so this is a "
                f"MEASURED zero, not an unchecked one — {citation}"))
    return unmeasured(
        "no DRC report in this run carries a 'density' rule category, and no DRC "
        "transcript this run scoped shows a density rule deck executed over a "
        "clean report, so no density violation count was produced by any deck "
        "this run ran")


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
    import librelane_signoff as native
    if rel == native.SIGNOFF_RECORD:
        # The native producer's record is JSON, not an OpenSTA text report.
        # Its existing reader binds every declared scene to current timed
        # inputs and the original receipt; no raw JSON/WNS fallback is valid.
        try:
            arm = native.step23_tool_arm(project, artefacts=())
            if not arm or not arm.get('corners'):
                raise ValueError('the selected native STA arm is absent')
            values = {}
            for corner, row in arm['corners'].items():
                value = row.get('metrics', {}).get(f'{want}_tns')
                if (row.get('scope_gaps') or type(value) not in (int, float)
                        or not math.isfinite(value)):
                    raise ValueError(f'{corner}: missing, unbound or non-finite {want} TNS')
                values[corner] = value
            # LibreLane aggregates both TNS metrics by their minimum, never
            # by adding repeated endpoint populations across PVT scenes.
            source = str((Path(arm['folder']) / 'state_out.json').relative_to(project.resolve()))
            return Cell(min(values.values()), source,
                        basis=f"native {want} TNS minimum across {len(values)} declared scenes; "
                              f"{rel} sha256={arm['record_sha256']}; per_scene={values}")
        except Exception as exc:
            return unmeasured(f'{rel}: native {want} TNS unavailable: {exc}', rel)
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


#: `SIGNOFF_DRV_CENSUS <check> violators=<N|UNAVAILABLE>` — OpenSTA's OWN
#: per-check violator counter, written by `phase3_one_shot_runner` from
#: `sta::${check}_violation_count`. Its BEGIN banner states the contract:
#: "the tool's own violator count for every check type requested above, zero
#: included -- an absent table is silence, a count is a measurement".
_DRV_CENSUS_RE = re.compile(
    r"^SIGNOFF_DRV_CENSUS\s+(\S+)\s+violators=(\S+)\s*$", re.M)


def _drv(project: Path, check: str) -> Cell:
    """The violator count for ONE design-rule check.

    IT IS PER-CHECK, AND IT USED NOT TO BE (2026-09-15, icspm2). This returned
    `text.count("VIOLATED")` — the number of violated rows in the WHOLE report
    — for every check it was asked about, so `design__max_slew_violation__count`
    and `design__max_cap_violation__count` were the SAME number under two names.
    On a clean design both are 0 and it is invisible; on a design with one
    max-cap violation both keys would read 1, and a reader would conclude the
    slews were violated too.

    The per-check number is already in the report. `phase3_one_shot_runner`
    (the `SIGNOFF_DRV_CENSUS` emitter) added it precisely because "an absent
    table is not a measurement", and its comment says what it was for: "that is
    the correct reading of silence, and it is why this run could not certify a
    DRV axis it had actually checked". The census was built and never read.

    The CENSUS is the authority when present, because it distinguishes a
    measured zero from an absent table — which is the whole reason it exists.
    `UNAVAILABLE` (OpenSTA had no such counter) stays NOT_MEASURED. A report
    with no census at all falls back to the whole-report VIOLATED count, which
    is what every already-published run carries, with the basis SAYING that the
    figure is not per-check.
    """
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
    census = {name: value for name, value in _DRV_CENSUS_RE.findall(text)}
    if census:
        raw = census.get(check)
        if raw is None:
            return unmeasured(
                f"{rel}: declares {check} in SIGNOFF_CHECK_TYPES_REPORTED but "
                f"its SIGNOFF_DRV_CENSUS names no count for it, so the tool "
                f"reported on it and this run did not capture the number", rel)
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return unmeasured(
                f"{rel}: SIGNOFF_DRV_CENSUS records {check} violators={raw} — "
                f"OpenSTA had no counter for this check, which is not a zero",
                rel)
        return Cell(n, rel,
                    basis=f"SIGNOFF_DRV_CENSUS {check} violators={n} — "
                          f"OpenSTA's own per-check violator counter")
    rows = text.count("VIOLATED")
    return Cell(rows, rel,
                basis=f"{check} declared in SIGNOFF_CHECK_TYPES_REPORTED; "
                      f"{rows} row(s) marked VIOLATED in this report. NOTE: "
                      f"this report carries no SIGNOFF_DRV_CENSUS, so the "
                      f"figure is the whole report's violated-row count and is "
                      f"NOT specific to {check}")


# ── geometry ────────────────────────────────────────────────────────────────
_DIEAREA_RE = re.compile(
    r"^DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)", re.M)
_UNITS_RE = re.compile(r"^UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", re.M)


#: The record `phase3_one_shot_runner.step_pnr` writes on every run, naming
#: the die rectangle and the rectangle OpenROAD was actually given. Spelled
#: here because importing the runner to read one path would pull 2.7 MB of
#: module into an aggregator that reads reports; `test_ct03_floorplan_
#: rectangles_and_declarations.py` asserts the two constants agree, so the
#: duplication cannot drift silently.
FLOORPLAN_RECTANGLES_REL = "reports/phase3/floorplan_rectangles.json"


def _declared_die_rect_um(project: Path):
    """(rect_um, source_rel, basis) from the run's own floorplan record.

    (None, "", why) when there is no record, it cannot be read, or it carries
    no usable rectangle. Never a default: the caller falls back to the DEF and
    SAYS it did.
    """
    rel = FLOORPLAN_RECTANGLES_REL
    rec = _json(project, rel)
    if not isinstance(rec, dict):
        return None, rel, (f"{rel} is absent or unreadable")
    rect = rec.get("die_rect_um")
    if not (isinstance(rect, list) and len(rect) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    for v in rect)
            and rect[2] > rect[0] and rect[3] > rect[1]):
        return None, rel, f"{rel} carries no usable `die_rect_um` ({rect!r})"
    return ([float(v) for v in rect], rel,
            str(rec.get("die_source") or "the run's floorplan record"))


def _die_bbox(project: Path) -> Cell:
    """``design__die__bbox`` in MICRONS — the DIE, not the floorplan rectangle.

    THE DEF IS NO LONGER THE FIRST AUTHORITY, and the reason is measured. Since
    the slot fix, and since CT-03 on a design whose own pad ring pins the die,
    the rectangle OpenROAD is handed as ``-die_area`` is the PLACEABLE CORE —
    because ``ppl place_pins`` places pins on the die boundary and has no
    core-boundary mode. The DEF's ``DIEAREA`` then states that core, and this
    key, which the readers parse as four floats and print as a width and a
    height, would state the core as the die: 2019 x 2019 um for a 3162 x 3162
    um die on spm, and 1052 x 1647 for a 1936 x 2531 slot.

    So the run's own floorplan record wins when it exists, and the DEF is the
    fallback for every tree written before it — with ``basis`` naming which of
    the two answered, so a reader can always tell. Among DEFs the order is the
    order the run finishes them: the last DEF a run writes is the one its GDS
    came from, named explicitly rather than by mtime, which a copy of a tree
    does not preserve.
    """
    rect, rel, basis = _declared_die_rect_um(project)
    if rect is not None:
        x0, y0, x1, y1 = rect
        return Cell(f"{x0:g} {y0:g} {x1:g} {y1:g}", rel,
                    basis=f"the run's declared die rectangle — {basis}")
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
                    basis=f"DIEAREA / UNITS DISTANCE MICRONS — {basis}, so "
                          f"this is the rectangle OpenROAD was given and is "
                          f"the die only when the two are the same")
    return unmeasured(f"no DEF under phase3/stage3/pnr/ carries a DIEAREA and "
                      f"{basis}, so this run has no die geometry to state")


#: The XOR producer's receipt. R-0915-129 metric 2.
_XOR_REL = "reports/phase3/gds_xor.json"


def _xor(project: Path) -> Cell:
    """GDS-vs-layout XOR difference count, from the producer's own receipt.

    R-0915-129 ruled this metric NOT structural -- KLayout in the pinned image has
    `xor`, so the flow CAN produce it and declaring it inapplicable would be
    laundering. `gds_xor_check` now does: it XORs the shipped GDS against the
    pre-finishing boundary of the same routed DB and counts DESIGN-layer
    differences, with the layers each finishing step declares it added subtracted
    and disclosed separately.

    Three outcomes are passed through as the producer stated them, never
    collapsed: a number (including 0), NOT_DETERMINED (the producer refused --
    an unfaithful reference, a changed artefact, no runner), and absence. A
    refusal is NOT a zero, and that distinction is the whole value of the key.
    """
    rec = _json(project, _XOR_REL)
    if not isinstance(rec, dict):
        return unmeasured(
            f"{_XOR_REL} is absent, so the XOR step did not run or did not write "
            f"its receipt; an unrun XOR is not a difference count of zero")
    verdict = rec.get("verdict")
    count = rec.get("design__xor_difference__count")
    if verdict in {"PASS", "FAIL"} and isinstance(count, int) \
            and not isinstance(count, bool):
        ref = (rec.get("reference") or {}).get("kind") or "unstated"
        if ref == "signoff_gds":
            # The IC front door's receipt (ruling #88 D3): no layer is exempt.
            return Cell(count, source=_XOR_REL,
                        basis=(f"KLayout XOR of the delivered GDS against the "
                               f"signoff GDS on all {rec.get('layers_compared')} "
                               f"layer(s) compared; no layer is exempt"))
        return Cell(count, source=_XOR_REL,
                    basis=(f"design-layer XOR against the {ref} pre-finishing "
                           f"reference; {len(rec.get('finishing_layer_differences') or [])} "
                           f"finishing-declared layer(s) differ and are listed "
                           f"separately in that report"))
    return unmeasured(
        f"{_XOR_REL} reports {verdict!r} rather than a difference count"
        + (f": {rec.get('reason')}" if rec.get("reason") else ""))


# ── the table: one row per key the release readers read ─────────────────────
#: Each row is (metric key, human label, resolver). The keys and their spelling
#: come from `tapeout_docs_gen.MANUFACTURABILITY` / `.ELECTRICAL` plus
#: `die_geometry`; a key added there and missing here is caught by
#: `test_signoff_metrics_aggregate.py::test_every_key_the_readers_read_has_a_rule`.
# ── the five axes the flow MEASURED and never published (icspm2, 2026-09-15) ──
#
# `every_required_metric_key_has_a_producer` reported six axes as "NOT PROVEN BY
# ANY RUN IN THIS CORPUS" on a run that had measured every one of them. It is an
# EMPIRICAL gate: it looks for a MEASURED record under a canonical name, and the
# records were on disk under no name it reads. The rules below publish them, each
# from the report the checker itself wrote, with its provenance — this module
# still measures nothing and re-decides nothing.


def _ir_worst_drop_v(project: Path) -> Cell:
    """Worst static IR drop in VOLTS, from the PSM sign-off record.

    `supply_measured` is consulted, not just the number: `ir_drop.json`
    documents that a PSM supply voltage of ZERO means PSM found no source on
    the net, and a drop derived from it is not a statement about the design.
    """
    rel = "reports/phase3/ir_drop.json"
    doc = _json(project, rel)
    if not isinstance(doc, dict):
        return unmeasured(f"{rel}: absent or unreadable, so this run recorded "
                          f"no IR-drop analysis")
    if doc.get("unmeasured_reason"):
        return unmeasured(f"{rel}: the producer declares it unmeasured — "
                          f"{doc['unmeasured_reason']}", rel)
    if doc.get("supply_measured") is False:
        return unmeasured(f"{rel}: supply_measured is false, so the drop is "
                          f"not a statement about this design", rel)
    uv = doc.get("worst_ir_uv")
    if not isinstance(uv, (int, float)):
        return unmeasured(f"{rel}: carries no numeric worst_ir_uv", rel)
    return Cell(float(uv) / 1e6, rel,
                basis=f"worst_ir_uv {uv} uV from the PSM static sign-off, "
                      f"expressed in volts")


def _em(project: Path, what: str) -> Cell:
    """EM from the Jmax screen's own record.

    `offender_count` is the number of segments over Jmax; `worst_utilization`
    is the worst current density AS A FRACTION of Jmax, which is what a
    "worst ratio" is. A SKIPPED screen is NOT a zero.
    """
    rel = "reports/phase3/em_current_authority.json"
    doc = _json(project, rel)
    if not isinstance(doc, dict):
        return unmeasured(f"{rel}: absent or unreadable, so this run recorded "
                          f"no electromigration screen")
    screen = doc.get("jmax_screen")
    if not isinstance(screen, dict):
        return unmeasured(f"{rel}: carries no jmax_screen record", rel)
    if screen.get("skip_reason"):
        return unmeasured(f"{rel}: the Jmax screen was skipped — "
                          f"{screen['skip_reason']}", rel)
    summary = screen.get("summary") or {}
    screened = summary.get("segments_screened")
    if not isinstance(screened, int) or screened <= 0:
        return unmeasured(f"{rel}: the Jmax screen examined no segment, so "
                          f"neither a violation count nor a ratio was "
                          f"established", rel)
    if what == "violations":
        n = screen.get("offender_count")
        if not isinstance(n, int):
            return unmeasured(f"{rel}: jmax_screen carries no offender_count",
                              rel)
        return Cell(n, rel,
                    basis=f"jmax_screen.offender_count over "
                          f"{screened} screened segment(s)")
    ratio = summary.get("worst_utilization")
    if not isinstance(ratio, (int, float)):
        return unmeasured(f"{rel}: jmax_screen carries no worst_utilization",
                          rel)
    return Cell(float(ratio), rel,
                basis=f"jmax_screen worst_utilization over {screened} "
                      f"screened segment(s) — current density as a fraction "
                      f"of the layer's Jmax")


def _equivalence(project: Path) -> Cell:
    """The post-layout LEC verdict, as the checker recorded it."""
    rel = "reports/phase3/lec_post_layout.json"
    doc = _json(project, rel)
    if not isinstance(doc, dict):
        return unmeasured(f"{rel}: absent or unreadable, so this run recorded "
                          f"no post-layout logical-equivalence proof")
    if doc.get("skipped"):
        return unmeasured(f"{rel}: the LEC step records itself as skipped, so "
                          f"no equivalence was proved", rel)
    verdict = doc.get("verdict")
    if not isinstance(verdict, str) or not verdict.strip():
        return unmeasured(f"{rel}: carries no verdict string", rel)
    return Cell(verdict, rel,
                basis=f"the post-layout LEC's own verdict "
                      f"(equivalent={doc.get('equivalent')!r}, "
                      f"{doc.get('proven_points')} of "
                      f"{doc.get('total_points')} point(s) proven)")


def _spares(project: Path) -> Cell:
    """The graded spare-cell pool, from the artefact a STEP DECLARES.

    WHY NOT `reports/spare_preservation.json`, WHICH IS THE BETTER FACT
    (2026-09-15, icspm2). The design-for-ECO question a reader really wants is
    what SURVIVED into the shipped netlist/DEF/GDS — an inserted spare a later
    pass removed reaches nothing — and `spare_preservation.json` carries
    exactly that. Reading it here is refused, and the flow says so in its own
    words at step 34:

        "`reports/spare_preservation.json` IS NOT DECLARED HERE … this step's
         only producer of that file is the `optional_program_exit_zero` clause
         below, which runs only when `phase3/stage3/pnr/spare_cells.json` is
         present, while `required_outputs` is UNCONDITIONAL … Declaring it
         asserts a production the same gate denies four lines down, and reds
         every spare-less design over an artefact nobody owes."

    and at step 37.5ic, about a consumer that was wired and then REMOVED for
    this very reason:

        "WHAT WOULD MAKE IT WIREABLE: a step that produces
         `reports/spare_preservation.json` UNCONDITIONALLY and declares it. As
         long as step 34's producer is conditional, no honest declaration
         exists and no gate may read the path."

    I re-created that consumer and d7 caught it — `W2:produced_consumed_
    undeclared` on step 37.4 — which is the register working. So this reads
    `reports/spare_cell_coverage.json` instead: step 18 DECLARES it in
    `required_outputs`, and `spare_cell_coverage_check` is its sole declaring
    producer (docs/decisions/2026-08-22-spare-cell-coverage-declaring-producer).

    AND THE BASIS SAYS WHAT THE WEAKER FACT IS. This is the pool at insertion,
    graded for density / distribution / tie-off — NOT a survival count. The key
    must not be read as evidence that the pool reached the shipped artefacts;
    `spare_cell_preservation_check` is what answers that, and it cannot be
    consumed here until its producer is unconditional and declared.
    """
    rel = "reports/spare_cell_coverage.json"
    doc = _json(project, rel)
    if not isinstance(doc, dict):
        return unmeasured(f"{rel}: absent or unreadable, so this run graded no "
                          f"spare-cell pool")
    n = doc.get("count")
    if not isinstance(n, int):
        return unmeasured(f"{rel}: carries no integer `count`", rel)
    return Cell(n, rel,
                basis=f"{n} spare cell(s) in the graded pool "
                      f"(verdict {doc.get('verdict')}, actual_density "
                      f"{doc.get('actual_density')} against target "
                      f"{doc.get('target_density')}). POOL AT INSERTION, not a "
                      f"survival count: the post-fill survival record is "
                      f"written under a conditional clause that no step "
                      f"declares, and no gate may read an undeclared path")


def _antenna_total(project: Path) -> Cell:
    """The antenna violation TOTAL — and ONLY when it is derivable.

    `_metric_vocabulary` refuses to answer this key from either per-population
    count, and its reason is right: "antenna violations are counted per NET and
    per PIN and the two are not the same population; neither alone is the
    total", and a net may violate at several pins, so the two do not sum
    either. `eda_report_audit:antenna` publishes a `summary.violations` that
    IS such a sum in its fallback path.

    There is exactly one state in which the total is not in doubt: BOTH
    populations are zero. Zero nets and zero pins can only be zero violations,
    whatever the overlap. So a clean antenna result answers the canonical key
    and a dirty one stays NOT_MEASURED, naming the two counts it holds. That is
    the direction that cannot invent evidence: a design with violations is
    never certified by this key.
    """
    rel = "reports/phase3/antenna.json"
    doc = _json(project, rel)
    if not isinstance(doc, dict):
        return unmeasured(f"{rel}: absent or unreadable, so this run recorded "
                          f"no antenna check")
    nets, pins = doc.get("net_violations"), doc.get("pin_violations")
    if not isinstance(nets, int) or not isinstance(pins, int):
        return unmeasured(f"{rel}: carries no integer net_violations / "
                          f"pin_violations pair", rel)
    if doc.get("routing_incomplete"):
        return unmeasured(f"{rel}: the route was incomplete, so an antenna "
                          f"count over it is not sign-off evidence", rel)
    if nets == 0 and pins == 0:
        return Cell(0, rel,
                    basis="net_violations 0 and pin_violations 0 — the one "
                          "state in which the TOTAL is not in doubt, since "
                          "the two populations overlap and do not sum")
    return unmeasured(
        f"{rel}: {nets} net violation(s) and {pins} pin violation(s). A net "
        f"may violate at several pins, so these two populations overlap and "
        f"their sum is not the total; this run therefore establishes no single "
        f"antenna violation count", rel)


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
    # The third leg of the `drv` proof group. `every_required_metric_key_has_a_
    # producer` proves that axis only when max_tran + max_cap + max_fanout all
    # have a measured record; two of the three were produced and this one never
    # was, so the axis read "NOT PROVEN BY ANY RUN IN THIS CORPUS" on a run that
    # had measured it (`SIGNOFF_DRV_CENSUS max_fanout violators=0`).
    ("design__max_fanout_violation__count", "Max-fanout violations",
     lambda p: _drv(p, "max_fanout")),
    ("design__die__bbox", "Die bounding box (um)", _die_bbox),
    ("power__ir__worst_drop_v", "Worst static IR drop (V)", _ir_worst_drop_v),
    ("reliability__em__violation__count", "EM segments over Jmax",
     lambda p: _em(p, "violations")),
    ("reliability__em__worst_ratio", "EM worst current density / Jmax",
     lambda p: _em(p, "worst_ratio")),
    ("equivalence__verdict", "Post-layout logical equivalence", _equivalence),
    ("design_for_eco__spares__count", "Spare cells surviving to the artefacts",
     _spares),
    ("antenna__violation__count", "Antenna violations (total)", _antenna_total),
]

#: Keys this aggregator publishes for the AXIS gate, not for the release
#: documents (2026-09-15, icspm2).
#:
#: `test_every_key_the_release_readers_read_has_a_rule` pins RULES against the
#: key set `tapeout_docs_gen` reads, as an EQUALITY. Its stated intent is
#: one-directional — "a key added there and not here would silently be
#: NOT_MEASURED forever" — and that direction is untouched and still exact.
#: What the equality ALSO said, incidentally, is that this aggregator may never
#: publish a measurement the release documents do not print, and that is the
#: half these six keys break: `every_required_metric_key_has_a_producer` is a
#: SECOND consumer, and it reported six axes as "NOT PROVEN BY ANY RUN IN THIS
#: CORPUS" over runs that had measured every one of them.
#:
#: So the closure property is kept rather than relaxed: RULES is still exactly
#: `readers | AXIS_ONLY_KEYS`, and a key may still not appear in RULES without
#: being accounted for HERE, in writing, with the consumer that wants it named.
AXIS_ONLY_KEYS: frozenset = frozenset({
    "design__max_fanout_violation__count",   # axis `drv`  (third leg of the group)
    "power__ir__worst_drop_v",               # axis `ir`
    "reliability__em__violation__count",     # axis `em`
    "reliability__em__worst_ratio",          # axis `em`
    "equivalence__verdict",                  # axis `equivalence`
    "design_for_eco__spares__count",         # axis `eco_readiness`
    "antenna__violation__count",             # axis `antenna`
})


def _librelane_state_cell(project: Path, key: str) -> Optional[Cell]:
    """Step 37.4 on LibreLane State (lane mig105).

    When the flow step that measures ``key`` runs on LibreLane
    (``phase3/librelane_switch.json``), the key is read from that chain's
    judged ``state_out.json`` (`librelane_pv_signoff.state_metric`), bound by
    sha256, and from nothing else. None: the step is not on LibreLane in this
    run, so the direct rule below answers.
    """
    import librelane_pv_signoff as _pv
    row = _pv.state_metric(project, key, current=True)
    if row is None:
        return None
    if row["value"] == _pv.NOT_MEASURED:
        return unmeasured(row["reason"], row.get("record", ""))
    return Cell(row["value"], row["source"],
                basis=f"LibreLane State, judged in {row['record']}")


def aggregate(project: Path) -> tuple[dict, dict]:
    """``(metrics, report)`` — every key answered, measured or not."""
    metrics: dict = {}
    provenance: dict = {}
    rows = []
    for key, label, resolve in RULES:
        try:
            cell = _librelane_state_cell(project, key)
            if cell is None:
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

    # Producer and canonical cwd checks must name the same evidence paths.
    project = Path(args.project_dir).resolve()
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
        # A numerically unchanged report can still describe different bytes.
        # Check the producer's material digests and types as well as values.
        keys = [k for k, _, _ in RULES] + ['__provenance__']
        drifted = [k for k in keys if json.dumps(on_disk.get(k), sort_keys=True)
                   != json.dumps(metrics[k], sort_keys=True)]
        if drifted:
            print(f"[FAIL] signoff_metrics_aggregate --check — "
                  f"{len(drifted)} key(s) no longer state what this run's "
                  f"reports state: {', '.join(drifted)}. Re-run the producer.")
            return 1
        rep = Path(args.json) if args.json else project / REPORT_REL
        try:
            recorded = json.loads(rep.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            print(f"[FAIL] signoff_metrics_aggregate --check — "
                  f"aggregate report missing or unreadable: {rep}: {exc}")
            return 1
        if json.dumps(recorded, sort_keys=True) != json.dumps(report, sort_keys=True):
            print("[FAIL] signoff_metrics_aggregate --check — aggregate report "
                  "does not describe this project's current source reports")
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
