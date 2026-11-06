#!/usr/bin/env python3
"""Read native FMEDA injection counts against the requested ASIL/DC floor.

No measured counts yields NOT_MEASURED. An invalid baseline or a diagnostic
coverage below the original floor yields FAIL. Source receipts are not read.
Exit 0 means PASS, 1 means FAIL and 2 means NOT_MEASURED.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import _path_layout as _pl  # noqa: E402
import fmeda_fault_injection_coverage as fi  # noqa: E402


def check(report: dict, asil_override: Optional[str],
          min_dc: Optional[float], project: Optional[Path] = None) -> dict:
    """Read native diagnostic measurements against the requested ASIL/DC floor."""
    import _fmeda_mechanisms as declared

    return declared.consume(project, report, asil_override, min_dc)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir")
    p.add_argument("--report", default=None,
                   help="path to fmeda_coverage.json (default: "
                        "reports/phase2/safety/fmeda_coverage.json)")
    p.add_argument("--asil", default=None)
    p.add_argument("--min-dc", type=float, default=None)
    p.add_argument("--require", action="store_true",
                   help="compatibility option; missing native data is NOT_MEASURED")
    p.add_argument("--json", default=None)
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    rpt_path = (Path(args.report) if args.report
                else _pl.reports_phase2_dir(project) / "safety" /
                "fmeda_coverage.json")
    if not rpt_path.exists():
        res = {"gate": "fmeda_coverage_check", "verdict": "NOT_MEASURED",
               "passed": False, "reason": f"Native report not found: {rpt_path}"}
        rc = 2
    else:
        try:
            report = json.loads(rpt_path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"fmeda_coverage_check: bad report: {e}", file=sys.stderr)
            return 2
        res = check(report, args.asil, args.min_dc, project)
        rc = 0 if res["passed"] else 2 if res["verdict"] == "NOT_MEASURED" else 1

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        res['program'] = 'fmeda_coverage_check'
        Path(args.json).write_text(json.dumps(res, indent=2) + "\n")
    print(f"[{res['verdict']}] fmeda_coverage_check: {res['reason']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
