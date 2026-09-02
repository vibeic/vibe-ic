#!/usr/bin/env python3
"""
mixed_signal_merge_check.py — M1 gate (v0.2.84: SUBSTANCE, not presence).

M1 — A+D top-level GDS merge (no overlap, all macro pins on tracks)

v0.2.84 (flow-completeness review): the v1.6.13 PASS-on-presence stub
is RETIRED. A merged GDS is a CLAIM; the claim needs the top-level
LVS that `mixed_signal_top_lvs_run.py` executes (KLayout merge +
Magic extraction + real netgen compare). PASS now requires
`reports/analog/mixed_signal/top_lvs.json` with verdict PASS.

Behaviour
---------
* SKIP (rc=2) — top_merged.gds missing AND step not waived. The report
  carries an explicit `reason_class` saying WHY there is no verdict:
  `DESIGN_DECLARED_NA` when the project declares no analog blocks (there is
  no A+D top to merge), `BLOCKED_BY_UPSTREAM` when it does and the merge
  producer has not run. See the note above `main` for the measurement.
* WAIVED (rc=0) — `waivers.json` declares step waived (evidence + ticket).
* PASS (rc=0) — merged GDS present AND top-level LVS verdict PASS.
* FAIL (rc=1) — merged GDS present but top-level LVS missing or FAIL
  (presence is not substance).

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded.

Usage
-----
    python3 mixed_signal_merge_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402  vibe-ic#1082 (helper from PR #1094)
import _flow_reason_taxonomy as _reason_taxonomy  # noqa: E402  vibe-ic#1978
from mixed_signal_signoff_check import _analog_applicable  # noqa: E402


# ── WHY THIS GATE PUBLISHES A `reason_class` (vibe-ic#1978/#2014) ──────────
# `_flow_reason_taxonomy` is deliberately fail-closed: an rc=2 non-verdict that
# carries no explicit class, and whose prose no recogniser matches, is an
# EXECUTION_ERROR — which is NOT skip-eligible, so the consuming step lands on
# INCOMPLETE rather than VACUOUS_PASS. That default is right; what was missing
# is this producer's own statement about WHY it returned no verdict.
#
# MEASURED on the pinned runtime image, against a tree carrying no
# mixed-signal artefacts, before this change:
#
#     rc 2, stdout "verdict: SKIP / missing:
#     ['phase3/mixed_signal/top_merged.gds']"
#     -> infer_nonverdict_reason(...) = EXECUTION_ERROR
#     -> flow_compliance_check.check_step(...) = INCOMPLETE
#
# Nothing had gone wrong in the execution: the project declares no analog
# blocks, so there is no A+D top to merge and this M1 gate does not apply. The
# taxonomy module says producers should publish the class whenever they can,
# and this one can — it already knows the two cases apart:
#
#   * no analog_block_list.json with a non-empty `blocks` list
#         -> the DESIGN declares no analog content -> DESIGN_DECLARED_NA
#            (skip-eligible: VACUOUS_PASS)
#   * blocks ARE declared and `top_merged.gds` is still absent
#         -> the merge producer has not run -> BLOCKED_BY_UPSTREAM
#            (not skip-eligible: INCOMPLETE, which is the honest answer and is
#            STRICTER than the pre-#1978 blanket VACUOUS_PASS)
#
# The applicability predicate is the one the sibling M4 gate already ships
# (`mixed_signal_signoff_check._analog_applicable`) rather than a fourth
# private copy of the same candidate-root list, so the two M-track gates cannot
# disagree about whether the track applies to a project.


def _load_waivers(project):
    p = project / "waivers.json"
    if not p.is_file():
        return []
    try:
        return (json.loads(p.read_text()).get("waived_steps") or [])
    except Exception:
        return []


def _step_waived(project, step_label):
    for w in _load_waivers(project):
        sid = str(w.get("id", "")).strip()
        ticket = w.get("ticket", "")
        if sid == step_label or step_label in ticket:
            return w
    return None


_GATE_NAME = 'mixed_signal_merge_check'
_GATE_LABEL = 'mixed_signal_merge'
_REQUIRED_FILES = ['phase3/mixed_signal/top_merged.gds']
_WAIVER_RATIONALE = 'Top-level merge+LVS not runnable in this environment (see mixed_signal_top_lvs_run SKIP reason).'


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    parser.add_argument("--step-label", default=_GATE_LABEL)
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}", file=sys.stderr)
        return 2

    found = [p for p in _REQUIRED_FILES if list(project.glob(p))]
    missing = [p for p in _REQUIRED_FILES if p not in found]

    waiver = _step_waived(project, args.step_label)
    reason_class = None
    skip_reason = None
    if missing and not waiver:
        verdict, rc = "SKIP", 2
        applicable, evidence = _analog_applicable(project)
        if applicable:
            reason_class = _reason_taxonomy.BLOCKED_BY_UPSTREAM
            skip_reason = (
                f"the mixed-signal track APPLIES to this project ({evidence}) "
                f"but {missing} is absent, so the merge producer has not run; "
                f"nothing here examined a merged layout")
        else:
            reason_class = _reason_taxonomy.DESIGN_DECLARED_NA
            skip_reason = (
                f"the design declares no analog content ({evidence}), so there "
                f"is no A+D top-level layout to merge and this M1 gate does not "
                f"apply; {missing} is absent for that reason and not because a "
                f"producer failed")
        findings = [{"severity": "INFO", "rule": "REQUIRED_FILES_MISSING",
                      "message": f"missing: {missing} — {skip_reason}"}]
    elif missing and waiver:
        verdict, rc = "WAIVED", 0
        findings = [{"severity": "WAIVED", "rule": "STEP_WAIVED",
                      "message": f"waiver={waiver.get('ticket','?')}: {waiver.get('reason','?')}"}]
    else:
        # v0.2.84 — SUBSTANCE: the merged GDS must be LVS-substantiated
        # by mixed_signal_top_lvs_run (Magic extraction + real netgen
        # compare). Presence alone never PASSes again.
        top_lvs = None
        for rel in ("reports/analog/mixed_signal/top_lvs.json",
                     "reports/mixed_signal/top_lvs.json"):
            cand = project / rel
            if cand.is_file():
                try:
                    top_lvs = json.loads(cand.read_text(errors="replace"))
                except (OSError, ValueError):
                    top_lvs = {"verdict": "UNPARSEABLE"}
                break
        if top_lvs is None:
            verdict, rc = "FAIL", 1
            findings = [{"severity": "ERROR",
                          "rule": "MERGE_NOT_LVS_SUBSTANTIATED",
                          "message": ("top_merged.gds present but no "
                                      "top-level LVS result — run "
                                      "mixed_signal_top_lvs_run; a merge "
                                      "claim without LVS is presence, "
                                      "not substance (v0.2.84)")}]
        elif str(top_lvs.get("verdict")) == "PASS":
            verdict, rc = "PASS", 0
            findings = [{"severity": "INFO", "rule": "MERGE_LVS_OK",
                          "message": ("merged GDS present + top-level "
                                      "netgen LVS PASS "
                                      f"({top_lvs.get('lvs_report', '?')})")}]
        elif str(top_lvs.get("verdict")) == "SKIP":
            # vibe-ic#614 — a SKIP means NO COMPARISON WAS PERFORMED, and this
            # branch used to publish it as "the merged layout does not match
            # the schematic". That is a statement about the ENVIRONMENT
            # published as a statement about the DESIGN, and in `merge.json` it
            # was indistinguishable from a real mismatch: the same producer,
            # run where it can see the project, returns FAIL with
            # `compared: true` and a netgen report — a materially different
            # fact flattened into one message.
            #
            # Still non-PASS: a step that returned no verdict must not pass.
            # The producer's own reason travels verbatim rather than being
            # re-narrated.
            verdict, rc = "FAIL", 1
            findings = [{"severity": "ERROR", "rule": "MERGE_LVS_NOT_RUN",
                          "message": ("top-level LVS did NOT run, so nothing "
                                      "compared the merged layout to the "
                                      "schematic — this is not a mismatch, it "
                                      "is an absent comparison. Producer "
                                      f"reason: {top_lvs.get('reason', '(none stated)')}")}]
        else:
            verdict, rc = "FAIL", 1
            findings = [{"severity": "ERROR", "rule": "MERGE_LVS_FAIL",
                          "message": ("top-level LVS verdict "
                                      f"{top_lvs.get('verdict')!r} — the "
                                      "merged layout does not match the "
                                      "schematic")}]

    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": args.step_label,
        "required_files": _REQUIRED_FILES,
        "found": found,
        "missing": missing,
        "waiver": waiver,
        "rationale_when_skipped": _WAIVER_RATIONALE,
        "findings": findings,
    }
    if reason_class:
        # Both keys, on purpose: `reason_class` is what
        # `_flow_reason_taxonomy.report_reason_class` reads, and `reason` is
        # what `_report_reason_text` publishes beside it so a reader is not
        # left with a bare taxonomy token.
        out["reason_class"] = reason_class
        out["reason"] = skip_reason
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    if missing:
        print(f"  missing: {missing}")
    if waiver:
        print(f"  waiver:  {waiver.get('ticket','?')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
