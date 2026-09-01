#!/usr/bin/env python3
"""A joint compile failure is attributed by the files its errors cite.

A candidate and a challenge are compiled together, so ``returncode != 0``
alone cannot say which side is broken. The dispatcher attributes the failure
by the files the error lines cite: only candidate RTL -> CANDIDATE_BROKEN
(repair-routed, never a proven FAIL), anything else -> INVALID. A FAIL
marker printed before a clean ``$finish`` is a FAIL: the challenge contract
requires the marker, not a non-zero exit.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import benchmark_dispatch as bd                         # noqa: E402
import benchmark_io_adapter as bio                      # noqa: E402


def _simulator_absent() -> str:
    """Why this host cannot EXECUTE a verification challenge, or "" if it can.

    Same live probe as test_benchmark_program_first_ai_review: the condition
    is the two binaries the production code itself looks for, and every
    branch the skipped tests cover is also pinned host-independently by the
    stubbed tests at the end of this module.
    """
    import shutil                                       # noqa: PLC0415
    missing = [tool for tool in ("iverilog", "vvp") if shutil.which(tool) is None]
    if not missing:
        return ""
    return ("NOT_MEASURED: this host has no " + " and no ".join(missing)
            + "; a verification challenge cannot be executed here")


_NEEDS_SIMULATOR = pytest.mark.skipif(
    bool(_simulator_absent()),
    reason=_simulator_absent() or "iverilog and vvp are both present")


ROUTING = {
    "nature": "spec_generation",
    "route": "SPEC_TO_RTL",
    "source": "no_context_heuristic",
    "needs_ai_parse": True,
}

_GOOD_RTL = ("module dut(input wire a, output wire y); "
             "assign y = a; endmodule\n")
_DUP_PORT_RTL = ("module dut(input wire a, input wire a, output wire y); "
                 "assign y = a; endmodule\n")
_INVERTED_RTL = ("module dut(input wire a, output wire y); "
                 "assign y = ~a; endmodule\n")
# The helper module is never instantiated, but its syntax error still stops
# the joint compile -- alongside a broken challenge it must NOT be read as
# proof that only the candidate is at fault.
_UNREACHABLE_BAD_HELPER_RTL = _GOOD_RTL + (
    "module vibeic_unused_helper(input wire b, output wire z); "
    "assign z = b b; endmodule\n")

_CHECKING_TB = r"""
module vibeic_ai_challenge_tb;
  reg a;
  wire y;
  dut candidate(.a(a), .y(y));
  initial begin
    a = 1'b0; #1;
    if (y !== 1'b0) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
    a = 1'b1; #1;
    if (y !== 1'b1) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
    $display("VIBEIC_AI_CHALLENGE=PASS");
    $finish;
  end
endmodule
"""

# Collects the verdict and exits through $finish: rc is 0 on both outcomes,
# only the printed marker distinguishes them.
_FINISH_ONLY_TB = r"""
module vibeic_ai_challenge_tb;
  reg a;
  wire y;
  reg ok;
  dut candidate(.a(a), .y(y));
  initial begin
    ok = 1'b1;
    a = 1'b0; #1; if (y !== 1'b0) ok = 1'b0;
    a = 1'b1; #1; if (y !== 1'b1) ok = 1'b0;
    if (ok) $display("VIBEIC_AI_CHALLENGE=PASS");
    else $display("VIBEIC_AI_CHALLENGE=FAIL");
    $finish;
  end
endmodule
"""

_NONEXISTENT_PORT_TB = r"""
module vibeic_ai_challenge_tb;
  reg a;
  wire y;
  dut candidate(.a(a), .y(y), .zz(1'b0));
  initial begin
    $display("VIBEIC_AI_CHALLENGE=FAIL");
    $display("VIBEIC_AI_CHALLENGE=PASS");
    $finish;
  end
endmodule
"""

_SYNTAX_BROKEN_TB = r"""
module vibeic_ai_challenge_tb;
  reg a wire y;
  dut candidate(.a(a), .y(y));
  initial begin
    $display("VIBEIC_AI_CHALLENGE=FAIL");
    $display("VIBEIC_AI_CHALLENGE=PASS");
    $finish;
  end
endmodule
"""

_BOTH_MARKERS_TB = r"""
module vibeic_ai_challenge_tb;
  initial begin
    $display("VIBEIC_AI_CHALLENGE=FAIL");
    $display("VIBEIC_AI_CHALLENGE=PASS");
    $finish;
  end
endmodule
"""


def _project(tmp_path: Path, rtl_source: str) -> Path:
    project = tmp_path / "project"
    (project / "input").mkdir(parents=True)
    (project / "input" / "phase1_prompt.md").write_text(
        "Design module dut with input a and output y; assign y = a.\n")
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(rtl_source)
    report = project / "reports" / "orchestrator"
    report.mkdir(parents=True)
    (report / "phase2_one_shot.json").write_text(json.dumps({
        "verdict": "PASS",
        "steps": [{
            "name": "rtl_gen", "status": "PASS", "detail": "fixture",
            "extras": {"deterministic_generator": "fixture_emitter"},
        }],
    }))
    return project


def _task(tmp_path: Path, rtl_source: str) -> tuple[Path, dict]:
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path, rtl_source)
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    return run, task


def _challenge(task: dict, tb_source: str) -> dict:
    path = Path(task["challenge_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tb_source)
    return {
        "schema": bd._CHALLENGE_SCHEMA,
        "path": str(path.resolve()),
        "sha256": bd._sha256_text(tb_source),
        "top_module": "vibeic_ai_challenge_tb",
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The test drives both input values and checks equality.",
        }],
        "expected_behavior": "Output y must equal input a combinationally.",
        "rationale": (
            "The prompt states a direct assignment, so two exhaustive scalar "
            "vectors establish whether the candidate implements that exact "
            "observable combinational behavior without relying on any oracle."),
    }


def _fail_review(task: dict, tb_source: str) -> dict:
    return {
        "schema": bd._AI_REVIEW_SCHEMA,
        "id": task["id"],
        "prompt_sha256": task["prompt_sha256"],
        "rtl_sha256": task["rtl_sha256"],
        "reviewer": {"kind": "AI", "model": "test-review-model"},
        "blind": {"oracle_accessed": False},
        "routing": {"verdict": "AGREE", "ai_nature": "spec_generation"},
        "semantic_review": {
            "verdict": "FAIL",
            "findings": [{"issue": "output does not directly track input"}],
            "prompt_evidence": [{
                "excerpt": "assign y = a",
                "supports": "The prompt explicitly requests a direct assignment.",
            }],
            "rationale": (
                "The candidate does not implement the direct assignment stated "
                "by the prompt; the attached exhaustive one-bit test "
                "demonstrates the mismatch without any benchmark oracle."),
        },
        "verification_test": _challenge(task, tb_source),
    }


def _write_review(task: dict, review: dict) -> None:
    path = Path(task["review_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review))


def _solve_report(run: Path, task: dict) -> None:
    result = {
        "id": task["id"], "ok": True, "candidate_ready": True,
        "accepted": False, "entry": "D1", "evidence": "RTL_SIM",
        "exit": "8", "routing_verdict": ROUTING,
        "candidate_origin": "PROGRAM", "ai_repair_required": False,
        "awaiting_ai": True, "awaiting_ai_review": True,
        "awaiting_ai_backup": False,
    }
    (run / "solve_report.json").write_text(json.dumps({
        "bench": "rtllm", "format": "rtllm", "total": 1,
        "solved": 1, "accepted": 0,
        "acceptance_policy": {
            "required": True,
            "review_task_schema": bd._REVIEW_TASK_SCHEMA,
            "review_schema": bd._AI_REVIEW_SCHEMA,
        },
        "results": [result],
    }))
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task])
    bd._write_jsonl(run / bd._BACKUP_WORKLIST, [])


# ---------------------------------------------------------------------------
# attribution itself is a pure string question -- pinned host-independently
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "errors, expected",
    [
        ("/w/rtl/dut.v:1: error: 'a' has already been declared.\n",
         (True, False)),
        ("/w/run/tb.v:3: error: port ``zz'' is not a port of candidate.\n"
         "2 error(s) during elaboration.\n",
         (False, True)),
        ("/w/rtl/dut.v:5: syntax error\n/w/run/tb.v:2: syntax error\n",
         (True, True)),
        ("i give up.\n", (False, False)),
    ],
)
def test_attribution_reads_the_cited_files(errors, expected):
    assert bd._joint_compile_attribution(
        errors, ["/w/rtl/dut.v"], "/w/run/tb.v") == expected


# ---------------------------------------------------------------------------
# live joint compiles through the production entry point
# ---------------------------------------------------------------------------
@_NEEDS_SIMULATOR
def test_broken_candidate_is_CANDIDATE_BROKEN_and_repair_routed(tmp_path):
    run, task = _task(tmp_path, _DUP_PORT_RTL)
    _solve_report(run, task)
    _write_review(task, _fail_review(task, _CHECKING_TB))

    result = bd._run_verification_challenge(
        task["candidate_snapshot"], _challenge(task, _CHECKING_TB))
    assert result["status"] == bd._CHALLENGE_CANDIDATE_BROKEN
    assert any("candidate RTL" in r for r in result["reasons"])
    # The compile error itself travels along for the repairer.
    assert any("dut.v" in r for r in result["reasons"])

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REPAIR_REQUIRED"
    assert verdict["challenge_result"]["status"] == \
        bd._CHALLENGE_CANDIDATE_BROKEN
    assert verdict["reasons"] == []

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    repairs = bd._read_jsonl(run / bd._REPAIR_WORKLIST)
    assert repairs[0]["status"] == "AI_SEMANTIC_REPAIR_REQUIRED"
    assert repairs[0]["challenge_result"]["status"] == \
        bd._CHALLENGE_CANDIDATE_BROKEN
    assert any("dut.v" in r for r in repairs[0]["challenge_result"]["reasons"])


@_NEEDS_SIMULATOR
def test_broken_challenge_buys_no_proven_fail(tmp_path):
    run, task = _task(tmp_path, _GOOD_RTL)
    _write_review(task, _fail_review(task, _NONEXISTENT_PORT_TB))

    result = bd._run_verification_challenge(
        task["candidate_snapshot"], _challenge(task, _NONEXISTENT_PORT_TB))
    assert result["status"] == "INVALID"
    assert any("only the challenge file" in r for r in result["reasons"])

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("not proven" in r for r in verdict["reasons"])


@_NEEDS_SIMULATOR
def test_unreachable_bad_helper_plus_bad_challenge_is_INVALID(tmp_path):
    # The reachability leak: a candidate whose only defect is an unreachable
    # helper module, joined with a deliberately broken challenge. File
    # attribution sees BOTH sides cited and refuses to blame the candidate
    # alone, so a broken test cannot ride a broken helper to repair routing.
    run, task = _task(tmp_path, _UNREACHABLE_BAD_HELPER_RTL)
    _write_review(task, _fail_review(task, _SYNTAX_BROKEN_TB))

    result = bd._run_verification_challenge(
        task["candidate_snapshot"], _challenge(task, _SYNTAX_BROKEN_TB))
    assert result["status"] == "INVALID"
    assert result["status"] != bd._CHALLENGE_CANDIDATE_BROKEN
    assert any("both candidate RTL and the challenge file" in r
               for r in result["reasons"])
    assert bd._validate_ai_review(task)["status"] == "REJECTED"


@_NEEDS_SIMULATOR
def test_a_passing_candidate_still_rejects_the_finding(tmp_path):
    run, task = _task(tmp_path, _GOOD_RTL)
    _write_review(task, _fail_review(task, _CHECKING_TB))

    result = bd._run_verification_challenge(
        task["candidate_snapshot"], _challenge(task, _CHECKING_TB))
    assert result["status"] == "PASS"
    assert bd._validate_ai_review(task)["status"] == "REJECTED"


@_NEEDS_SIMULATOR
def test_fail_marker_with_rc0_is_a_proven_fail(tmp_path):
    run, task = _task(tmp_path, _INVERTED_RTL)
    _write_review(task, _fail_review(task, _FINISH_ONLY_TB))

    result = bd._run_verification_challenge(
        task["candidate_snapshot"], _challenge(task, _FINISH_ONLY_TB))
    assert result["status"] == "FAIL"
    assert result["returncode"] == 0
    assert bd._validate_ai_review(task)["status"] == "REPAIR_REQUIRED"


@_NEEDS_SIMULATOR
def test_a_fail_marker_disqualifies_a_pass_marker(tmp_path):
    _, task = _task(tmp_path, _GOOD_RTL)
    result = bd._run_verification_challenge(
        task["candidate_snapshot"], _challenge(task, _BOTH_MARKERS_TB))
    assert result["status"] == "FAIL"


# ---------------------------------------------------------------------------
# a MISSING CAPABILITY never becomes CANDIDATE_BROKEN -- host-independent
# ---------------------------------------------------------------------------
def test_no_simulator_beats_a_broken_candidate(tmp_path, monkeypatch):
    _, task = _task(tmp_path, _DUP_PORT_RTL)
    challenge = _challenge(task, _CHECKING_TB)
    import shutil                                       # noqa: PLC0415
    real = shutil.which
    monkeypatch.setattr(
        bd.shutil, "which",
        lambda name, *a, **k: (None if name in ("iverilog", "vvp")
                               else real(name, *a, **k)))
    result = bd._run_verification_challenge(
        task["candidate_snapshot"], challenge)
    assert result["status"] == bd._CHALLENGE_UNAVAILABLE


def test_a_compile_timeout_is_never_CANDIDATE_BROKEN(tmp_path, monkeypatch):
    _, task = _task(tmp_path, _DUP_PORT_RTL)
    challenge = _challenge(task, _CHECKING_TB)
    monkeypatch.setattr(
        bd.shutil, "which", lambda name, *a, **k: f"/stub/bin/{name}")

    def _times_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="iverilog", timeout=30)

    monkeypatch.setattr(bd.subprocess, "run", _times_out)
    result = bd._run_verification_challenge(
        task["candidate_snapshot"], challenge)
    assert result["status"] not in (bd._CHALLENGE_CANDIDATE_BROKEN, "FAIL")
    assert result["status"] == "INVALID"
