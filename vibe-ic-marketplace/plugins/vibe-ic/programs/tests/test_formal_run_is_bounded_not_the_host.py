"""A formal proof gets a CEILING, and hitting it is INCONCLUSIVE — never proved.

WHAT HAPPENED. `formal_property_run.run()` dispatched SymbiYosys with a deadline
and, on the container path only, an address-space ceiling. The AMBIENT path —
the one taken whenever the caller already runs inside the vibeic-eda image,
where `docker` is absent and `sby` is at /usr/local/bin/sby, which is how CI,
`design_one_shot_runner` (it passes `container or None`) and every agent run it
— carried NO memory ceiling and only a CLIENT-side deadline. MEASURED: two
`yosys` reached 35.6 GB apiece on a 125 GB host, 71 GB between them, no log
output for twelve minutes, available memory falling ~2 GB per 20 s. One host
stopped answering ssh and did not come back.

None of that is a defect in yosys. A hard formal proof is entitled to be
expensive. What it is not entitled to is the host, and what the RUNNER owes its
caller is an honest answer when the ceiling is reached:

  * INCONCLUSIVE IS NOT PASS. `all_proved` can never be true for a proof that
    did not finish — recording an unfinished proof as proved is the worst
    outcome available, because it is the only one that makes the flow greener
    than its evidence. `assert_resource_honesty` is the EXECUTED guard, and
    `test_a_bound_stop_can_never_be_recorded_as_proved` is the regression that
    fails if a future change lets one through.
  * INCONCLUSIVE IS NOT FAIL. The properties may well hold; we did not finish.
  * IT NAMES THE RESOURCE. "Inconclusive" with no resource named sends the
    reader to the design when the fix is on the host.
  * A REAL COUNTEREXAMPLE SURVIVES A LATER STOP. A cex is sound evidence the
    moment it is found; laundering a FAIL into "we ran out of time" would lose
    a true finding.
  * AND A PROOF THAT FINISHES INSIDE ITS CEILING STILL GETS A REAL VERDICT. A
    change that cannot tell those apart is a refusal machine, so the accept
    cases below are as load-bearing as the refusals.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
F = importlib.import_module("formal_property_run")

LEAF = """\
`default_nettype none
module leaf_a (input wire clk, input wire rst, output reg q);
    always @(posedge clk) if (rst) q <= 1'b0; else q <= ~q;
endmodule
`default_nettype wire
"""

HARNESS = """\
`default_nettype none
module formal_leaf_a (input wire clk);
    (* anyseq *) wire rst;
    wire q;
    leaf_a dut (.clk(clk), .rst(rst), .q(q));
endmodule
`default_nettype wire
"""

# Transcript shapes, verbatim from the tools. A `.sby` emitted by `emit_sby`
# declares two tasks, `safety` (prove) and `bmc`, tagged `<stem>_<task>`.
_STEM = "formal_leaf_a_formal"
PASSED = (f"[{_STEM}_safety] engine_0: abc pdr\n"
          f"[{_STEM}_safety] DONE (PASS, rc=0)\n"
          f"[{_STEM}_bmc] engine_0: abc bmc3\n"
          f"[{_STEM}_bmc] DONE (PASS, rc=0)\n")
REFUTED = (f"[{_STEM}_safety] engine_0: abc pdr\n"
           f"[{_STEM}_safety] Assert failed in leaf_a: asserted in frame 3\n"
           f"[{_STEM}_safety] DONE (FAIL, rc=1)\n"
           f"[{_STEM}_bmc] engine_0: abc bmc3\n"
           f"[{_STEM}_bmc] DONE (PASS, rc=0)\n")
OUT_OF_MEMORY = (f"[{_STEM}_safety] engine_0: abc pdr\n"
                 f"[{_STEM}_safety] terminate called after throwing an "
                 f"instance of 'std::bad_alloc'\n")
DEADLINE = (f"[{_STEM}_safety] engine_0: abc pdr\n"
            "\n[formal_property_run] SOLVER DEADLINE: the host-side deadline "
            "stopped sby and its whole process group after 30s. The proof is "
            "INCONCLUSIVE — not disproved.\n")


def _stage(tmp_path: Path):
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    formal = proj / "phase2" / "stage1" / "formal"
    rtl.mkdir(parents=True)
    formal.mkdir(parents=True)
    (rtl / "leaf_a.v").write_text(LEAF)
    harness = formal / "formal_leaf_a.sv"
    harness.write_text(HARNESS)
    return proj, harness, [rtl / "leaf_a.v"]


def _run(tmp_path, monkeypatch, transcript, **kw):
    """Drive the SHIPPED `run()` with the solver replaced by a transcript.

    Only the executor is stubbed: the emit, the config parse, the log parse, the
    verdict and every honesty guard are the real ones, so what is under test is
    the program and not a re-typed copy of it.
    """
    proj, harness, rtl = _stage(tmp_path)
    seen = {}

    def _fake_sby(sby_path, formal_dir, container, timeout, mem_limit_kb=None):
        seen["timeout"] = timeout
        seen["mem_limit_kb"] = mem_limit_kb
        return transcript

    monkeypatch.setattr(F, "detect_engines", lambda container: {})
    monkeypatch.setattr(F, "_run_sby", _fake_sby)
    res = F.run(project=proj, harness=harness, rtl=rtl, top="formal_leaf_a",
                container=None, **kw)
    return res, proj, seen


# ── the classifier is pure, and it says WHICH resource ─────────────────────
def test_a_deadline_stop_names_the_wall_clock_and_its_limit():
    stop = F.classify_resource_stop(DEADLINE, timeout_s=30,
                                    mem_limit_kb=8 * 1024 * 1024)
    assert stop["resource"] == "wall_clock"
    assert stop["limit"] == 30 and stop["unit"] == "s"
    assert "did not finish" in stop["meaning"]


def test_a_memory_stop_names_the_address_space_and_its_limit():
    stop = F.classify_resource_stop(OUT_OF_MEMORY, timeout_s=900,
                                    mem_limit_kb=32952508)
    assert stop["resource"] == "memory"
    assert stop["limit"] == 32952508 and stop["unit"] == "KiB"
    assert "bad_alloc" in stop["tool_message"]


@pytest.mark.parametrize("transcript", [PASSED, REFUTED, ""])
def test_a_run_that_reached_an_answer_is_not_called_a_resource_stop(transcript):
    """THE ACCEPT DIRECTION. A classifier that says yes to everything invents
    the condition it looks for; these are the transcripts it must stay silent
    on, including a real counterexample."""
    assert F.classify_resource_stop(transcript, 900, 32952508) is None


# ── the executed honesty guard ─────────────────────────────────────────────
def test_the_honesty_guard_refuses_a_proved_record_under_a_stop():
    stop = {"resource": "memory", "limit": 4, "unit": "KiB"}
    with pytest.raises(AssertionError, match="INCONCLUSIVE, never proved"):
        F.assert_resource_honesty({"verdict": "INCONCLUSIVE",
                                   "all_proved": True}, stop)
    with pytest.raises(AssertionError, match="INCONCLUSIVE, never proved"):
        F.assert_resource_honesty({"verdict": "PASS",
                                   "all_proved": False}, stop)


def test_the_honesty_guard_lets_an_honest_record_through():
    """It must not be a blanket refusal: with no stop, PASS is fine; with a
    stop, an INCONCLUSIVE record is fine."""
    assert F.assert_resource_honesty({"verdict": "PASS",
                                      "all_proved": True}, None) is True
    assert F.assert_resource_honesty(
        {"verdict": "INCONCLUSIVE", "all_proved": False},
        {"resource": "memory", "limit": 4, "unit": "KiB"}) is True


# ── end to end through the shipped run() ───────────────────────────────────
def test_a_proof_that_finishes_inside_the_ceiling_still_gets_a_real_verdict(
        tmp_path, monkeypatch):
    """LOAD-BEARING ACCEPT CASE. A bound that also stops the answer is the gate
    switched off from the other end."""
    res, proj, _ = _run(tmp_path, monkeypatch, PASSED)
    assert res["verdict"] == "PASS"
    assert res["all_proved"] is True
    assert res["rc"] == F.RC_ALL_PROVED == 0
    assert "resource_stop" not in res
    on_disk = json.loads(
        (proj / "phase2" / "stage1" / "formal" / "results.json").read_text())
    assert on_disk["all_proved"] is True


def test_a_refutation_inside_the_ceiling_still_gets_a_real_verdict(
        tmp_path, monkeypatch):
    """The other real verdict. FAIL must remain reachable."""
    res, _proj, _ = _run(tmp_path, monkeypatch, REFUTED)
    assert res["verdict"] == "FAIL"
    assert res["all_proved"] is False
    assert res["rc"] == F.RC_PROPERTY_FAILED


def test_a_memory_stop_is_inconclusive_and_names_what_ran_out(
        tmp_path, monkeypatch):
    res, proj, seen = _run(tmp_path, monkeypatch, OUT_OF_MEMORY,
                           mem_limit_kb=32952508, timeout=900)
    assert res["verdict"] == "INCONCLUSIVE"
    assert res["all_proved"] is False
    assert res["rc"] == F.RC_RESOURCE_INCONCLUSIVE
    stop = res["resource_stop"]
    assert stop["resource"] == "memory"
    assert stop["limit"] == 32952508
    # ... carrying WHAT WAS ATTEMPTED, so the reader can raise the right bound.
    tasks = {a["task"] for a in res["attempted"]}
    assert tasks == {"safety", "bmc"}, res["attempted"]
    assert {a["mode"] for a in res["attempted"]} == {"prove", "bmc"}
    # the ceiling the caller granted is the ceiling that was dispatched
    assert seen["mem_limit_kb"] == 32952508
    on_disk = json.loads(
        (proj / "phase2" / "stage1" / "formal" / "results.json").read_text())
    assert on_disk["all_proved"] is False
    assert on_disk["verdict"] == "INCONCLUSIVE"


def test_a_deadline_stop_is_inconclusive_and_names_the_wall_clock(
        tmp_path, monkeypatch):
    res, _proj, _ = _run(tmp_path, monkeypatch, DEADLINE, timeout=30)
    assert res["verdict"] == "INCONCLUSIVE"
    assert res["all_proved"] is False
    assert res["resource_stop"]["resource"] == "wall_clock"
    assert res["resource_stop"]["limit"] == 30
    assert res["rc"] == F.RC_RESOURCE_INCONCLUSIVE


def test_a_real_counterexample_survives_a_later_resource_stop(
        tmp_path, monkeypatch):
    """A cex is sound the moment it is found. Laundering a FAIL into "we ran
    out of time" would discard a true finding — the harm runs the other way,
    but it is still a lie about the evidence."""
    res, _proj, _ = _run(tmp_path, monkeypatch, REFUTED + DEADLINE, timeout=30)
    assert res["verdict"] == "FAIL"
    assert res["all_proved"] is False
    assert res["resource_stop"]["resource"] == "wall_clock"


def test_a_bound_stop_can_never_be_recorded_as_proved(tmp_path, monkeypatch):
    """THE REGRESSION THAT FAILS IF A FUTURE CHANGE LETS ONE THROUGH.

    `apply_resource_stop` is the function that KEEPS the rule, and it is where a
    future change would land — a renamed verdict, a "PARTIAL reads better here"
    tweak, a refactor that reorders the fields. A rule enforced only by the code
    that could break it is enforced by nothing, so `run()` re-derives it from the
    record as it finally stands.

    Simulate exactly that future change by neutering the applier, and require
    `run()` to REFUSE rather than write the record: no results.json, no rc 0, no
    quiet green.
    """
    monkeypatch.setattr(F, "apply_resource_stop",
                        lambda results, stop: results)
    with pytest.raises(AssertionError, match="INCONCLUSIVE, never proved"):
        _run(tmp_path, monkeypatch, OUT_OF_MEMORY + PASSED,
             mem_limit_kb=4194304)
    formal = tmp_path / "proj" / "phase2" / "stage1" / "formal"
    assert not (formal / "results.json").exists(), (
        "a record the guard refused was written to disk anyway")


def test_the_regression_guard_is_not_vacuous(tmp_path, monkeypatch):
    """The control for the test above: with the applier INTACT, the very same
    transcript produces an honest record instead of a raise. So the raise is
    caused by the missing rule, not by the transcript."""
    res, proj, _ = _run(tmp_path, monkeypatch, OUT_OF_MEMORY + PASSED,
                        mem_limit_kb=4194304)
    assert res["verdict"] == "INCONCLUSIVE"
    assert res["all_proved"] is False
    assert (proj / "phase2" / "stage1" / "formal" / "results.json").is_file()


# ── the ceiling is the CALLER's to set, and it reaches the solver ──────────
def test_the_caller_can_grant_a_ceiling_and_it_is_the_one_dispatched(
        tmp_path, monkeypatch):
    _res, _proj, seen = _run(tmp_path, monkeypatch, PASSED,
                             mem_limit_kb=6 * 1024 * 1024, timeout=123)
    assert seen["mem_limit_kb"] == 6 * 1024 * 1024
    assert seen["timeout"] == 123


def test_no_explicit_ceiling_derives_one_from_the_host(tmp_path, monkeypatch):
    """Unbounded must never be the DEFAULT. Omitting the ceiling derives one."""
    monkeypatch.setattr(F, "memory_limit_kb", lambda: 32952508)
    _res, _proj, seen = _run(tmp_path, monkeypatch, PASSED)
    assert seen["mem_limit_kb"] == 32952508


def test_the_ambient_argv_puts_the_ceiling_before_the_solver():
    """`ulimit` must precede everything the solver runs: set after sby has
    started it bounds nothing, and the memory lives in the yosys sby spawns."""
    argv = F.local_bounded_argv("sby -f x.sby", 32952508)
    assert argv[:2] == ["bash", "-lc"]
    assert argv[2].startswith("ulimit -v 32952508; ")
    assert argv[2].endswith("exec sby -f x.sby")


def test_an_underivable_ceiling_emits_no_ulimit_rather_than_a_guess():
    """A guessed bound is one nobody can reason about, and too low is the same
    outage from the other end."""
    assert "ulimit" not in F.local_bounded_argv("sby -f x.sby", None)[2]
    assert "ulimit" not in F.local_bounded_argv("sby -f x.sby", 0)[2]


# ── the deadline reaches the TREE, not the launcher we happen to hold ──────
def test_the_deadline_kills_the_whole_process_group(tmp_path):
    """sby is a launcher; the 35.6 GB lived in the yosys it spawned. Signalling
    only our direct child is the #623/#628 shape, and it is what let the runaway
    keep growing after the client had given up on it.

    The child here backgrounds a grandchild that would touch a marker; the
    deadline fires first, and the marker must never appear.
    """
    marker = tmp_path / "grandchild_survived"
    argv = ["bash", "-lc", f"(sleep 3; touch {marker}) & wait"]
    t0 = time.time()
    rc, _out = F._run_group_bounded(argv, tmp_path, timeout=1)
    elapsed = time.time() - t0
    # rc 124 IS "the deadline fired" — it is the code `_run_group_bounded`
    # returns for exactly that and nothing else, so it states the property the
    # wall clock was standing in for. The stopwatch added nothing and could go
    # red on a loaded host while the deadline had fired correctly.
    assert rc == 124, (rc, f"observed {elapsed:.1f}s")
    time.sleep(3.2)
    assert not marker.exists(), (
        "the deadline killed the launcher and left its child running — the "
        "orphan is invisible in exactly the way that matters")


def test_a_command_that_finishes_inside_the_deadline_is_untouched(tmp_path):
    """The accept direction for the group kill."""
    rc, out = F._run_group_bounded(["bash", "-lc", "echo ok"], tmp_path,
                                   timeout=30)
    assert rc == 0 and "ok" in out


# ── nothing downstream may read INCONCLUSIVE as a pass ─────────────────────
def test_the_step5_gate_does_not_read_an_inconclusive_run_as_a_pass(
        tmp_path, monkeypatch):
    """The consumer, executed. `formal_proof_evidence_check` is the Step-5 gate
    that turns formal/results.json into a flow verdict; an INCONCLUSIVE record
    must not come back rc 0."""
    gate = importlib.import_module("formal_proof_evidence_check")
    _res, proj, _ = _run(tmp_path, monkeypatch, OUT_OF_MEMORY,
                         mem_limit_kb=4194304)
    rc = gate.main([str(proj)])
    assert rc != 0, "an inconclusive formal run was accepted as a pass"


def test_the_flow_only_keeps_a_formal_pass_on_verdict_pass_and_all_proved():
    """The other consumer: the phase-2 runner keeps `results.json` as Step-5
    evidence ONLY on `verdict == 'PASS' and all_proved`. Read as SOURCE so this
    stays true of the shipped call site rather than of a copy of it."""
    src = (Path(F.__file__).parent / "design_one_shot_runner.py").read_text()
    assert '_res.get("verdict") == "PASS" and _res.get("all_proved")' in src
