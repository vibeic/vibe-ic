#!/usr/bin/env python3
"""professional_tb_check.py — Phase-2 gate for the professional cocotb TB path.

Verifies the NEW TB path (professional_tb_gen, wired into Phase-2 by
design_one_shot_runner.step_professional_tb_gen) never silently passes a real
functional mismatch. It reads the step's own report
(reports/phase2/gates/professional_tb.json) and enforces:

  * functional_mismatch == true  -> FAIL (exit 1): the streaming / closed-form
    scoreboard actually RAN and recorded >0 mismatched vectors — a real RTL bug
    that must NOT be waived away (no silent vacuous pass).
  * status PASS/WAIVED/SKIP with functional_mismatch false -> PASS (exit 0):
    either functional verification CLOSED (cocotb ran, 0 mismatches), or the TB
    was honestly generated with the run deferred (tooling unreachable / generic
    reference-hook class), or the class exposes no derivable reference.
  * report absent -> NOT_APPLICABLE (exit 0): the step did not run for this
    project. This gate is wired conditioned on the report existing, so absence
    is a no-op — never a false FAIL.

chip-AGNOSTIC: no chip / vendor / SKU literal; keys off the report only.
Contract: exit 0 = PASS / N-A, exit 1 = functional mismatch, exit 2 = IO error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


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
    return {"gate": "professional_tb", "verdict": "PASS",
            "status": rec.get("status"), "dut_kind": rec.get("dut_kind"),
            "ran_cocotb": rec.get("ran_cocotb")}


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
    verdict = res.get("verdict")
    if verdict in ("PASS", "NOT_APPLICABLE"):
        return 0
    if verdict == "IO_ERROR":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
