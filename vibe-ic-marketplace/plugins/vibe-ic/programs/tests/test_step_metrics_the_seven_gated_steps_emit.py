"""Steps 10, 21, 23, 24, 25, 37 and 37.3 EMIT through `step_metrics` on the
call shapes a REAL run uses (M, #2550; M2).

#2550 wired each program to `step_metrics.emit_gate_outcome` and attributed the
row by matching the LITERAL clause argv. The pre-landing review measured that
mostly ineffective on a real run:
  (1) the phase-3 runner passes an ABSOLUTE `--json`, and flow_compliance_check
      redirects `--json` to /tmp/gate_receipt_* when the target exists, so
      steps 23 and 25 never emitted and 10/21/37 only on a first run -- and
      then kept that first run's row beside a refreshed `__flow__invocation`;
  (2) an out-of-flow hand run could write into a project's metrics;
  (3) the unattributable run printed a stderr line that pushed the DRC PASS
      denominator out of the 400-char tail 37.5ic's evidence quotes;
  (4) `coverage()` did not count `emit_gate_outcome`.
M2: the CALLER states the step (`VIBEIC_GATE_STEP`) -- flow_compliance_check
for the step it is judging, the runner resolved once from the canonical
clause -- every row carries the invocation, a hand run (no step) or an
inherited id (a step whose gate does not run this program) is silent, and the
census counts the call.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import step_metrics as SM                        # noqa: E402

_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_STEPS = ("10", "21", "23", "24", "25", "37", "37.3")


def _clauses():
    """(step, program, argv) for each of the seven steps' gate clauses that
    run one of the step's declared programs -- read from the yaml, not typed."""
    doc = yaml.safe_load(_FLOW.read_text())
    out = []
    for s in doc["steps"]:
        sid = str(s["id"])
        if sid not in _STEPS:
            continue
        progs = set(s.get("programs") or [])
        for clause in SM._gate_strings(s.get("gate")):
            try:
                toks = shlex.split(clause)
            except ValueError:
                continue          # prose-shaped clause text, not a command
            if toks and Path(toks[0]).stem in progs:
                out.append((sid, Path(toks[0]).stem, toks[1:]))
    return out




def test_every_one_of_the_seven_has_a_clause_this_test_can_read():
    assert {c[0] for c in _clauses()} == set(_STEPS), _clauses()


@pytest.mark.parametrize("step,program,argv", _clauses())
def test_each_clause_is_attributed_to_its_own_step(step, program, argv):
    got, why = SM.step_for_invocation(program, argv)
    assert got == step, (program, argv, why)


def test_the_census_counts_emit_gate_outcome():
    """(4): all seven are EMITTING in `coverage()`, which is what
    `test_step_metrics_coverage` pins against `EMITTING_STEPS`."""
    from flow_compliance_check import _find_flow_def
    rep = SM.coverage(_find_flow_def(), _PROGRAMS)
    assert set(_STEPS) <= set(rep["emitting"]), rep["emitting"]


# ── the real call shapes ────────────────────────────────────────────────────

_STA_BODY = (
    "OpenSTA 2.4.0 report_checks\n"
    "Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)\n"
    "Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)\n"
    "Path Type: max\nWNS = 0.15 ns\nTNS = 0.0 ns\n"
    "slack (MET)\nsetup check: PASS\nhold check: PASS\n"
    "data arrival time: 2.34 ns\n" + "# " + ("=" * 78 + "\n") * 40)


def _sta_project(tmp: Path) -> Path:
    sta = tmp / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "post_route_timing.rpt").write_text(_STA_BODY)
    return tmp


def _run(program, argv, cwd, env_extra):
    env = {k: v for k, v in os.environ.items()
           if k not in (SM.GATE_STEP_ENV, SM.INVOCATION_ENV)}
    env.update(env_extra)
    return subprocess.run([sys.executable, str(_PROGRAMS / f"{program}.py"),
                           *argv], cwd=cwd, capture_output=True, text=True,
                          env=env)


def _row(proj: Path, sid: str) -> dict:
    return json.loads((proj / "reports" / "metrics"
                       / f"{SM.normalize_step(sid)}.json").read_text())


def test_the_runners_absolute_json_shape_emits_under_23(tmp_path):
    """(1) runner shape: absolute project + absolute --json, step resolved by
    `phase3_one_shot_runner._signoff_gate_env` from the canonical clause."""
    import phase3_one_shot_runner as R
    proj = _sta_project(tmp_path)
    rel = "reports/phase3/sta/post_route_summary.json"
    env = R._signoff_gate_env(
        "sta_report_check.py",
        ("--mode", "sta", "--under", "phase3/stage3/sta/post_route_timing.rpt"),
        rel)
    assert env[SM.GATE_STEP_ENV] == "23"
    r = _run("sta_report_check", [str(proj), "--mode", "sta", "--under",
                                  "phase3/stage3/sta/post_route_timing.rpt",
                                  "--json", str(proj / rel)],
             cwd="/", env_extra={SM.GATE_STEP_ENV: env[SM.GATE_STEP_ENV],
                                 SM.INVOCATION_ENV: "inv-runner"})
    row = _row(proj, "23")
    assert row["23__gate__rc"] == r.returncode, row
    assert row["23__gate__invocation"] == "inv-runner", row
    assert row["23__gate__program"] == "sta_report_check", row


def test_the_audits_redirected_receipt_shape_emits_under_25(tmp_path):
    """(1) audit shape: --json redirected OUTSIDE the project (the receipt
    redirect), step stated by the audit that is judging step 25."""
    proj = tmp_path / "p"
    proj.mkdir()
    receipt = tmp_path / "gate_receipt_x" / "em_signoff.json"
    receipt.parent.mkdir()
    r = _run("em_report_check", [".", "--mode", "em", "--json", str(receipt)],
             cwd=proj, env_extra={SM.GATE_STEP_ENV: "25",
                                  SM.INVOCATION_ENV: "inv-audit"})
    row = _row(proj, "25")
    assert row["25__gate__rc"] == r.returncode, row
    assert row["25__gate__invocation"] == "inv-audit", row


def test_a_second_run_refreshes_the_row_and_its_invocation(tmp_path):
    """(1) the first-run-only row: run 2 (target already exists) must replace
    run 1's gate row, and the invocation says which run wrote it."""
    proj = _sta_project(tmp_path)
    argv = next(a for s, p, a in _clauses() if s == "23")
    _run("sta_report_check", argv, proj,
         {SM.GATE_STEP_ENV: "23", SM.INVOCATION_ENV: "inv-1"})
    assert _row(proj, "23")["23__gate__invocation"] == "inv-1"
    (proj / "phase3/stage3/sta/post_route_timing.rpt").write_text(
        _STA_BODY.replace("slack (MET)", "slack (VIOLATED)").replace(
            "WNS = 0.15 ns", "WNS = -0.40 ns"))
    r2 = _run("sta_report_check", argv, proj,
              {SM.GATE_STEP_ENV: "23", SM.INVOCATION_ENV: "inv-2"})
    row = _row(proj, "23")
    assert row["23__gate__invocation"] == "inv-2", row
    assert row["23__gate__rc"] == r2.returncode == 1, row


def test_a_hand_run_writes_no_metrics_and_says_nothing(tmp_path):
    """(2)+(3): no step stated -> no project metrics, and the gate's own
    stderr is untouched (no `[step_metrics]` line to push an evidence tail)."""
    proj = _sta_project(tmp_path)
    argv = next(a for s, p, a in _clauses() if s == "23")
    r = _run("sta_report_check", argv, proj, {})
    assert not (proj / "reports" / "metrics").exists()
    assert "[step_metrics]" not in r.stderr, r.stderr[-800:]


def test_an_inherited_step_id_does_not_attribute_a_grandchild(tmp_path):
    """Step 37.5ic's gate is tapeout_precheck; a drc_report_check it spawns
    inherits VIBEIC_GATE_STEP=37.5ic and must NOT emit under it."""
    r = _run("drc_report_check", [".", "--json", "reports/x.json"], tmp_path,
             {SM.GATE_STEP_ENV: "37.5ic", SM.INVOCATION_ENV: "inv"})
    assert not (tmp_path / "reports" / "metrics").exists()
    assert "[step_metrics]" not in r.stderr, r.stderr[-800:]


def test_the_emit_never_changes_the_gates_rc(tmp_path):
    proj = _sta_project(tmp_path)
    argv = next(a for s, p, a in _clauses() if s == "23")
    env = {SM.GATE_STEP_ENV: "23", SM.INVOCATION_ENV: "inv"}
    r1 = _run("sta_report_check", argv, proj, env)
    (proj / "reports" / "metrics" / "23.json").unlink()
    (proj / "reports" / "metrics" / "23.json").mkdir()   # blocks the write
    r2 = _run("sta_report_check", argv, proj, env)
    assert r1.returncode == r2.returncode
    assert "EMIT FAILED" in r2.stderr, r2.stderr[-1500:]


def test_the_audit_hands_the_judged_step_to_its_gate(tmp_path):
    """flow_compliance_check's spawn environment carries the step it is
    judging, and "" outside a step (so an outer id cannot leak in)."""
    import flow_compliance_check as F
    assert F._child_env()[SM.GATE_STEP_ENV] == ""
    seen = {}

    @F._with_child_gate_step
    def _judge(project, step, *_a, **_k):
        seen["env"] = F._child_env()[SM.GATE_STEP_ENV]
        return "judged"
    assert _judge(tmp_path, {"id": "37.3"}, {}) == "judged"
    assert seen["env"] == "37.3"
    # and it is check_step that carries it
    assert F.check_step.__wrapped__ is not None
    assert F._child_env()[SM.GATE_STEP_ENV] == ""


# ── M2 r2 (dispatcher's read) ─────────────────────────────────────────────

def test_two_steps_judged_concurrently_each_hand_their_own_step(tmp_path):
    """(1) Since #2548 check_step runs in a thread pool. Two steps judged at the
    same time, forced to interleave (each sets its step, then both wait at a
    barrier, then each spawns): each gate environment carries ITS OWN step. A
    module global made both read whichever step was set last."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import flow_compliance_check as F
    barrier = threading.Barrier(2)

    @F._with_child_gate_step
    def _judge(project, step, *_a, **_k):
        barrier.wait(timeout=30)          # both steps are now "being judged"
        return F._child_env()[SM.GATE_STEP_ENV]
    with ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(_judge, tmp_path, {"id": "23"}, {})
        fb = ex.submit(_judge, tmp_path, {"id": "25"}, {})
        assert (fa.result(), fb.result()) == ("23", "25")
    assert F._child_env()[SM.GATE_STEP_ENV] == ""


def test_a_failing_attribution_never_changes_a_signoff_gates_verdict(
        tmp_path, monkeypatch):
    """(2) step_for_invocation raising must not turn a sign-off gate into
    NOT CHECKED: the gate runs with the plain environment, its verdict is the
    one it gives when attribution works, and it writes no metrics row."""
    import phase3_one_shot_runner as R
    args = ("sta_signoff", "sta_report_check.py",
            "reports/phase3/sta/post_route_summary.json",
            ("--mode", "sta", "--under",
             "phase3/stage3/sta/post_route_timing.rpt"))
    ok = _sta_project(tmp_path / "ok")
    for k in (SM.GATE_STEP_ENV, SM.INVOCATION_ENV):
        monkeypatch.delenv(k, raising=False)
    base = R._run_declared_signoff_gate(ok, *args)
    assert base.status == "PASS", base
    assert (ok / "reports/metrics/23.json").is_file()

    def _boom(*_a, **_k):
        raise RuntimeError("attribution exploded")
    monkeypatch.setattr(SM, "step_for_invocation", _boom)
    bad = _sta_project(tmp_path / "bad")
    got = R._run_declared_signoff_gate(bad, *args)
    assert got.status == base.status, got
    assert not (bad / "reports" / "metrics").exists()
