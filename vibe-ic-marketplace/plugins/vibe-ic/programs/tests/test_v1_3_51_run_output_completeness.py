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


# ══════════════════════════════════════════════════════════════════════════════
# DELIVERABLE_SELF_DECLARED_INTERIM — "length is not doneness".
#
# MEASURED ESCAPE (sha256 x sky130A, round E, 2026-08-01). The runner was killed
# 9 minutes in by a 10-minute harness Bash timeout ("Exit code 143 / Command
# timed out after 10m 0s"); Phase 3 never started and the LEC produced neither
# reports/lec.rpt nor reports/lec.json. The agent had honestly written a
# RESULT.md stamped "INTERIM" carrying four PENDING numbers. This gate returned
#
#     [PASS] COMPLETE - deliverable RESULT.md present (14023 B, 148 content lines)
#
# rc 0, because _is_all_placeholder requires EVERY content line to be a
# placeholder, so the verdict reduced to "RESULT.md is >= 400 B". The gate that
# exists to catch the launch-and-idle abandon bug was cleared by the abandoned
# run's own interim file.
# ══════════════════════════════════════════════════════════════════════════════

# The escape verbatim in shape: an INTERIM banner + a PENDING headline score,
# inside an otherwise large, real, many-section report.
_INTERIM_RESULT = """# RESULT - demo x somepdk (run `e1`)

> WARNING **INTERIM - the flow run was still executing when this file was first written.**
> Sections 1 and 3 carry the round's *tooling* results, which are complete and verified.
> The run's own PASS/FAIL numbers are marked **PENDING** and are filled in from the run's
> own artefacts when it finishes.

## 1. Headline - score, denominator, what was measured

**Score: PENDING - filled from `e1`'s own artefacts on completion.**

The denominator is the 44-step canonical-flow compliance audit plus the 9-corner
STA setup and hold sign-off on the routed netlist.

## 3. Score trajectory

| design / tooling | setup WNS | setup TNS |
|---|---|---|
| prior round | +3.33 ns | 0.00 |
| **this run** | **PENDING** | **PENDING** |

## 5. Tool substitution

No commercial or licensed EDA tool was used or required anywhere in this run.

## 6. Reproduce

python3 programs/flow_compliance_check.py e1 --strict
"""


def test_interim_banner_is_detected_at_its_line():
    hits = R.find_interim_banner(_INTERIM_RESULT)
    assert [(w) for _, w, _ in hits] == ["INTERIM"]
    assert hits[0][0] == 3                      # 1-based line of the banner


def test_placeholder_headline_slot_is_detected():
    hp = R.find_placeholder_headline(_INTERIM_RESULT)
    assert hp is not None
    _line, label, value = hp
    assert label == "Score" and value == "PENDING"


def test_unfilled_slots_are_enumerated_for_the_operator():
    slots = R.find_unfilled_slots(_INTERIM_RESULT)
    assert {s[1] for s in slots} == {"PENDING"}
    assert len(slots) >= 2                      # banner line + trajectory row


def test_self_declared_interim_fails_the_gate(tmp_path):
    """THE ESCAPE. Pre-fix this returned COMPLETE / rc 0."""
    (tmp_path / "RESULT.md").write_text(_INTERIM_RESULT)
    _mk_final_summary(tmp_path)
    rep = R.check(tmp_path)
    assert rep.state == "DELIVERABLE_SELF_DECLARED_INTERIM"
    assert rep.verdict == "FAIL" and rep.rc == 1
    # the deliverable is NOT a stub — that is the whole point: every prior
    # signal reads green and the document still says it is unfinished.
    assert rep.evidence["deliverable_complete"] is True
    assert rep.evidence["deliverable_all_placeholder"] is False
    assert rep.evidence["deliverable_bytes"] > R._MIN_REAL_BYTES


def test_interim_with_a_live_runner_is_in_progress_not_fail(tmp_path):
    """An interim snapshot written WHILE the runner is still going is honest.
    It is still not COMPLETE (rc 3 != 0), so an "only exit 0 counts" caller
    refuses to sign it off — but it is not a failure either."""
    (tmp_path / "RESULT.md").write_text(_INTERIM_RESULT)
    _mk_final_summary(tmp_path)
    (tmp_path / ".runner.lock").write_text(
        json.dumps({"pid": os.getpid(), "runner": "t"}))
    rep = R.check(tmp_path)
    assert rep.state == "RUN_STILL_IN_PROGRESS"
    assert rep.verdict == "IN_PROGRESS" and rep.rc == 3


def test_banner_alone_fails_even_with_every_number_filled(tmp_path):
    """Deleting the PENDINGs but leaving the banner does not clear the gate."""
    body = _INTERIM_RESULT.replace("**PENDING**", "**+3.33 ns**").replace(
        "**Score: PENDING - filled from `e1`'s own artefacts on completion.**",
        "**Score: 41/44 steps PASS.**")
    assert "PENDING" not in body
    (tmp_path / "RESULT.md").write_text(body)
    _mk_final_summary(tmp_path)
    rep = R.check(tmp_path)
    assert rep.state == "DELIVERABLE_SELF_DECLARED_INTERIM"
    assert rep.evidence["headline_placeholder"] is None    # S2 clean, S1 fires


def test_placeholder_headline_alone_fails_without_a_banner(tmp_path):
    """And deleting the banner but leaving the headline PENDING does not
    clear it either — the two signals are independent."""
    body = "\n".join(ln for ln in _INTERIM_RESULT.splitlines()
                     if not ln.lstrip().startswith(">"))
    assert "INTERIM" not in body
    (tmp_path / "RESULT.md").write_text(body)
    _mk_final_summary(tmp_path)
    rep = R.check(tmp_path)
    assert rep.state == "DELIVERABLE_SELF_DECLARED_INTERIM"
    assert rep.evidence["interim_banner"] == []            # S1 clean, S2 fires


def test_a_finished_report_still_passes(tmp_path):
    """DEFECT-DIRECTION control: the ordinary complete deliverable used by every
    other test in this file must be unaffected."""
    (tmp_path / "RESULT.md").write_text(_REAL_RESULT)
    _mk_final_summary(tmp_path)
    rep = R.check(tmp_path)
    assert rep.state == "COMPLETE" and rep.rc == 0
    assert rep.evidence["self_declared_interim"] is False


def test_prose_mentioning_the_words_is_not_a_self_declaration(tmp_path):
    """NARROWNESS control. Lowercase prose, a quoted tool banner inside a fence,
    and the word 'pending' used as an ordinary English preposition are all NOT
    self-declarations. Without this the rule would fire on real reports."""
    body = _REAL_RESULT + """
## Notes
This supersedes the interim numbers circulated earlier; an earlier draft of the
spec used a different period. Deferred = 1 pending foundry sign-off.
The DRC deck reports results pending review by the foundry.

```
> **INTERIM** - quoted banner from the tool we are describing
Score: PENDING
```
"""
    (tmp_path / "RESULT.md").write_text(body)
    _mk_final_summary(tmp_path)
    rep = R.check(tmp_path)
    assert rep.state == "COMPLETE" and rep.rc == 0
    assert rep.evidence["interim_banner"] == []
    assert rep.evidence["headline_placeholder"] is None


def test_an_honest_final_report_may_mark_an_unreachable_row_pending(tmp_path):
    """THE FALSE-POSITIVE THAT MUST NOT HAPPEN — measured on the live corpus.

    benchmark-data/ic/opentitan_aes/clean_run_v1432int_commercial/RESULT.md is a
    FINAL report whose headline is fully written ("Sign-off verdict: PnR
    incomplete; no tapeout claim") and which marks 2 of 6 pillar rows PENDING
    with the reason stated. That is honest reporting of an unreachable
    measurement, not an unfinished document. It must PASS; the unfilled slots
    are reported as ADVISORY evidence only.
    """
    body = _REAL_RESULT + """
## Six-pillar summary
| # | Pillar | Verdict | Note |
|---|---|---|---|
| 1 | Functional verification | **PASS** | KAT PASS. |
| 2 | 56-step output comparison | **PENDING** | needs GDS/LVS; routing did not converge. |
| 6 | Design-for-ECO spare cells | **PENDING** | needs routed DEF; routing did not converge. |
"""
    (tmp_path / "RESULT.md").write_text(body)
    _mk_final_summary(tmp_path)
    rep = R.check(tmp_path)
    assert rep.state == "COMPLETE" and rep.rc == 0
    assert rep.evidence["self_declared_interim"] is False
    # ... but the operator is still TOLD which slots are unfilled.
    assert len(rep.evidence["unfilled_slots"]) == 2


def test_cli_self_declared_interim_exit_1(tmp_path, capsys):
    (tmp_path / "RESULT.md").write_text(_INTERIM_RESULT)
    _mk_final_summary(tmp_path)
    rc = R.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "DELIVERABLE_SELF_DECLARED_INTERIM" in out
    assert "Length is not doneness" in out
    assert "self-declared INTERIM" in out       # names the line for the operator


def test_selfdeclared_interim_corpus_sweep():
    """ZERO FALSE POSITIVES on every published RESULT.md in this repo.

    This is the calibration that keeps the two GATING signals narrow. If a new
    checked-in deliverable trips it, that is either a real unfinished report
    (fix the report) or the rule is too wide (narrow the rule) — never a reason
    to weaken the assertion.
    """
    root = _repo_root()
    bench = root / "benchmark-data"
    if not bench.is_dir():
        pytest.skip("benchmark-data not present in this checkout")
    result_files = sorted(bench.rglob("RESULT.md"))
    if not result_files:
        pytest.skip("no RESULT.md files found")
    flagged = []
    for f in result_files:
        a = R.assess_self_declared_interim(f)
        if a["self_declared_interim"]:
            flagged.append((str(f.relative_to(root)), a["banner"],
                            a["headline_placeholder"]))
    assert not flagged, (
        "published RESULT.md flagged as self-declared-INTERIM: " + repr(flagged))
