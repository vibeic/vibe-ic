#!/usr/bin/env python3
"""professional_tb_check.py — Phase-2 gate for the professional cocotb TB path.

(No `ENFORCEMENT:` line on purpose. This gate is wired BLOCKING in the flow —
Step 4 `program_exit_zero` — but `flow_gate_enforcement_audit` reserves
"blocking" for a gate a RUNNER invokes inline, and no runner invokes this one;
it runs through flow_compliance_check. Declaring an intent this program does
not satisfy in that audit's own terms is the paper-wiring the audit exists to
find, so the declaration is left off and the wiring is described here instead.)

Verifies the NEW TB path (professional_tb_gen, wired into Phase-2 by
design_one_shot_runner.step_professional_tb_gen) never silently passes a real
functional mismatch, and that the bundle the producer says it wrote is
actually on disk. It reads the step's own report
(reports/phase2/gates/professional_tb.json) and enforces:

  * functional_mismatch == true  -> FAIL (exit 1): the streaming / closed-form
    scoreboard actually RAN and recorded >0 mismatched vectors — a real RTL bug
    that must NOT be waived away (no silent vacuous pass).
  * a DECLARED bundle that is INCOMPLETE where the bundle tree IS present
    -> FAIL (exit 1). See below.
  * a DECLARED bundle whose whole tree is absent from this copy of the project
    -> NOT_CHECKED (exit 2), the disclosed-skip tier. See below.
  * status PASS/WAIVED/SKIP with functional_mismatch false and a complete
    bundle -> PASS (exit 0): either functional verification CLOSED (cocotb ran,
    0 mismatches), or the TB was honestly generated with the run deferred
    (tooling unreachable / generic reference-hook class), or the class exposes
    no derivable reference.
  * report absent -> NOT_APPLICABLE (exit 0): the step did not run for this
    project, so there is nothing to judge — never a false FAIL. (The gate is
    wired UNCONDITIONALLY in Step 4 for exactly this reason, vibe-ic#236: a
    conditional wiring is an invisible skip. An earlier version of this
    docstring still claimed the wiring was conditional on the report existing;
    it has not been since #236.)

BUNDLE COMPLETENESS (the outputs nothing verified)
--------------------------------------------------
`professional_tb_gen.generate()` writes a durable bundle —
`tb_<top>.py`, `<top>_coverage_model.json`, `<top>_assertions.sva`,
`Makefile`, `verification_plan.json` — under
`phase2/stage1/sim_professional/<top>/`, and RECORDS it in the report as
`out_dir` + `files`. Nothing read that declaration back: Step 4's
`required_outputs` names none of those paths, and this gate looked only at
`functional_mismatch`. So the producer's own list of what it wrote was
unverifiable.

It is checked HERE rather than added to `required_outputs` on purpose:
`required_outputs` is ALL-of-N (PR #455) and `step_professional_tb_gen`
legitimately SKIPs for a class with no derivable arithmetic/streaming
interface, so declaring the bundle there would manufacture a MISSING for
every such design. Keying off the producer's own `status`/`files`
declaration cannot fire when the generator did not generate.

THREE ANSWERS, NOT TWO — and why the third one is not a loophole
-----------------------------------------------------------------
The producer records an ABSOLUTE `out_dir` from the host it ran on, so on any
copied / relocated project that string is meaningless. That leaves three
genuinely different states, and collapsing them into PASS/FAIL gets one of
them wrong whichever way it is collapsed:

  1. the bundle tree `phase2/stage1/sim_professional/` is present and the
     DECLARED files are all there and non-empty          -> PASS   (exit 0)
  2. that tree is PRESENT but a declared file is missing or empty
                                                          -> FAIL   (exit 1)
     This is the defect the check exists for, and it stays BLOCKING.
  3. that tree is ABSENT from this copy of the project entirely -> exit 2,
     NOT_CHECKED. The gate looked and there was nothing of this kind to look
     at. Calling that PASS would be the false-clean this change is fixing;
     calling it FAIL asserts a defect from an absent input, which is the
     opposite error and the one measured below.

MEASURED, and it is why (3) exists. Over the 9 tracked projects in
`benchmark-data` carrying a `reports/phase2/gates/professional_tb.json`, 3
(`ic/spm/v1.5.58_ihp-sg13g2`, `v1.5.65_sky130A`, `v1.5.66_gf180mcuD`) declare
a 5-file bundle and carry no `sim_professional/` tree at all — the snapshot
was published without it. Answering those FAIL would turn 3 of 9 published
runs red on a BLOCKING Step-4 slot for a snapshotting artefact, not for
anything the run did. rc=2 is the tier this repo already has for exactly
that: `flow_compliance_check._check_program_exit_zero` maps it through
`_VACUOUS_HINT_PREFIX` to a disclosed "n/a (input not present)", counted and
rendered as VACUOUS, never as a clean result. Blast radius after this change:
0 verdict flips over those 9, with the 3 disclosing rc=2.

RESOLUTION IS PROJECT-SCOPED, AND DOES NOT WALK
------------------------------------------------
`_resolve_bundle_dir` tries the canonical layout slot and a declared path that
is literally inside the project. It does NOT glob `**/sim_professional/<name>`.
That walk was in an earlier revision of this change and it leaked ACROSS
scopes: a project with no bundle of its own was certified by a bundle
belonging to a NESTED snapshot, with `resolved_out_dir` pointing into the
nested tree (reproduced; `ic/sha256` and `ic/u_hawaii_adc` both carry the
triggering `clean_run_*` shape). That is the same defect class PR #485 item 6
removes from `eda_report_audit`; a `**` walk from a project root cannot tell
this project's evidence from a child run's. Pinned by
`test_DEFECT_nested_snapshot_bundle_does_not_certify_outer_project`.

FUNCTIONAL COVERAGE — MEASURED AND DISCLOSED, NOT ENFORCED
----------------------------------------------------------
The generated TB exports cocotb-coverage results to `coverage_<top>.xml`, and
`<top>_coverage_model.json` declares `closure_policy.functional_bins_required_pct`.
Nothing compared them. When both are present this gate now records the
comparison in its JSON output and prints it.

It does NOT block on it, and the reason is stated so the choice is
reviewable: `professional_tb_gen` emits a fixed 100 % closure policy while
its stimulus makes no attempt to hit the declared bins (measured on the
reference spm x ihp-sg13g2 run: `cover_percentage=12.5`, 2 of 16 bins, against
a declared 100 %). Blocking on it would fail essentially every design for a
PRODUCER defect — the generator declaring a goal it does not drive toward.
Closing that is a stimulus change (directed vectors for declared bins) and a
flow-owner decision; recording the number turns an invisible gap into a
disclosed one in the meantime.

chip-AGNOSTIC: no chip / vendor / SKU literal; keys off the report and the
producer's own declarations only.
Contract: exit 0 = PASS / N-A, exit 1 = functional mismatch or a declared
bundle that is incomplete where its tree IS present, exit 2 = NOT CHECKED
(the declared bundle tree is absent from this copy of the project) or IO error.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

import _path_layout as _pl


def _bundle_root(project: Path) -> Path:
    """The tree the producer writes every bundle under, for THIS project.

    Uses the shared layout helper rather than a private literal so this gate
    and the producer (`professional_tb_gen`, which resolves
    ``rtl_dir(project).parent / "sim_professional" / top``) cannot drift.
    """
    return _pl.phase2_stage1_dir(project) / "sim_professional"


def _resolve_bundle_dir(project: Path, out_dir: Any) -> Optional[Path]:
    """Resolve the producer's declared `out_dir` INSIDE `project`.

    The producer records an ABSOLUTE path from the host it ran on, so the
    literal string does not survive a moved/copied project. Resolution is
    deliberately project-SCOPED and deliberately does NOT walk: only the
    canonical layout slot and a declared path that is literally inside this
    project are accepted. An earlier revision fell back to
    ``project.glob("**/sim_professional/<name>")`` and took ``hits[0]``, which
    let a NESTED snapshot's bundle certify the OUTER project — see the
    docstring section on scoping.
    """
    if not out_dir:
        return None
    raw = Path(str(out_dir))
    name = raw.name
    if not name:
        return None
    cand = _bundle_root(project) / name
    if cand.is_dir():
        return cand
    literal = raw if raw.is_absolute() else (project / raw)
    try:
        literal.resolve().relative_to(project.resolve())
    except (ValueError, OSError):
        return None
    return literal if literal.is_dir() else None


def _bundle_report(project: Path, rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Verify every file the producer DECLARED it wrote.

    Returns ``None`` when the producer declared no bundle (SKIP class, or an
    older report) — nothing was claimed, so nothing is owed.

    ``state`` distinguishes the two ways a bundle can fail to resolve:
    ``"incomplete"`` (the bundle tree IS present in this project, so a
    missing file is a real defect -> FAIL) from ``"tree_absent"`` (this copy
    of the project carries no ``sim_professional/`` tree at all, so there was
    nothing of this kind to examine -> the disclosed rc=2 tier).
    """
    files = rec.get("files")
    out_dir = rec.get("out_dir")
    if not isinstance(files, list) or not files or not out_dir:
        return None
    resolved = _resolve_bundle_dir(project, out_dir)
    if resolved is None:
        tree_present = _bundle_root(project).is_dir()
        return {"declared_out_dir": str(out_dir), "resolved_out_dir": None,
                "bundle_root": str(_bundle_root(project)),
                "bundle_root_present": tree_present,
                "state": "incomplete" if tree_present else "tree_absent",
                "declared": [str(f) for f in files],
                "missing": [str(f) for f in files], "empty": []}
    missing: List[str] = []
    empty: List[str] = []
    for f in files:
        p = resolved / str(f)
        if not p.is_file():
            missing.append(str(f))
        elif p.stat().st_size == 0:
            empty.append(str(f))
    return {"declared_out_dir": str(out_dir),
            "resolved_out_dir": str(resolved),
            "bundle_root": str(_bundle_root(project)),
            "bundle_root_present": True,
            "state": "incomplete" if (missing or empty) else "complete",
            "declared": [str(f) for f in files],
            "missing": missing, "empty": empty}


def _functional_coverage(bundle_dir: Optional[Path]) -> Optional[Dict[str, Any]]:
    """Measured functional-bin coverage vs the model's OWN declared policy.

    Returns ``None`` when either side is absent (no cocotb export, or a model
    that declares no closure policy) — an absent input is reported as absent,
    never as closed.
    """
    if bundle_dir is None or not bundle_dir.is_dir():
        return None
    exports = sorted(bundle_dir.glob("coverage_*.xml"))
    models = sorted(bundle_dir.glob("*_coverage_model.json"))
    if not exports or not models:
        return None
    required: Optional[float] = None
    try:
        model = json.loads(models[0].read_text(errors="ignore"))
        policy = (((model or {}).get("fields") or {}).get("closure_policy")
                  or {})
        raw = policy.get("functional_bins_required_pct")
        if raw is not None:
            required = float(raw)
    except (OSError, ValueError, TypeError):
        required = None
    if required is None:
        return None
    try:
        root = ET.parse(exports[0]).getroot()
        measured = float(root.attrib["cover_percentage"])
    except (OSError, ET.ParseError, KeyError, ValueError, TypeError) as e:
        return {"export": exports[0].name, "model": models[0].name,
                "measured_pct": None, "required_pct": required,
                "closed": None, "error": f"unreadable coverage export: {e}",
                "enforcement": "DISCLOSED_NOT_BLOCKING"}
    return {"export": exports[0].name, "model": models[0].name,
            "measured_pct": measured, "required_pct": required,
            "closed": measured >= required,
            "enforcement": "DISCLOSED_NOT_BLOCKING",
            "note": ("professional_tb_gen emits a fixed closure policy its own "
                     "stimulus does not drive toward; blocking here would fail "
                     "designs for a producer defect. Recorded so the gap is "
                     "visible, not enforced.")}


def check(project: Path) -> Dict[str, Any]:
    report = project / "reports" / "phase2" / "gates" / "professional_tb.json"
    if not report.is_file():
        return {"gate": "professional_tb", "verdict": "NOT_APPLICABLE",
                "reason": "no professional_tb.json (step did not run)"}
    try:
        rec = json.loads(report.read_text(errors="ignore"))
    except (OSError, ValueError) as e:
        return {"gate": "professional_tb", "verdict": "IO_ERROR", "error": str(e)}
    if not isinstance(rec, dict):
        return {"gate": "professional_tb", "verdict": "IO_ERROR",
                "error": "report is not a JSON object"}
    if bool(rec.get("functional_mismatch")):
        return {"gate": "professional_tb", "verdict": "FAIL",
                "reason": "cocotb functional mismatch — real RTL bug",
                "dut_kind": rec.get("dut_kind"),
                "cocotb_xml_failures": rec.get("cocotb_xml_failures")}

    bundle = _bundle_report(project, rec)
    res: Dict[str, Any] = {
        "gate": "professional_tb", "verdict": "PASS",
        "status": rec.get("status"), "dut_kind": rec.get("dut_kind"),
        "ran_cocotb": rec.get("ran_cocotb"),
    }
    if bundle is not None:
        res["bundle"] = bundle
        fc = _functional_coverage(
            Path(bundle["resolved_out_dir"]) if bundle["resolved_out_dir"]
            else None)
        if fc is not None:
            res["functional_coverage"] = fc
        if bundle["state"] == "tree_absent":
            # The producer declared a bundle, and this copy of the project
            # carries no `sim_professional/` tree at all. The gate examined
            # NOTHING of this kind — that is the disclosed-skip tier, not a
            # clean result (which would be the false-clean this check exists
            # to remove) and not a defect (which would assert a finding from
            # an absent input). See the docstring for the measurement.
            res["verdict"] = "NOT_CHECKED"
            res["reason"] = (
                "professional_tb_gen DECLARED a "
                + str(len(bundle["declared"])) + "-file bundle at "
                + bundle["declared_out_dir"] + ", and this project carries no "
                + bundle["bundle_root"] + " tree at all — nothing of this kind "
                "to examine. DISCLOSED as not-checked, never certified.")
        elif bundle["missing"] or bundle["empty"]:
            res["verdict"] = "FAIL"
            res["reason"] = (
                "professional_tb_gen DECLARED a TB bundle that is not on "
                "disk: missing=" + json.dumps(bundle["missing"])
                + " empty=" + json.dumps(bundle["empty"])
                + " (declared out_dir " + bundle["declared_out_dir"] + ")")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path, nargs="?", default=Path("."))
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    res = check(a.project.resolve())
    txt = json.dumps(res, indent=2)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(txt + "\n")
    print(txt)
    fc = res.get("functional_coverage")
    if isinstance(fc, dict) and fc.get("closed") is False:
        print(f"[finding] functional coverage {fc.get('measured_pct')}% < the "
              f"model's own declared closure policy {fc.get('required_pct')}% "
              f"({fc.get('export')}) — DISCLOSED, not blocking; see this "
              f"program's docstring for why.")
    verdict = res.get("verdict")
    if verdict == "NOT_CHECKED":
        # rc=2, the disclosed-skip tier. `flow_compliance_check` maps rc=2
        # through `_VACUOUS_HINT_PREFIX` to "n/a (input not present)"; the
        # stdout sentinel below is the same signal for readers that scrape
        # output rather than the exit code.
        print("VACUOUS_PASS: professional_tb_check — " + str(res.get("reason")))
        return 2
    if verdict == "NOT_APPLICABLE":
        # vibe-ic#1115. The branch above already gets this right for
        # NOT_CHECKED; NOT_APPLICABLE is the SAME case -- "no
        # professional_tb.json (step did not run)" -- and fell through to a
        # plain rc 0, which `flow_compliance_check` records as PASS. The
        # producer emitted nothing and the checker read the absence as consent.
        # rc stays 0 (an absent optional step must not fail a run); what
        # changes is that the flow stops recording "checked, fine".
        print("VACUOUS_PASS: professional_tb examined 0 testbench report(s) — "
              + str(res.get("reason", "the producing step left nothing to check")))
        return 0
    if verdict == "PASS":
        return 0
    if verdict == "IO_ERROR":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
