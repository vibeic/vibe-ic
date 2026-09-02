#!/usr/bin/env python3
"""em_peak_current_authority_check.py — the EM peak current must reach a
COMPARISON, or the step must name the authority it lacks.

ENFORCEMENT: advisory — no runner spawns this gate inline, so it cannot stop
step 25 while step 25 is running. That is the ONLY axis this token names, and
it is the one `flow_gate_enforcement_audit` measures ("can this verdict stop
the step it guards"). It is not a statement that the finding is ignorable, and
the other two axes are unchanged and stated here so the declaration can never
be quoted as a demotion:

  * VERDICT SEVERITY — unchanged and BLOCKING in the ordinary sense. rc 1 on a
    supply-current contradiction or a Jmax offender, and rc 2 on INCOMPLETE.
    The rc-2-on-INCOMPLETE half is vibe-ic#1022's repair, landed in #1026: this
    gate previously exited 0 while reporting that it had compared nothing, so
    the honest refusal was indistinguishable from a pass.
  * FLOW SLOT — unchanged and BLOCKING. Step 25 wires this gate in
    `program_exit_zero`, never `advisory_program_exit_zero`, so when
    `flow_compliance_check` evaluates that clause a non-zero rc FAILs the step.

WIRED AND DECLARED ARE DIFFERENT QUESTIONS (vibe-ic#1035). This gate was wired
BLOCKING at step 25 by #1000 and repaired by #1026, and it was STILL reported
by `flow_gate_enforcement_audit` as `undeclared::em_peak_current_authority_
check` at every commit from 080bf6d05 through ad8fbfeb. Neither PR was wrong
and the audit was not stale: "which flow slot is this clause in" and "does this
program state where its verdict is consumed" are two questions, and answering
the first has never answered the second. Silence on the second is what the
audit refuses, and this block is the answer rather than a loosening of it.

THE DEFECT, MEASURED
====================
`matrix_mutation_ledger.ARTEFACT_MUTATIONS` carried an entry, ART-EM-CURRENT-
DENSITY, recording that step 25's dimension-2 cell CANNOT BE REDDENED from the
content of the artefact it audits. The mutation: raise the peak power-grid
segment current stated in `reports/phase3/em.rpt` from 1.963e-04 A to 5.0 A — a
factor of about 25000 — in every place the report states it. The wired gate
(`em_report_check` = `eda_report_audit --mode em`) returned rc 0 with zero
findings, and its own report still read MEASURED.

That gate is not broken at what it does. It establishes that an EM analysis RAN,
that the report carries a tool signature, and that the machine-readable half is
not vacuous. It never compares the current to a limit, so there is no magnitude
of current it can refuse. A gate that reads a figure and emits PASS without
naming a threshold is indistinguishable from one that never looked.

TWO AUTHORITIES, AND WHY BOTH ARE NEEDED
========================================
**Authority 1 — the PDK per-layer Jmax.** This is the real electromigration
sign-off: J = I / (w * t) screened against the foundry's DC current-density
limit per metal and via layer. `em_current_density_check.py` (614 lines) already
implements it, correctly and honestly, including its own §4.05 refusals. It had
ZERO references in `flow/phase1_phase2_phase3.yaml`. This gate is the wiring:
it delegates the Jmax tier to that program rather than re-deriving it.

  MEASURED over the published corpus on 2026-08-11: `*.tlef` files present in
  `benchmark-data/` = **0**, `DCCURRENTDENSITY` occurrences = **0**. The PDK
  lives at `$PDK_ROOT` inside the EDA image, not inside a published run, so on
  every published copy `_discover_jmax_ref` returns `(None, None)` and the Jmax
  tier is UNRESOLVABLE. Wiring `em_current_density_check` into the flow ALONE
  would therefore have returned its SKIPPED rc 3 on all 13 runs that carry an EM
  report — and rc 3 without the waiver sentinel is a FAIL to
  `flow_compliance_check`. That is the gate-that-reddens-the-corpus-on-day-one
  shape, and it is why wiring alone was not the fix.

**Authority 2 — the net's own supply current, declared in the same report.**
The PSM IR block of `em.rpt` states, per analysed net:

    Net              : <name>
    Total power      : 1.34e-03 W
    Supply voltage   : 1.80e+00 V

so the total current delivered into that net is I_net = P / V. No branch of a
passive resistive grid driven by that supply can carry more current than is
injected into it (superposition over source-sink pairs; there is no EMF in the
loop to circulate current). So

    peak segment current  >  total net supply current

is not a marginal call and not a tunable threshold — it is a CONTRADICTION
inside one artefact, of the same shape as the IR-drop budget that the ledger
already calls "the one artefact edit the gate can settle without any outside
reference". THERE IS NO BOUND HERE TO MOVE: the ratio limit is 1.0 because
that is conservation of charge, not a guardband someone chose.

  MEASURED over all 13 published runs carrying `reports/phase3/em.rpt`, the
  ratio peak/(P/V) is 0.049 - 0.712 (worst: the 5 V run, 0.712). Every run
  clears the bound with at least 29% headroom, so this screen turns NOTHING in
  the corpus red. Under the ledger's mutation the same ratio is ~6.7e+03.

WHAT A PASS MEANS HERE, AND WHY MOST RUNS DO NOT GET ONE
========================================================
Authority 2 is a physical-impossibility floor. It is NOT an electromigration
screen: a current that is physically possible can still be far over the metal's
Jmax. So passing it is not passing EM, and saying PASS would re-commit the
defect this gate was written against, one floor lower.

    Jmax tier ran, clean            -> PASS, naming Jmax source + worst util
    Jmax tier ran, offenders        -> FAIL
    supply-current contradiction    -> FAIL (whatever the Jmax tier did)
    Jmax absent, supply screen ok   -> INCOMPLETE, naming the missing authority
    neither authority resolvable    -> INCOMPLETE, naming both

`INCOMPLETE` is this repository's own verdict tier for "the input WAS applicable
and it was not audited; someone must come back" — `flow_compliance_check`
promotes a step to it when a passing gate prints the token at line-start. It
aggregates exactly as VACUOUS_PASS does, so no published design turns red on
this alone, and the per-step listing stops calling the step a bare PASS.

WHAT THIS GATE DOES NOT DO — stated so a reviewer does not have to find it
=========================================================================
  * It does not check that the peak stated in `em.rpt` AGREES with `em.json`'s
    `max_segment_current_A` or with the maximum row of `em_segments.csv`. The
    published corpus states 1.963e-04 in one and 1.96e-04 in another (rounded
    provenance text), so an equality screen would need a tolerance, and a
    tolerance chosen to straddle the corpus is the ruler-fitting this campaign
    forbids. Instead the LARGEST peak any member of the family states is the one
    screened: a report family that states two peaks must satisfy the bound for
    the bigger one.
  * It does not read a per-net peak. `em.rpt` in this corpus analyses one net;
    when several are present the bound taken is the LARGEST I_net across them,
    which is the conservative direction (it can only miss a violation, never
    invent one).
  * It forms no opinion about lifetime, temperature or duty cycle. Black's
    equation needs Ea/T/A constants no LEF carries; the relative headroom
    `em_current_density_check` reports is the honest ceiling.

chip-AGNOSTIC: it reads currents, powers and voltages, and resolves the PDK
reference through the existing discovery helper. No foundry, process or chip
token appears anywhere in this file.

Exit codes: 0 = PASS, 1 = a comparison FAILED, 2 = the question could not be
put — INCOMPLETE (the disclosed-skip tier, `_vacuous_exit.RC_VACUOUS`) or a bad
argument.

INCOMPLETE EXITS 2, NOT 0 (vibe-ic#1017)
----------------------------------------
This gate is a BLOCKING `program_exit_zero` clause at step 25. Through #1000 it
returned 0 for INCOMPLETE, so an EMPTY tree — no EM report, no authority of any
kind — PASSED the blocking clause while this file's own last line said
``electromigration was NOT screened``. A gate that states a refusal and returns
a clean verdict is the shape `gate_zero_denominator_refuses_check` exists to
forbid, and the shape repaired for `declared_pdk_is_the_pdk_used_check` in
vibe-ic#1002. `test_matrix_d2_falsifiable` had been red on main for five merges
saying exactly this.

rc 2 is the repo-wide disclosed-skip tier: `flow_compliance_check` records it as
VACUOUS_PASS — "the input-missing skip convention", explicitly NOT a clean
result — so the refusal now survives into the flow record instead of being
laundered into a PASS on the way out.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import _flow_reason_taxonomy as _reason_taxonomy  # noqa: E402

TOOL = "em_peak_current_authority_check"
VERSION = "1.0.1"

RC_OK, RC_FINDINGS, RC_ARG = 0, 1, 2
#: INCOMPLETE — the disclosed-skip tier (`_vacuous_exit.RC_VACUOUS`).
#: Named apart from RC_ARG because they mean different things to a
#: reader even though the flow maps both to VACUOUS_PASS today.
RC_NOT_SCREENED = 2

#: The text report family. Same shape `eda_report_audit._check_em` discovers,
#: kept narrow to the EM report proper — this gate reads NUMBERS, and an IR
#: report's currents are not segment currents.
_RPT_GLOBS = ("reports/**/em*.rpt", "reports/**/*electromigration*",
              "steps/**/em*.rpt")
_JSON_GLOBS = ("reports/**/em*.json", "steps/**/em*.json")

_NUM = r"([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)"

#: Every way this corpus's EM reports state a PEAK SEGMENT CURRENT in amps.
#: Both are the same quantity: the runner's own summary line, and the line PSM
#: prints to stdout and the emitter copies in.
_PEAK_RES = (
    re.compile(r"max(?:imum)?\s+segment\s+current\s*:?\s*" + _NUM + r"\s*A\b",
               re.I),
    re.compile(r"^\s*Maximum\s+current\s*:?\s*" + _NUM + r"\s*A\b",
               re.I | re.M),
)
#: The declared supply authority, as the PSM IR block states it.
_NET_RE = re.compile(r"^\s*Net\s*:\s*(\S+)\s*$", re.M)
_TOTAL_POWER_RE = re.compile(r"^\s*Total\s+power\s*:?\s*" + _NUM + r"\s*W\b",
                             re.I | re.M)
_SUPPLY_V_RE = re.compile(r"^\s*Supply\s+voltage\s*:?\s*" + _NUM + r"\s*V\b",
                          re.I | re.M)


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # reject NaN


def discover(project: Path, globs: Tuple[str, ...]) -> List[Path]:
    """Sorted, de-duplicated files matching any glob. DISCOVERED, never typed."""
    seen: Dict[str, Path] = {}
    for pat in globs:
        for p in project.glob(pat):
            if p.is_file():
                seen[str(p.resolve())] = p
    return [seen[k] for k in sorted(seen)]


def read_peaks(project: Path) -> List[Dict[str, Any]]:
    """Every peak-segment-current figure the EM report family states, in A.

    Both halves are read: the text report(s) and the machine-readable
    companion's ``max_segment_current_A``. A figure in EITHER is a figure the
    run publishes, and the screen below takes the largest.
    """
    out: List[Dict[str, Any]] = []
    for fp in discover(project, _RPT_GLOBS):
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        for rx in _PEAK_RES:
            for raw in rx.findall(text):
                val = _num(raw)
                if val is not None:
                    out.append({"file": _rel(fp, project), "current_A": abs(val)})
    for fp in discover(project, _JSON_GLOBS):
        try:
            doc = json.loads(fp.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        val = _num(doc.get("max_segment_current_A"))
        if val is not None:
            out.append({"file": _rel(fp, project), "current_A": abs(val)})
    return out


def read_supply_authority(project: Path) -> List[Dict[str, Any]]:
    """``I_net = Total power / Supply voltage`` for every net the report states.

    Parsed per ``Net :`` block so a multi-net report does not pair one net's
    power with another's supply. A block missing either figure yields nothing —
    an unstated authority is absent, never assumed.
    """
    out: List[Dict[str, Any]] = []
    for fp in discover(project, _RPT_GLOBS):
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        marks = [(m.start(), m.group(1)) for m in _NET_RE.finditer(text)]
        for i, (pos, net) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
            block = text[pos:end]
            pm = _TOTAL_POWER_RE.search(block)
            vm = _SUPPLY_V_RE.search(block)
            if not (pm and vm):
                continue
            power = _num(pm.group(1))
            volt = _num(vm.group(1))
            if power is None or volt is None or volt <= 0.0:
                continue
            out.append({"file": _rel(fp, project), "net": net,
                        "total_power_W": power, "supply_voltage_V": volt,
                        "supply_current_A": power / volt})
    return out


def _rel(p: Path, project: Path) -> str:
    try:
        return str(p.relative_to(project))
    except ValueError:  # pragma: no cover - defensive
        return str(p)


def jmax_tier(project: Path, jmax: Optional[Path], tech_lef: Optional[Path],
              margin: float) -> Dict[str, Any]:
    """Delegate the REAL EM screen to ``em_current_density_check``.

    This call is the wiring the program never had. Its verdict vocabulary is
    passed through untouched — PASS / FAIL / SKIPPED — because reinterpreting
    another gate's honest SKIP is how an absence becomes a green.
    """
    import em_current_density_check as emc

    em_path = emc._discover_em_report(project)
    if em_path is None:
        return {"verdict": "SKIPPED", "skip_reason": "em_report_absent",
                "jmax_source": None}
    jpath, tlef = jmax, tech_lef
    if jpath is None and tlef is None:
        try:
            from signoff_ladder_run import _discover_jmax_ref
            jpath, tlef = _discover_jmax_ref(project)
        except Exception:  # pragma: no cover - defensive
            jpath, tlef = None, None
    # #1215-PDN: hand the density screen the routed DEF's own per-layer PG
    # width lower bound, so a width-less CSV segment is judged against the
    # wire the router actually drew instead of the LEF minimum. Lower bound
    # -> J overstated -> conservative direction preserved (a PASS through it
    # is trustworthy; a FAIL is strictly less pessimistic than before).
    defw = emc.discover_def_pg_min_widths(project)
    verdict, rep = emc.evaluate(em_path, jpath, tlef, margin,
                                emc._DEFAULT_BLACKS_N, None, 20,
                                def_widths=defw or None)
    return {"verdict": verdict, "skip_reason": rep.get("skip_reason"),
            "def_pg_min_widths_um": defw or None,
            "jmax_source": rep.get("jmax_source"),
            "summary": rep.get("summary"),
            "offender_count": rep.get("offender_count", 0),
            "findings": rep.get("findings", []),
            "em_report": str(em_path)}


def evaluate(project: Path, jmax: Optional[Path], tech_lef: Optional[Path],
             margin: float) -> Tuple[str, Dict[str, Any]]:
    """Return ``(verdict, report)``; verdict in {PASS, FAIL, INCOMPLETE}."""
    rep: Dict[str, Any] = {"program": TOOL, "version": VERSION,
                           "project": str(project), "findings": []}
    peaks = read_peaks(project)
    authority = read_supply_authority(project)
    rep["peak_currents_read"] = peaks
    rep["supply_authority"] = authority

    # ---- authority 2: conservation of charge, from the same artefact -------
    supply_screen: Dict[str, Any] = {"screened": False}
    if peaks and authority:
        worst = max(peaks, key=lambda d: d["current_A"])
        bound = max(authority, key=lambda d: d["supply_current_A"])
        ratio = (worst["current_A"] / bound["supply_current_A"]
                 if bound["supply_current_A"] > 0 else float("inf"))
        supply_screen = {
            "screened": True, "peak_current_A": worst["current_A"],
            "peak_stated_in": worst["file"],
            "authority": (f"{bound['file']}: net {bound['net']} "
                          f"Total power / Supply voltage"),
            "supply_current_A": bound["supply_current_A"],
            "ratio": ratio, "limit_ratio": 1.0,
            "over": ratio > 1.0,
        }
        if supply_screen["over"]:
            rep["findings"].append({
                "severity": "ERROR", "rule": "EM_PEAK_CURRENT_EXCEEDS_SUPPLY",
                "message": (
                    f"peak segment current {worst['current_A']:.4e} A "
                    f"({worst['file']}) exceeds the total current the net is "
                    f"supplied with, {bound['supply_current_A']:.4e} A "
                    f"(= {bound['total_power_W']:.4e} W / "
                    f"{bound['supply_voltage_V']:.4e} V, net {bound['net']}, "
                    f"{bound['file']}) by {ratio:.4g}x. No branch of the grid "
                    f"can carry more current than the supply injects, so this "
                    f"report contradicts itself; the limit is 1.0 because it "
                    f"is conservation of charge, not a guardband")})
    rep["supply_current_screen"] = supply_screen

    # ---- authority 1: the PDK per-layer Jmax -------------------------------
    jt = jmax_tier(project, jmax, tech_lef, margin)
    rep["jmax_screen"] = jt
    if jt["verdict"] == "FAIL":
        for f in jt.get("findings", []):
            if str(f.get("severity")).upper() == "ERROR":
                rep["findings"].append(f)

    # ---- verdict ----------------------------------------------------------
    if rep["findings"]:
        rep["verdict"] = "FAIL"
        return "FAIL", rep
    if jt["verdict"] == "PASS":
        rep["verdict"] = "PASS"
        return "PASS", rep
    rep["verdict"] = "INCOMPLETE"
    rep["missing_authority"] = (
        "per-layer Jmax (PDK tech LEF DCCURRENTDENSITY, or a --jmax JSON)")
    rep["missing_authority_reason"] = jt.get("skip_reason")
    if not supply_screen["screened"]:
        rep["missing_authority"] += (
            "; and the net supply current (Total power / Supply voltage) the "
            "EM report would have to declare for the physical-impossibility "
            "screen")
    # TYPED (#1978). `_flow_reason_taxonomy.infer_nonverdict_reason` is
    # deliberately fail-closed: an rc=2 carrying no DECLARED class is booked
    # EXECUTION_ERROR — "the gate blew up". This gate does not blow up here; it
    # opens what it can find, counts what it read, and refuses because the
    # count is zero. Only the PRODUCER can say which refusal this is, so it
    # says so in the field `report_reason_class` reads, and never in prose.
    # Its own docstring already asked producers to do this and this one did
    # not, which is the whole of the change.
    #
    # ZERO_DENOMINATOR IS NOT SKIP-ELIGIBLE. Publishing it cannot return this
    # gate to the VACUOUS-PASS tier and cannot green any assertion — the step
    # renders INCOMPLETE either way (measured, both directions). What changes
    # is that the row a reviewer reads stops saying the program crashed.
    #
    # SCOPE, DELIBERATELY NARROW: only when the denominator is MEASURABLY zero
    # — nothing was read at all. The INCOMPLETE tier is also reachable with
    # peaks in hand and no Jmax authority, and that is a different state with a
    # different honest class; it is left to the fail-closed inference rather
    # than guessed at here.
    #
    # `missing_authority_reason` (`em_report_absent`) STAYS. It is the reason
    # for THIS instance; `reason_class` is the classification. Neither replaces
    # the other, and a reader needs both to know where to go next.
    if not peaks and not authority:
        rep["reason_class"] = _reason_taxonomy.ZERO_DENOMINATOR
    return "INCOMPLETE", rep


def _segments_screened(project: Path, jt: Dict[str, Any]) -> Tuple[int, int]:
    """``(screened, total)`` for the Jmax tier's denominator disclosure.

    When the tier refuses BEFORE reading segments — the Jmax reference is
    resolved first — its summary is absent and the naive answer is "0 of 0",
    which reads as "there was nothing to screen" when in fact there were
    thousands. The total then comes from the report family's own
    ``segments_analysed``, so the disclosure says how much went UNSCREENED.
    """
    s = jt.get("summary") or {}
    screened = int(s.get("segments_screened") or 0)
    total = int(s.get("segments_total") or 0)
    if total:
        return screened, total
    for fp in discover(project, _JSON_GLOBS):
        try:
            doc = json.loads(fp.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        n = doc.get("segments_analysed") if isinstance(doc, dict) else None
        if isinstance(n, int) and not isinstance(n, bool) and n > total:
            total = n
    return screened, total


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", nargs="?", default=".",
                    help="project directory (default: cwd)")
    ap.add_argument("--jmax", default=None,
                    help="per-layer Jmax JSON (overrides discovery)")
    ap.add_argument("--tech-lef", default=None,
                    help="PDK tech LEF carrying DCCURRENTDENSITY / THICKNESS")
    ap.add_argument("--margin", type=float, default=0.10,
                    help="Jmax guardband forwarded to em_current_density_check")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project = Path(args.project)
    if not project.is_dir():
        print(f"ERROR: {args.project!r} is not a directory", file=sys.stderr)
        return RC_ARG
    if not (0.0 <= args.margin < 1.0):
        print("ERROR: --margin must be in [0, 1)", file=sys.stderr)
        return RC_ARG

    verdict, rep = evaluate(project, Path(args.jmax) if args.jmax else None,
                            Path(args.tech_lef) if args.tech_lef else None,
                            args.margin)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n")

    ss = rep["supply_current_screen"]
    jt = rep["jmax_screen"]
    screened, total = _segments_screened(project, jt)
    # A PASS must say how much it looked at AND what it compared against.
    scope = (f"read {len(rep['peak_currents_read'])} peak-current figure(s) and "
             f"{len(rep['supply_authority'])} declared supply authority(ies); "
             f"{screened} of {total} segment(s) screened against Jmax")

    if verdict == "FAIL":
        print(f"[FAIL] {TOOL}: {scope}")
        for f in rep["findings"]:
            print(f"  - {f.get('rule')}: {f.get('message')}")
        return RC_FINDINGS

    if verdict == "PASS":
        s = jt.get("summary") or {}
        print(f"[PASS] {TOOL}: {scope}. Compared against Jmax from "
              f"{jt.get('jmax_source')!r} (worst utilization "
              f"{s.get('worst_utilization')}, margin {args.margin}) and "
              f"against the net supply current "
              f"{ss.get('supply_current_A')!r} A (ratio {ss.get('ratio')}, "
              f"limit 1.0)")
        return RC_OK

    # INCOMPLETE. The token must START A LINE, and it must survive the
    # consumer's tail cut: `flow_compliance_check.output_snippet` keeps only
    # the LAST `_OUTPUT_SNIPPET_CHARS` (300) characters of stdout, so a
    # sentinel printed at the top of a long paragraph is deleted before any
    # tier is decided — MEASURED, that is exactly what a first draft of this
    # gate did (`_stdout_signals_token` returned False on a gate that had
    # printed the token). The detail therefore goes FIRST and the sentinel is
    # the SHORT LAST LINE.
    if ss.get("screened"):
        settled = (f"the physical-impossibility screen PASSED: peak "
                   f"{ss['peak_current_A']:.4e} A vs supplied "
                   f"{ss['supply_current_A']:.4e} A "
                   f"(ratio {ss['ratio']:.4g}, limit 1.0, authority "
                   f"{ss['authority']})")
    else:
        settled = ("no comparison was possible: the report declares neither a "
                   "peak segment current nor a supply authority")
    print(f"{TOOL}: {scope}.")
    print(f"  {settled}.")
    print(f"  A current that is physically possible can still be far over the "
          f"metal's Jmax, so the screen above is a floor, not an EM pass.")
    print(f"INCOMPLETE: electromigration was NOT screened — missing authority: "
          f"{rep['missing_authority']} ({rep.get('missing_authority_reason')}); "
          f"{screened} of {total} segment(s) screened against Jmax.")
    # A REFUSAL EXITS 2, NOT 0 (vibe-ic#1017). See the module docstring: this
    # line says the screen did not happen, and until #1017 the next line handed
    # a blocking clause a clean PASS anyway.
    return RC_NOT_SCREENED


if __name__ == "__main__":
    sys.exit(main())
