"""v1.3.51 — run_output_completeness_check: the EMPTY / MISSING / STUB
deliverable gate.

The gate keys off the DELIVERABLE (RESULT.md) rather than the runner's own
outputs, so it catches the launch-and-idle abandon bug: a run whose compute
finished (final_summary / orchestrator verdict / GDS present) but whose
RESULT.md was never written. It classifies every incomplete case into one of a
small taxonomy so "find the problem" is automatic, and it must NOT false-positive
on a legitimately in-progress run (a live process/lock).

Cases covered (the load-bearing one is COMPUTE_DONE_DELIVERABLE_MISSING):
  * empty RESULT                                   → FAIL + DELIVERABLE_STUB
  * MISSING RESULT + final_summary + GDS present   → FAIL + COMPUTE_DONE_DELIVERABLE_MISSING
  * live process/lock present                      → RUN_STILL_IN_PROGRESS (non-fail)
  * complete RESULT + artifacts                    → PASS + COMPLETE
  * no-summary-no-artifacts                        → FAIL + RUN_DIED_EARLY
  * complete RESULT but a required artifact missing → FAIL + DECLARED_ARTIFACT_MISSING
  * corpus sweep: every genuinely-complete benchmark-data RESULT.md PASSes.
"""
import json
import os
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import run_output_completeness_check as R  # noqa: E402
import gatekeeper_review as GK  # noqa: E402


# A realistic, non-stub RESULT.md body well above the content floors.
_REAL_RESULT = """# demo — clean-run spec->GDSII (plugin v1.3.51)
Blind clean-room design driven end to end through the runner chain.
## Result: functional + physical PASS
| Pillar | Result |
|---|---|
| functional (self-test) | PASS |
| yosys synth | PASS (6264 cells) |
| PnR (OpenROAD) | PASS (126 spares) |
| GDS streamout | PASS — demo.gds 76 MB |
| DRC | 0 violations |
| LVS | circuits match uniquely |
## Timing finding
The single-cycle datapath computes the full ALU combinationally in one clock.
Closure needs pipelining the execute stage. Functional correctness unaffected.
## Tool substitution
VCS->iverilog 12; DC->yosys; PnR/DRC/LVS/STA->OpenROAD/klayout/netgen.
## Reproduce
python3 scorer.py --design demo --dataset ./dataset
"""


def _mk_final_summary(run_dir: Path, text: str = "# final summary\nverdict: PASS\nall phases green.\n"):
    d = run_dir / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / "final_summary.md").write_text(text)


def _mk_orch_verdict(run_dir: Path, verdict: str = "PASS"):
    d = run_dir / "reports" / "orchestrator"
    d.mkdir(parents=True, exist_ok=True)
    (d / "vibe_ic_one_shot.json").write_text(
        json.dumps({"phase": "vibe-ic", "verdict": verdict}) + "\n")


def _mk_gds(run_dir: Path, name="demo.gds", size=2048):
    p = run_dir / "phase3" / "stage3" / "gds"
    p.mkdir(parents=True, exist_ok=True)
    (p / name).write_bytes(b"G" * size)


# ── (1) empty RESULT → FAIL + DELIVERABLE_STUB ───────────────────────────────
def test_empty_result_is_deliverable_stub(tmp_path):
    (tmp_path / "RESULT.md").write_text("")   # zero-byte file that EXISTS
    _mk_final_summary(tmp_path)
    rep = R.check(tmp_path)
    assert rep.state == "DELIVERABLE_STUB"
    assert rep.verdict == "FAIL"
    assert rep.is_fail and rep.rc == 1
    assert rep.highlight and "DELIVERABLE_STUB" in rep.highlight
    assert rep.capture_candidate["failure_mode"] == "DELIVERABLE_STUB"


def test_header_only_result_is_stub(tmp_path):
    (tmp_path / "RESULT.md").write_text("# Title only\n\n## Section\n")
    rep = R.check(tmp_path)
    assert rep.state == "DELIVERABLE_STUB"
    assert rep.verdict == "FAIL"


def test_all_placeholder_result_is_stub(tmp_path):
    # ≥3 content lines but every one is a placeholder token, and padded past the
    # byte floor so the stub is caught by the placeholder rule specifically.
    body = "# R\n" + ("TODO\nTBD\nplaceholder\n<fill in>\n" * 20)
    (tmp_path / "RESULT.md").write_text(body)
    rep = R.check(tmp_path)
    assert rep.evidence["deliverable_bytes"] >= R._MIN_REAL_BYTES
    assert rep.evidence["deliverable_all_placeholder"] is True
    assert rep.state == "DELIVERABLE_STUB"


# ── (2) MISSING RESULT + final_summary + GDS → COMPUTE_DONE_DELIVERABLE_MISSING ─
def test_missing_result_with_compute_done_is_the_idle_abandon_bug(tmp_path):
    # No RESULT.md at all, but the runner's compute finished.
    _mk_final_summary(tmp_path)
    _mk_gds(tmp_path)
    rep = R.check(tmp_path, require_artifacts=["gds"])
    assert rep.state == "COMPUTE_DONE_DELIVERABLE_MISSING"
    assert rep.verdict == "FAIL"
    assert rep.rc == 1
    # the highlight must name the idle-abandon bug loudly
    assert "COMPUTE_DONE_DELIVERABLE_MISSING" in rep.highlight
    assert "abandon" in rep.reason.lower() or "idle" in rep.reason.lower()
    # capture candidate is emitted and is enhancement_emit-ingestible (Bucket C)
    cc = rep.capture_candidate
    assert cc["bucket"] == "C"
    assert cc["why_not_bucket_a"]
    assert cc["component"] == "orchestration/deliverable-completeness"
    assert cc["failure_mode"] == "COMPUTE_DONE_DELIVERABLE_MISSING"


def test_missing_result_with_only_orchestrator_verdict_is_compute_done(tmp_path):
    _mk_orch_verdict(tmp_path, "PASS")
    rep = R.check(tmp_path)
    assert rep.state == "COMPUTE_DONE_DELIVERABLE_MISSING"
    assert rep.evidence["orchestrator_verdict"] == "PASS"


def test_claimed_pass_but_missing_result_flags_inconsistency(tmp_path):
    _mk_final_summary(tmp_path)
    rep = R.check(tmp_path, claimed_verdict="PASS")
    assert rep.state == "COMPUTE_DONE_DELIVERABLE_MISSING"
    assert any("INCONSISTENCY" in b for b in rep.blocking)


# ── (3) live process/lock → RUN_STILL_IN_PROGRESS (non-fail) ──────────────────
def test_live_pid_is_in_progress_not_fail(tmp_path):
    # deliverable not written yet, but the runner (this very process) is alive
    _mk_final_summary(tmp_path)
    rep = R.check(tmp_path, pid=os.getpid())
    assert rep.state == "RUN_STILL_IN_PROGRESS"
    assert rep.verdict == "IN_PROGRESS"
    assert not rep.is_fail
    assert rep.rc == 3                     # distinct non-fail exit code
    assert rep.capture_candidate is None   # no capture on a non-fail


def test_live_lock_is_in_progress(tmp_path):
    (tmp_path / ".runner.lock").write_text(
        json.dumps({"pid": os.getpid(), "runner": "test", "ts": "now"}))
    rep = R.check(tmp_path)
    assert rep.state == "RUN_STILL_IN_PROGRESS"
    assert rep.evidence["liveness"]["lock_live"] is True


def test_stale_lock_dead_pid_does_not_mask_abandoned_run(tmp_path):
    # A lock left by a DEAD runner must NOT read as in-progress (the false-
    # negative the owner directive forbids). pid 2**31-1 is not a live process.
    _mk_final_summary(tmp_path)
    (tmp_path / ".runner.lock").write_text(
        json.dumps({"pid": 2**31 - 1, "runner": "dead", "ts": "old"}))
    rep = R.check(tmp_path)
    assert rep.evidence["liveness"]["live"] is False
    assert rep.state == "COMPUTE_DONE_DELIVERABLE_MISSING"
    assert rep.is_fail


# ── Step-2.7 adversarial: no false-positive on in-progress, no false-negative ─
def test_live_process_with_partial_stub_is_in_progress_not_fail(tmp_path):
    # a run still writing (live pid) with a partial stub RESULT must NOT FAIL —
    # liveness is judged BEFORE the stub classification.
    (tmp_path / "RESULT.md").write_text("# partial\nstill writing...\n")
    rep = R.check(tmp_path, pid=os.getpid())
    assert rep.state == "RUN_STILL_IN_PROGRESS"
    assert not rep.is_fail


def test_empty_result_with_dead_pidfile_still_fails(tmp_path):
    # a dead-pid run.pid must NOT mask an empty deliverable (no false-negative).
    (tmp_path / "RESULT.md").write_text("")
    (tmp_path / "run.pid").write_text("2147483646")   # not a live pid
    _mk_final_summary(tmp_path)
    rep = R.check(tmp_path)
    assert rep.evidence["liveness"]["live"] is False
    assert rep.state == "DELIVERABLE_STUB" and rep.is_fail


def test_whitespace_above_byte_floor_is_stub(tmp_path):
    # the byte floor alone cannot be gamed with whitespace — content_lines catch.
    (tmp_path / "RESULT.md").write_text("\n" * 401)
    rep = R.check(tmp_path)
    assert rep.evidence["deliverable_bytes"] > R._MIN_REAL_BYTES
    assert rep.evidence["deliverable_content_lines"] == 0
    assert rep.state == "DELIVERABLE_STUB"


# ── (4) complete RESULT + artifacts → PASS + COMPLETE ────────────────────────
def test_complete_result_with_artifacts_passes(tmp_path):
    (tmp_path / "RESULT.md").write_text(_REAL_RESULT)
    _mk_final_summary(tmp_path)
    _mk_gds(tmp_path)
    rep = R.check(tmp_path, require_artifacts=["gds"])
    assert rep.state == "COMPLETE"
    assert rep.verdict == "PASS"
    assert rep.rc == 0
    assert not rep.is_fail
    assert rep.capture_candidate is None


def test_complete_result_wins_over_live_process(tmp_path):
    # once COMPLETE, a lingering live process does not downgrade to in-progress
    (tmp_path / "RESULT.md").write_text(_REAL_RESULT)
    rep = R.check(tmp_path, pid=os.getpid())
    assert rep.state == "COMPLETE"


# ── (5) no summary + no artifacts + no RESULT → RUN_DIED_EARLY ────────────────
def test_no_summary_no_artifacts_is_run_died_early(tmp_path):
    rep = R.check(tmp_path)               # utterly empty run_dir
    assert rep.state == "RUN_DIED_EARLY"
    assert rep.verdict == "FAIL"
    assert rep.evidence["compute_done"] is False


# ── DECLARED_ARTIFACT_MISSING: RESULT complete but a required artifact absent ─
def test_complete_result_missing_required_artifact_fails(tmp_path):
    (tmp_path / "RESULT.md").write_text(_REAL_RESULT)
    _mk_final_summary(tmp_path)
    # require a GDS but never produce one
    rep = R.check(tmp_path, require_artifacts=["gds"])
    assert rep.state == "DECLARED_ARTIFACT_MISSING"
    assert rep.verdict == "FAIL"
    assert "gds" in rep.evidence["missing_artifacts"]


def test_empty_artifact_file_is_not_ok(tmp_path):
    (tmp_path / "RESULT.md").write_text(_REAL_RESULT)
    p = tmp_path / "phase3" / "stage3" / "gds"
    p.mkdir(parents=True, exist_ok=True)
    (p / "demo.gds").write_bytes(b"")     # zero-byte artifact
    rep = R.check(tmp_path, require_artifacts=["gds"])
    assert rep.state == "DECLARED_ARTIFACT_MISSING"


# ── agent-output emptiness ───────────────────────────────────────────────────
def test_empty_agent_output_fails_even_with_complete_result(tmp_path):
    (tmp_path / "RESULT.md").write_text(_REAL_RESULT)
    ao = tmp_path / "agent_return.txt"
    ao.write_text("")
    rep = R.check(tmp_path, agent_output=ao)
    assert rep.state == "DECLARED_ARTIFACT_MISSING"
    assert rep.evidence["agent_output_ok"] is False


def test_nonempty_agent_output_ok(tmp_path):
    (tmp_path / "RESULT.md").write_text(_REAL_RESULT)
    ao = tmp_path / "agent_return.txt"
    ao.write_text("Delivered: 243/302 = 80.46%. See RESULT.md.\n")
    rep = R.check(tmp_path, agent_output=ao)
    assert rep.state == "COMPLETE"


# ── CLI exit codes ───────────────────────────────────────────────────────────
def test_cli_pass_exit_0(tmp_path):
    (tmp_path / "RESULT.md").write_text(_REAL_RESULT)
    assert R.main([str(tmp_path)]) == 0


def test_cli_compute_done_missing_exit_1(tmp_path, capsys):
    _mk_final_summary(tmp_path)
    rc = R.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "COMPUTE_DONE_DELIVERABLE_MISSING" in out
    assert "CAPTURE" in out


def test_cli_in_progress_exit_3(tmp_path):
    _mk_final_summary(tmp_path)
    assert R.main([str(tmp_path), "--pid", str(os.getpid())]) == 3


def test_cli_json_written(tmp_path):
    _mk_final_summary(tmp_path)
    out = tmp_path / "out.json"
    R.main([str(tmp_path), "--json", str(out)])
    d = json.loads(out.read_text())
    assert d["state"] == "COMPUTE_DONE_DELIVERABLE_MISSING"
    assert d["capture_candidate"]["failure_mode"] == "COMPUTE_DONE_DELIVERABLE_MISSING"


def test_cli_not_a_directory_exit_2(tmp_path):
    assert R.main([str(tmp_path / "nope")]) == 2


# ── corpus sweep: genuinely-complete benchmark-data RESULT.md files PASS ──────
def _repo_root() -> Path:
    # .../vibe-ic-marketplace/plugins/vibe-ic/programs/tests -> up to repo root
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "benchmark-data").is_dir() and (anc / ".git").exists():
            return anc
    return p.parents[6]


def test_corpus_sweep_complete_result_md_all_pass():
    root = _repo_root()
    bench = root / "benchmark-data"
    if not bench.is_dir():
        pytest.skip("benchmark-data not present in this checkout")
    result_files = sorted(bench.rglob("RESULT.md"))
    if not result_files:
        pytest.skip("no RESULT.md files found")
    # We assert on the DELIVERABLE assessment in isolation (does the file itself
    # read as real content?) — that is the property the sweep must keep clean:
    # every checked-in RESULT.md that people rely on is non-empty / non-stub.
    stubs = []
    for f in result_files:
        a = R._assess_deliverable(f)
        if not a["complete"]:
            stubs.append((str(f.relative_to(root)), a["bytes"], a["content_lines"]))
    assert not stubs, (
        "checked-in RESULT.md file(s) read as EMPTY/STUB (real finding, not a "
        "gate bug — report/fix them): " + repr(stubs))


# ── gatekeeper_review wiring: the run_deliverable_gate ────────────────────────
def test_gk_gate_skips_when_no_result_in_changeset():
    g = GK.run_deliverable_gate(Path("/nonexistent"), ["programs/foo.py"])
    assert g.rc == -1 and g.green            # not applicable = non-blocking


def test_gk_gate_flags_empty_result(tmp_path):
    run = tmp_path / "evaluation" / "somebench"
    run.mkdir(parents=True)
    (run / "RESULT.md").write_text("")       # empty deliverable added by the PR
    _mk_final_summary(run)
    g = GK.run_deliverable_gate(tmp_path, ["evaluation/somebench/RESULT.md"])
    assert g.rc == 1 and not g.green
    assert "DELIVERABLE_STUB" in g.summary or "COMPUTE_DONE" in g.summary


def test_gk_gate_passes_complete_result(tmp_path):
    run = tmp_path / "ic" / "demo"
    run.mkdir(parents=True)
    (run / "RESULT.md").write_text(_REAL_RESULT)
    g = GK.run_deliverable_gate(tmp_path, ["ic/demo/RESULT.md"])
    assert g.rc == 0 and g.green


def test_gk_gate_in_progress_is_non_blocking(tmp_path):
    run = tmp_path / "ic" / "live"
    run.mkdir(parents=True)
    _mk_final_summary(run)                   # no RESULT yet
    (run / ".runner.lock").write_text(
        json.dumps({"pid": os.getpid(), "runner": "t"}))
    g = GK.run_deliverable_gate(tmp_path, ["ic/live/RESULT.md"])
    # RESULT.md path not on disk here → the parent run_dir IS, and it's live.
    # (A live in-progress run must never block the merge.)
    assert g.green


def test_gk_review_includes_run_deliverable_gate(tmp_path):
    # a change-set with an empty RESULT.md makes the whole verdict non-MERGE_OK
    run = tmp_path / "evaluation" / "b"
    run.mkdir(parents=True)
    (run / "RESULT.md").write_text("")
    _mk_final_summary(run)
    v = GK.review(
        "BASE", "HEAD",
        repo=tmp_path,
        plugin_root=PROG.parent,
        role="core-agent",
        override_files=["evaluation/b/RESULT.md"],
        override_cur="1.3.51", override_prev="1.3.50")
    names = [g.name for g in v.gates]
    assert "run_output_completeness_check" in names
    roc_gate = next(g for g in v.gates if g.name == "run_output_completeness_check")
    assert roc_gate.rc == 1
    assert v.verdict != "MERGE_OK"
