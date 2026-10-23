#!/usr/bin/env python3
"""FX_P2 (3c, second half) — the phase-2 final audit judges THIS run's record,
not the previous run's.

MEASURED on subservient (8HD-4, 2026-09-28, the proof command on a fresh copy
of an earlier run's tree): final_audit FAILed `project_outputs_in_tree_check`
on "2 blocking external-storage reference(s) (0 live, 2 dangling)" in
`reports/orchestrator/phase2_one_shot.json`. Both were
`/tmp/vibeic-rtl-step-*/sub` -- a stage path cut mid-token -- in the EARLIER
run's record: the runner wrote its own record only after the audit. The new
record (written 25 s after the audit) carried none, and the same gate passed on
the finished tree. The audit judged a document this run was about to replace.

Driven through the real publisher and the real gate.
chip-AGNOSTIC: synthetic project.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as DOSR  # noqa: E402

GATE = PROGRAMS / "project_outputs_in_tree_check.py"


def _stale_tree(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    rec = proj / "reports" / "orchestrator" / "phase2_one_shot.json"
    rec.parent.mkdir(parents=True)
    rec.write_text(json.dumps({"steps": [{
        "name": "rtl_gen", "status": "PASS_WITH_WAIVERS",
        "waiver_rows": [{"id": "rtl_gen", "reason":
                         "READ THE SKILL AT: `/tmp/vibeic-rtl-step-zz9/sub"}]}]}))
    return proj


def _gate(proj: Path) -> int:
    return subprocess.run([sys.executable, str(GATE), str(proj)],
                          capture_output=True, text=True, timeout=120).returncode


def test_the_previous_runs_record_is_what_the_gate_refuses(tmp_path):
    """The control: the earlier record really does fail the gate."""
    assert _gate(_stale_tree(tmp_path)) == 1


def test_publishing_this_run_before_the_audit_replaces_it(tmp_path):
    proj = _stale_tree(tmp_path)
    plan = [DOSR.StepResult("detect_ic_class", "PASS", 0.0, "processor_cpu")]
    publish = getattr(DOSR, "_publish_record_before_audit", None)
    assert publish is not None, "no pre-audit publication of this run's record"
    out = publish(proj, plan, "processor_cpu", {})
    doc = json.loads(out.read_text())
    assert doc["final_audit_pending"] is True
    assert [s["name"] for s in doc["steps"]] == ["detect_ic_class"]
    assert _gate(proj) == 0


def test_main_publishes_before_it_audits():
    """Order, read from the source: the publication precedes the audit call in
    the ONE place main() dispatches the final audit."""
    src = Path(DOSR.__file__).read_text()
    tree = ast.parse(src)
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [(n.lineno, n.func.id) for n in ast.walk(main)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id in ("_publish_record_before_audit",
                               "_audit_after_declared_producers")]
    names = [c[1] for c in sorted(calls)]
    # The first publication feeds complete Phase-2 consumers.  The second is
    # the fresh, immediately-adjacent publication that the final audit judges.
    assert names == ["_publish_record_before_audit",
                     "_publish_record_before_audit",
                     "_audit_after_declared_producers"], names
