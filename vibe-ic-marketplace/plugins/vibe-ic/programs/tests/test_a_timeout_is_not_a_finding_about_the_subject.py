#!/usr/bin/env python3
"""test_a_timeout_is_not_a_finding_about_the_subject.py

Four handlers from the timeout-as-verdict census that CAUGHT the timeout and
still recorded it as a defect in whatever they were pointed at. In each one the
program already had a way to say "I could not decide" — a second exit code, an
INCONCLUSIVE detail string, a distinct skip reason — and the timeout branch used
the ACCUSING one instead.

  * `verilator_timing_fallback_check.adjudicate` — the file's own exit-code
    table says rc 1 is "golden FAILS its own TB under Verilator" and rc 2 is
    "cannot adjudicate". Both timeout branches printed "cannot adjudicate" and
    returned 1.
  * `tb_vcs_only_construct_detect.floor_proof` — every rc it did not recognise
    was labelled VERILATOR_ABSENT, so a host where Verilator was PRESENT and
    merely slow published a record saying the tool was missing.
  * `handoff_bundle_check._git_apply_check` — "`git apply --check` timed out"
    was returned in the slot that means "does not apply", i.e. a finding about
    the candidate patch. The same file already had the right shape one function
    away, for a composed program that CRASHES.
  * `fresh_agent_rtl_bug_density_metric._resolve_repo_root` — git failing to RUN
    and git saying "not a repository" both became `None`, and the caller
    published the second as the reason. On a slow host the metric asserted
    something FALSE about the project it was pointed at.

BOTH DIRECTIONS, everywhere. Each fix keeps the conservative outcome exactly
where it was — the FLOOR still stands, the bundle is still not admitted, the
metric still declines to report a number — and changes only what the record
CLAIMS was observed. Where the fix moved an rc, the accompanying test asserts
the old rc's own meaning is still reachable by the thing that really means it.

No design, PDK, vendor or IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_a_timeout_is_not_a_finding_about_the_subject.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import verilator_timing_fallback_check as VF      # noqa: E402
import tb_vcs_only_construct_detect as TB         # noqa: E402
import handoff_bundle_check as HB                 # noqa: E402
import fresh_agent_rtl_bug_density_metric as FA   # noqa: E402


# ── the constructed violation, one shape reused ─────────────────────────────

class _NeverFinishes:
    """A `subprocess.run` that always reports the job did not finish.

    The SUBJECT is the handler, not the clock. What a program does once it has
    been told "this did not finish" is the whole question, and the answer does
    not depend on how that fact arrived — so the tests raise the exception the
    real bound raises rather than waiting out a real one.
    """

    def __init__(self):
        self.calls = 0

    def __call__(self, argv, *a, **kw):
        self.calls += 1
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout", 1))


# ── verilator_timing_fallback_check ─────────────────────────────────────────

_GOLDEN = ("module dut(input clk, output reg [3:0] q);\n"
           "  always @(posedge clk) q <= 4'd5;\n"
           "endmodule\n")
_TB_SRC = ("module tb;\n  reg clk = 0; wire [3:0] q;\n"
           "  dut uut(.clk(clk), .q(q));\n"
           "  initial begin #20; $finish; end\n"
           "endmodule\n")


def _tb_and_golden(tmp_path: Path):
    tb = tmp_path / "tb.v"
    golden = tmp_path / "golden.v"
    tb.write_text(_TB_SRC)
    golden.write_text(_GOLDEN)
    return tb, golden


def _adjudicate(tmp_path, monkeypatch, runner):
    tb, golden = _tb_and_golden(tmp_path)
    monkeypatch.setattr(VF, "verilator_available", lambda: True)
    monkeypatch.setattr(VF.subprocess, "run", runner)
    return VF.adjudicate(tb, golden, "tb", "dut", "dut", None,
                         list(VF._DEFAULT_PASS), list(VF._DEFAULT_FAIL))


def test_a_verilator_run_that_did_not_finish_is_not_a_finding_about_the_golden(
        tmp_path, monkeypatch):
    """THE FIX. rc 1 accuses the golden; rc 2 is this file's own word for
    "cannot adjudicate", which is what the message already said."""
    rc, msg = _adjudicate(tmp_path, monkeypatch, _NeverFinishes())
    assert rc == 2, (rc, msg)
    assert rc != 1, "a build that did not FINISH is being reported as one that FAILED"
    assert "cannot adjudicate" in msg
    assert "NOT a finding about the golden" in msg


def test_the_floor_still_stands_when_verilator_could_not_be_adjudicated(
        tmp_path, monkeypatch):
    """THE HALF THAT MUST NOT MOVE. The conservative direction of this gate is
    that an unadjudicated construct stays floored — never waved through as
    scorable. Moving the rc must not have moved that."""
    rc, msg = _adjudicate(tmp_path, monkeypatch, _NeverFinishes())
    assert rc != 0, "an unadjudicated TB became FAITHFUL — the guard was deleted"
    assert "FLOOR-D stands" in msg


def test_rc_one_is_still_reachable_by_a_golden_that_actually_fails(
        tmp_path, monkeypatch):
    """NON-VACUITY. The fix must not have emptied rc 1 of its meaning: a build
    that RAN and returned non-zero is still VERILATOR_UNFAITHFUL."""
    class _BuildFails:
        def __call__(self, argv, *a, **kw):
            return subprocess.CompletedProcess(
                argv, 1, stdout="", stderr="%Error: no.\n")
    rc, msg = _adjudicate(tmp_path, monkeypatch, _BuildFails())
    assert rc == 1, (rc, msg)
    assert "VERILATOR_BUILD_FAIL" in msg


def test_the_exit_code_table_states_which_of_the_two_a_timeout_is():
    """The table is what a caller reads before writing the branch. Leaving it
    saying rc 1 covers "cannot build" while a timeout now returns 2 would put
    the next author back where this started."""
    doc = VF.__doc__
    assert "A timeout is rc 2, never this." in doc
    assert "CANNOT ADJUDICATE" in doc


# ── tb_vcs_only_construct_detect ────────────────────────────────────────────

def test_a_slow_verilator_is_not_recorded_as_an_absent_one(
        tmp_path, monkeypatch):
    """The record is what survives the run. VERILATOR_ABSENT on a host that HAS
    verilator is a false statement about the host, published as measured."""
    tb, golden = _tb_and_golden(tmp_path)
    monkeypatch.setattr(VF, "verilator_available", lambda: True)
    monkeypatch.setattr(VF.subprocess, "run", _NeverFinishes())
    rec = TB.floor_proof(tb, golden, "tb", "dut")
    assert rec["verdict"] == "CANNOT_ADJUDICATE", rec
    assert rec["verdict"] != "VERILATOR_ABSENT"
    # and the conservative disposition is untouched
    assert rec["disposition"] == "FORK-FIXABLE", rec
    assert rec["rc"] == 2, rec


# ── handoff_bundle_check ────────────────────────────────────────────────────

def _patch_file(tmp_path: Path) -> Path:
    p = tmp_path / "candidate.patch"
    p.write_text("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n")
    return p


def test_a_git_apply_check_that_did_not_finish_is_not_a_conflicting_patch(
        tmp_path, monkeypatch):
    """THE FIX, in the shape this file already uses for a composed program that
    crashes: fail-closed, and say it was never judged."""
    monkeypatch.setattr(HB.subprocess, "run", _NeverFinishes())
    ok, detail = HB._git_apply_check(tmp_path, _patch_file(tmp_path))
    assert ok is False, "the item went green — fail-closed was deleted"
    assert "INCONCLUSIVE" in detail, detail
    assert "never judged" in detail
    assert "does not apply" not in detail, (
        "the bundle is still being told its patch conflicts, which is the "
        "finding nobody made")


def test_a_patch_that_really_conflicts_still_says_so(tmp_path, monkeypatch):
    """NON-VACUITY. The accusing sentence must still be reachable by the thing
    it accuses — otherwise the fix is a deletion of the check."""
    class _Conflicts:
        def __call__(self, argv, *a, **kw):
            return subprocess.CompletedProcess(
                argv, 1, stdout="", stderr="error: patch does not apply\n")
    monkeypatch.setattr(HB.subprocess, "run", _Conflicts())
    ok, detail = HB._git_apply_check(tmp_path, _patch_file(tmp_path))
    assert ok is False
    assert detail.startswith("does not apply:"), detail


# ── fresh_agent_rtl_bug_density_metric ──────────────────────────────────────

def test_a_git_that_could_not_run_is_not_a_project_outside_a_repository(
        tmp_path, monkeypatch):
    """THE FIX. The two ways `None` arrived are now distinguishable, because
    only one of them is a fact about the project."""
    monkeypatch.setattr(FA.subprocess, "run", _NeverFinishes())
    root, why = FA._resolve_repo_root(tmp_path)
    assert root is None
    assert "not inside a git repository" not in why, (
        "the metric is still asserting something about the tree it was pointed "
        f"at that it never established: {why!r}")
    assert "NOT MEASURED" in why, why


def test_a_project_genuinely_outside_a_repository_still_says_so(
        tmp_path, monkeypatch):
    """NON-VACUITY, the other arm: git RAN and answered. That answer is a real
    fact about the project and must survive."""
    class _NotARepo:
        def __call__(self, argv, *a, **kw):
            return subprocess.CompletedProcess(argv, 128, stdout="", stderr="")
    monkeypatch.setattr(FA.subprocess, "run", _NotARepo())
    root, why = FA._resolve_repo_root(tmp_path)
    assert root is None
    assert why == "not inside a git repository"


def test_the_published_skip_reason_carries_the_distinction(
        tmp_path, monkeypatch):
    """The reason is the only thing a reader of the report gets. It is what was
    wrong, so it is what the test asserts."""
    (tmp_path / "rtl").mkdir()
    monkeypatch.setattr(FA.subprocess, "run", _NeverFinishes())
    summary = FA.inspect(tmp_path)
    assert summary["skipped_reason"], "a skip with no reason is worse than both"
    assert "NOT MEASURED" in summary["skipped_reason"]
    assert summary["bug_commit_count"] == 0
    assert summary["bug_commits"] == [], (
        "a skipped metric must publish no findings at all")


# ── the pre-fix control ─────────────────────────────────────────────────────

def test_these_four_would_have_answered_wrongly_before_the_fix():
    """THE CONTROL, written so the PRE-FIX tree can RUN it and answer wrongly.

    Each assertion below is a property the old code did NOT have, phrased
    against something the old code DOES define, so nothing raises
    AttributeError and reports "observed nothing".
    """
    # verilator: the old table said rc 1 covered "cannot build the TB" with no
    # carve-out for a build that did not finish.
    assert "A timeout is rc 2, never this." in VF.__doc__

    # tb_vcs: the old mapping had no third label at all.
    assert "CANNOT_ADJUDICATE" in TB.floor_proof.__doc__

    # handoff: the INCONCLUSIVE shape existed for CRASHES only.
    src = Path(HB.__file__).read_text(encoding="utf-8")
    assert src.count("INCONCLUSIVE") >= 2, (
        "the git-apply timeout branch has stopped using the same shape the "
        "composed-program crash branch uses")

    # fresh-agent: the old `_resolve_repo_root` returned a bare Path|None.
    assert FA._resolve_repo_root.__doc__ and \
        "why-not" in FA._resolve_repo_root.__doc__
    assert getattr(FA, "_GIT_UNUSABLE_RC", None) == 127
