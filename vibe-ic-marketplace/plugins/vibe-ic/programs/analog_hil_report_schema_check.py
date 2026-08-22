#!/usr/bin/env python3
"""analog_hil_report_schema_check.py — structural validation of hw_tuning_report.json.

The analog-hw-tuning-loop skill documents the exact output shape of
hw_tuning_report.json. Whether a file conforms to that schema is purely
structural — no judgment — so it is a deterministic check.

Required schema:
    {
      "block_name": <non-empty string>,
      "converged":  <bool>,
      "total_iterations": { "spice": <int>=0>, "hardware": <int>=0> },
      "final_comparison": {
        "<metric>": { "spec": <number>, "spice": <number>,
                      "hw": <number>, "discrepancy_pct": <number>=0> },
        ...  (>= 1 metric)
      },
      "convergence_status": one of _VALID_STATUS (see below)
    }

THE convergence_status VOCABULARY (repaired — it used to accept only half of it)
-------------------------------------------------------------------------------
`skills/analog-hw-tuning-loop/SKILL.md` names TWO vocabularies for the same
field and never says which one a producer must write:

  * the "Convergence criteria" tiers, §"Convergence criteria" / the JSON
    example — IDEAL / CONVERGED / WARNING; and
  * the four-row decision table, §"Three-way comparison logic" — CONVERGED /
    CONVERGED_WARNING / MODEL_INACCURACY / BACK_TO_PHASE1, which is what
    `programs/analog_hil_three_way_verdict.py` COMPUTES from the very same
    `final_comparison` block of the very same file.

This program used to accept only the first list. Measured on one report per
status: CONVERGED_WARNING, MODEL_INACCURACY and BACK_TO_PHASE1 each came back
`FAIL … not in ['CONVERGED','IDEAL','WARNING']`. MODEL_INACCURACY is the honest
"hardware disagrees with SPICE" outcome — reporting it as a SCHEMA violation
buries a real bench finding under a format complaint, i.e. fails the run for the
wrong reason. So the accepted set is now the UNION, and the cross-field rules
carry the meaning instead:

  * IDEAL / CONVERGED                 ⇒ converged must be true
  * MODEL_INACCURACY / BACK_TO_PHASE1 ⇒ converged must NOT be true
    (these are the two verdicts `analog_hil_three_way_verdict` FAILs on; a
     report claiming convergence while carrying a non-converged verdict is a
     genuine self-contradiction, and this is the rule that replaces the
     rejection)
  * WARNING / CONVERGED_WARNING       ⇒ either (that is what a warning means)

PASS  iff the report has every required field with the right type/range and the
      cross-field rules hold.
FAIL  iff a required field is missing / wrong-typed / out-of-range, or a
      cross-field rule is violated (real defect: a downstream consumer — e.g.
      analog-hardmacro-gen — would mis-handle a malformed convergence report).
      A garbage / unparseable file is a FAIL, never a pass.
NOT CHECKED (exit 2) iff there is no hw_tuning_report.json to validate. This is
      exit 2 and NOT exit 0 deliberately: wired into a flow gate, exit 0 is
      recorded as "ran and found nothing wrong", which is the substitution this
      repo removes everywhere else. Exit 2 is the disclosed
      cannot-judge tier (`flow_compliance_check` renders it as a VACUOUS-PASS
      hint on a blocking slot and as "n/a (input not present)" on an advisory
      slot); either way the report SAYS the schema was not checked.

Usage:
    python3 analog_hil_report_schema_check.py <project_dir> [--json <out>]
    python3 analog_hil_report_schema_check.py --file <report.json> [--json <out>]

Exit codes:
    0  PASS
    1  FAIL (schema / consistency violation, incl. unparseable JSON)
    2  NOT CHECKED (no report present) / argument / I/O error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

try:
    import _path_layout as _pl
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _path_layout as _pl


# The two documented vocabularies, unioned. Left column: the "Convergence
# criteria" tiers. Right column: the four-row decision table that
# analog_hil_three_way_verdict computes. See the module docstring for why both
# are accepted and which cross-field rule replaces the rejection.
_TIER_STATUS = {"IDEAL", "CONVERGED", "WARNING"}
_VERDICT_STATUS = {"CONVERGED", "CONVERGED_WARNING",
                   "MODEL_INACCURACY", "BACK_TO_PHASE1"}
_VALID_STATUS = _TIER_STATUS | _VERDICT_STATUS
_STATUS_REQUIRES_CONVERGED = {"IDEAL", "CONVERGED"}
# The two verdicts analog_hil_three_way_verdict FAILs on: a report cannot carry
# one of them and simultaneously claim `converged: true`.
_STATUS_REQUIRES_NOT_CONVERGED = {"MODEL_INACCURACY", "BACK_TO_PHASE1"}
_NUM = (int, float)


@dataclass
class BlockSchema:
    block: str
    source: str
    verdict: str            # PASS / FAIL
    violations: List[str] = field(default_factory=list)


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _is_num(x) -> bool:
    return isinstance(x, _NUM) and not isinstance(x, bool)


def validate(data) -> List[str]:
    """Return a list of violation strings (empty list == conforms)."""
    v: List[str] = []
    if not isinstance(data, dict):
        return ["top-level JSON is not an object"]

    bn = data.get("block_name")
    if not (isinstance(bn, str) and bn.strip()):
        v.append("block_name missing or not a non-empty string")

    if not isinstance(data.get("converged"), bool):
        v.append("converged missing or not a bool")

    ti = data.get("total_iterations")
    if not isinstance(ti, dict):
        v.append("total_iterations missing or not an object")
    else:
        for key in ("spice", "hardware"):
            val = ti.get(key)
            if not _is_int(val):
                v.append(f"total_iterations.{key} missing or not an int")
            elif val < 0:
                v.append(f"total_iterations.{key} is negative ({val})")

    fc = data.get("final_comparison")
    if not isinstance(fc, dict) or not fc:
        v.append("final_comparison missing or empty")
    else:
        for metric, m in fc.items():
            if not isinstance(m, dict):
                v.append(f"final_comparison.{metric} is not an object")
                continue
            for fld in ("spec", "spice", "hw", "discrepancy_pct"):
                if fld not in m:
                    v.append(f"final_comparison.{metric}.{fld} missing")
                elif not _is_num(m[fld]):
                    v.append(f"final_comparison.{metric}.{fld} is not a number")
            dp = m.get("discrepancy_pct")
            if _is_num(dp) and dp < 0:
                v.append(f"final_comparison.{metric}.discrepancy_pct is negative ({dp})")

    status = data.get("convergence_status")
    if status not in _VALID_STATUS:
        v.append(f"convergence_status {status!r} not in {sorted(_VALID_STATUS)}")
    elif status in _STATUS_REQUIRES_CONVERGED and data.get("converged") is not True:
        v.append(f"convergence_status={status!r} but converged is not true")
    elif (status in _STATUS_REQUIRES_NOT_CONVERGED
            and data.get("converged") is True):
        v.append(f"convergence_status={status!r} is a non-converged verdict "
                 f"but converged is true")

    return v


def evaluate_file(path: Path) -> BlockSchema:
    block_name = path.parent.name
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return BlockSchema(block=block_name, source=str(path), verdict="FAIL",
                           violations=["unreadable / malformed JSON"])
    viol = validate(data)
    block = (data.get("block_name") if isinstance(data, dict) else None) or block_name
    return BlockSchema(block=block, source=str(path),
                       verdict="FAIL" if viol else "PASS", violations=viol)


def run(project: Optional[Path], single_file: Optional[Path]) -> dict:
    blocks: List[BlockSchema] = []
    if single_file is not None:
        blocks.append(evaluate_file(single_file))
    else:
        analog_dir = _pl.analog_dir(project)
        if not analog_dir.is_dir():
            return {"gate": "analog_hil_report_schema_check", "verdict": "SKIP",
                    "reason": "no phase3/analog directory", "blocks": []}
        reports = sorted(analog_dir.glob("*/hw_tuning_report.json"))
        if not reports:
            return {"gate": "analog_hil_report_schema_check", "verdict": "SKIP",
                    "reason": "no hw_tuning_report.json under analog/", "blocks": []}
        for rp in reports:
            blocks.append(evaluate_file(rp))

    if not blocks:
        overall = "SKIP"
    elif any(b.verdict == "FAIL" for b in blocks):
        overall = "FAIL"
    else:
        overall = "PASS"
    return {
        "gate": "analog_hil_report_schema_check",
        "verdict": overall,
        "valid_statuses": sorted(_VALID_STATUS),
        "blocks": [asdict(b) for b in blocks],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", nargs="?", default=None)
    ap.add_argument("--file", default=None,
                    help="validate a single hw_tuning_report.json directly")
    ap.add_argument("--json", default=None, help="write JSON report to this path")
    args = ap.parse_args(argv)

    single = Path(args.file) if args.file else None
    project = Path(args.project_dir).resolve() if args.project_dir else None
    if single is None and project is None:
        print("error: provide <project_dir> or --file <report.json>", file=sys.stderr)
        return 2
    if single is not None and not single.is_file():
        print(f"error: file not found: {single}", file=sys.stderr)
        return 2
    if single is None and not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    report = run(project, single)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    verdict = report["verdict"]
    label = "NOT CHECKED" if verdict == "SKIP" else verdict
    print(f"[{label}] analog_hil_report_schema_check"
          + (f" — {report.get('reason', 'nothing to validate')}"
             if verdict == "SKIP" else ""))
    for b in report["blocks"]:
        print(f"  [{b['verdict']}] block={b['block']}")
        for vmsg in b.get("violations", []):
            print(f"      {vmsg}")

    # 0 PASS / 1 FAIL / 2 NOT CHECKED — see the module docstring for why the
    # no-artefact tier is 2 and not 0.
    if verdict == "SKIP":
        return 2
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
