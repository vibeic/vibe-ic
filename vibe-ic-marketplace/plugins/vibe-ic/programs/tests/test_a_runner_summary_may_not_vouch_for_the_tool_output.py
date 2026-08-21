#!/usr/bin/env python3
"""Authenticity must come from the TOOL's output, not the RUNNER's summary of it.

THE FINDING, MEASURED (vibe-ic#1119, attack A1_TAMPER_DESTRUCTIVE)
==================================================================
A1 overwrites every `*.rpt` in a published cell with the single line "TAMPERED
BY THE ADVERSARY" and re-runs the sign-off gates. It is the CONTROL attack — it
is supposed to be defended by everything, because a gate needs its evidence to
pass. Six of seven flipped rc 0 -> 1. `ir_drop_report_check` returned 0, and
printed its own reason for doing so::

    "passed": true,
    "findings": [
      {"rule": "IR_DROP_REPORT_TOO_SMALL",  "severity": "ERROR",
       "message": "report 26 B is below minimum 1024 B ...",
       "file": "reports/phase3/ir_drop.rpt"},
      {"rule": "IR_DROP_NO_TOOL_SIGNATURE", "severity": "ERROR",
       "message": "report lacks any known ir_drop tool signature ...",
       "file": "reports/phase3/ir_drop.rpt"}
    ],
    "summary": {"tool_authentic": true, ...}

Two ERROR findings naming the report as a 26-byte forgery, `tool_authentic:
true`, and a PASS.

WHY. `_check_tool_authenticity` returns True when ANY discovered candidate
passes, and the candidate that passed was `reports/phase3/ir_drop.json`. The
attack never touched it — it is not a `.rpt` — and the RUNNER writes it
(`step_canonicalize_artefacts` -> `_emit_ir_em_reports`). That file even names
what it is a summary OF::

    "source": "reports/phase3/ir_drop.rpt",

so the document vouching for the tool's output declared itself a derivative of
the very file that had been destroyed.

THE SHAPE WAS ALREADY ON RECORD. `matrix_63x8/README.md` describes two artefact
findings that closed for this reason — "the gate believed a summary the RUNNER
wrote instead of the output the TOOL wrote" — and says outright that it "is the
shape to look for next".

WHAT THIS FILE HOLDS THE FIX TO
===============================
The fixture reproduces the published cell's situation exactly, and that
precision is the point: the runner json carries a drop value and a tool
signature, so `has_drop_value` stays true and the ONLY thing separating PASS
from FAIL is whether a runner summary may establish authenticity. A fixture
whose tampered arm also lost its drop values would pass this file for the wrong
reason and would keep passing it if the fix were removed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import eda_report_audit as E  # noqa: E402

_CLI_BOUND_S = 60

#: Modelled on the published cell's own `reports/phase3/ir_drop.json`, and
#: modelled CLOSELY on purpose: it must be a document that CAN vouch, or the
#: tampered arm below would fail for a reason other than the finding.
#:
#: The real file is 893 B — under `MIN_REPORT_BYTES["ir_drop"]` (1024) — and is
#: nonetheless accepted as authentic because it carries the whole strong
#: signature group `['openroad-psm', 'analyze_power_grid', 'power_nets']`, which
#: waives the size floor. All three appear here for that reason. It also keeps
#: the `source` back-reference, which is the detail worth not losing: the
#: document that vouched for the tool's output names that output as the thing it
#: is a summary OF.
#:
#: A FIRST VERSION OF THIS FIXTURE OMITTED `analyze_power_grid` and
#: `power_nets`. The json was then inauthentic on its own account, the gate
#: failed the tampered arm with or without the fix, and two of the four tests
#: below passed on a reverted tree — a guard that proved nothing, for exactly
#: the reason this file exists to catch elsewhere.
_RUNNER_JSON = {
    "tool": "openroad-psm",
    "mode": "static_ir_drop",
    "power_nets": ["VDD"],
    "source": "reports/phase3/ir_drop.rpt",
    "worst_ir_uv": 4490.0,
    "budget_uv": 500000.0,
    "worst_ir_mv_note": "worst static IR drop 4.49 mV against the budget",
    "verdict": "PASS",
    "evidence": "analyze_power_grid stdout",
}


def _tool_report(top: str) -> str:
    head = [
        "OpenROAD v2.0 PSM static IR drop analysis",
        f"[INFO ODB-0128] Design: {top}",
        "Worst IR drop: 4.49 mV",
        "IR drop summary: worst 4.49 mV (0.37 %Vdd)",
    ]
    # Padded past MIN_REPORT_BYTES["ir_drop"] (1024) so the size floor is never
    # what the authentic arm is resting on.
    head += [f"  net VDD segment {i:04d}  drop 0.{i:03d} mV" for i in range(40)]
    return "\n".join(head) + "\n"


def _project(root: Path, tamper: bool) -> Path:
    (root / "rtl").mkdir(parents=True, exist_ok=True)
    (root / "rtl" / "my_top.v").write_text(
        "module my_top (input wire clk, output wire q);\n"
        "  assign q = clk;\nendmodule\n", encoding="utf-8")
    rep = root / "reports" / "phase3"
    rep.mkdir(parents=True, exist_ok=True)
    rep.joinpath("ir_drop.json").write_text(
        json.dumps(_RUNNER_JSON, indent=2), encoding="utf-8")
    rep.joinpath("ir_drop.rpt").write_text(
        "TAMPERED BY THE ADVERSARY\n" if tamper else _tool_report("my_top"),
        encoding="utf-8")
    return root


def _audit(project: Path) -> dict:
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "ir_drop_report_check.py"), ".",
         "--mode", "ir_drop"],
        cwd=str(project), capture_output=True, text=True, timeout=_CLI_BOUND_S)
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        doc = {"program": "unparseable", "stdout": r.stdout, "stderr": r.stderr}
    doc["rc"] = r.returncode
    return doc


def test_a_real_tool_report_still_passes(tmp_path):
    """The discriminating twin. Same runner json, genuine tool output."""
    got = _audit(_project(tmp_path / "ok", tamper=False))
    assert got["rc"] == 0, (
        f"authentic tool output was refused; the rule is not discriminating:"
        f"\n{json.dumps(got, indent=2)}")
    assert got["summary"]["tool_authentic"] is True


def test_a_destroyed_tool_report_is_not_rescued_by_the_runner_json(tmp_path):
    """THE FINDING. The tool's output is a 26-byte forgery; the summary is intact."""
    got = _audit(_project(tmp_path / "tampered", tamper=True))
    assert got["summary"]["tool_authentic"] is False, (
        f"the gate called the evidence authentic while the only tool-written "
        f"report present was the line 'TAMPERED BY THE ADVERSARY'. The "
        f"document that vouched for it is the runner's own summary OF it:"
        f"\n{json.dumps(got, indent=2)}")
    assert got["rc"] == 1, (
        f"a sign-off gate passed with its tool evidence destroyed. A1 is the "
        f"CONTROL attack — a gate needs its evidence to pass, and one that does "
        f"not is not gating on evidence at all:\n{json.dumps(got, indent=2)}")


def test_the_gate_does_not_pass_while_carrying_ERROR_findings(tmp_path):
    """The invariant the finding violated, stated directly.

    An AuditResult carrying `severity: ERROR` and `passed: true` has recorded a
    defect and acted on nothing. That combination is what made this finding
    invisible: the gate published its own two ERRORs and exited 0.
    """
    got = _audit(_project(tmp_path / "inv", tamper=True))
    errors = [f for f in got["findings"] if f["severity"] == "ERROR"]
    assert errors, "the tampered arm produced no ERROR finding at all"
    assert got["passed"] is False, (
        f"passed=true beside {len(errors)} ERROR finding(s): "
        f"{[f['rule'] for f in errors]}")


def test_a_runner_summary_is_not_judged_as_a_tool_report_either(tmp_path):
    """Both directions. The json must not be FAILED for lacking what it never
    claimed to be, or the rule would just move the false verdict."""
    root = _project(tmp_path / "both", tamper=False)
    files = E._discover(root, ["*ir*.rpt", "*power_grid*", "*IR*.rpt",
                               "*ir_drop*", "*voltage_drop*"])
    assert any(f.suffix == ".json" for f in files), (
        "the fixture no longer discovers the runner json, so this test is not "
        "measuring what it says")
    got = _audit(root)
    named = [f["file"] for f in got["findings"]]
    assert not any(n.endswith("ir_drop.json") for n in named), (
        f"the runner summary was judged as if it were the tool's report: {named}")
