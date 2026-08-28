#!/usr/bin/env python3
"""Regression for #833 — `analog_content_detected_must_emit_l5_check` exited 0
when it had measured nothing, so a vacuous skip joined the executed-PASS
numerator.

THE SHAPE
=========
The gate is registered in `flow_compliance_check._STRUCTURAL_RTL_GATES`, whose
driver (`_run_structural_rtl_gates`) reads the exit code and nothing else:
rc 0 -> PASS record, rc 1 -> FAIL, rc 2 -> SKIP (`skip_kind: input-missing`).
The gate printed `[SKIP] ... no analog keywords found` and returned 0. So a
project with no analog content anywhere — and a project with no input document
at all — were each credited with a full executed PASS for this gate.

MEASURED, base vs fixed, over every project root in the repo's corpora — a
root being a directory under `benchmark-data/` that carries `input/`,
`phase1/` or `phase2/`, not descending into a root's own subtree. 109 roots;
read-only, nothing under `benchmark-data/` was written:

    gate rc      base        fixed
    0            96          5      (4 [PASS] + 1 [PASS_WITH_WAIVER])
    1            13         13
    2             0         91
    transitions: 0 -> 2 on 91 roots; no other transition.

The 91 are NOT 91 moved published cells, and the difference is the whole
point of naming them. The P0 umbrella never invokes the gate on 61 of them
(no RTL directory -> the umbrella is SKIPPED-CONDITION), and
`_class_skipped_gates` already excludes it on a further 21 with
`skip_kind: class-not-applicable`. NINE roots actually invoke it, and on
each the audit JSON's `passed_gate_count` drops by exactly one while the P0
headline `_p0_verdict_count` holds at 210 of 246 (SKIP has always counted as
a verdict; only the PASS numerator moves):

    run_v0156/cvdp_agentic_8x3_priority_encoder_0003         144 -> 143
    run_v0156/cvdp_agentic_fixed_arbiter_0001                144 -> 143
    run_v0157/cvdp_agentic_8x3_priority_encoder_0003         144 -> 143
    run_v0157/cvdp_agentic_fixed_arbiter_0001                144 -> 143
    run_v0158/cvdp_agentic_8x3_priority_encoder_0003         144 -> 143
    run_v0158/cvdp_agentic_fixed_arbiter_0001                144 -> 143
    run_v0159/cvdp_agentic_8x3_priority_encoder_0003         141 -> 140
    run_v0159/cvdp_agentic_fixed_arbiter_0001                140 -> 139
    run_v1332_delta/runner_path/cvdp_copilot_cache_lru_0001  140 -> 139

`gate_skip_routing_check` — the static auditor of exactly this class — carried
this gate in its published `_UNROUTED_INVENTORY` with 1 unrouted skip path.
The fix drains it, and that inventory entry is deleted in the same commit
(the ratchet FAILs with "delete the inventory entry" otherwise, which is the
mechanism that stops a baseline outliving its truth). Its own published
residual moves with it, measured on the real tree:

    272 skip paths in scope: 174 routed / 98 unrouted in 53 gates  (base)
    272 skip paths in scope: 175 routed / 97 unrouted in 52 gates  (fixed)

WHAT IS ASSERTED, AND WHAT IS A CONTROL
=======================================
The rc-2 assertions are the fix. The PASS and FAIL assertions are CONTROLS
and hold identically before and after: a change that moved a real verdict
would be a different bug. The denominator assertion is new behaviour of its
own — "no input document" and "documents read, none analog" are different
facts and the skip now says which.

chip-AGNOSTIC: synthetic generic fixtures only.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _vacuous_exit as _vx  # noqa: E402
import flow_compliance_check as F  # noqa: E402
import gate_skip_routing_check as GSR  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_GATE_NAME = "analog_content_detected_must_emit_l5_check"
_GATE = _PROGRAMS / f"{_GATE_NAME}.py"


def _run(project: Path) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(_GATE), str(project)],
                          capture_output=True, text=True)


def _doc(project: Path, name: str, body: str) -> None:
    d = project / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")


def _l5(project: Path, blocks) -> None:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "L5_ADI_SPEC.json").write_text(
        json.dumps({"analog_blocks": blocks}), encoding="utf-8")


# ---------------------------------------------------------------------------
# The fix — both shapes of "nothing to compare".
# ---------------------------------------------------------------------------
def test_no_input_document_at_all_exits_with_the_vacuous_rc(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    r = _run(proj)
    assert r.returncode == _vx.RC_VACUOUS, (
        f"a project with no input document was compared against nothing; "
        f"rc must be {_vx.RC_VACUOUS}, got {r.returncode}. "
        f"stdout={r.stdout!r}")


def test_docs_present_but_no_analog_keyword_exits_with_the_vacuous_rc(
        tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _doc(proj, "spec.md",
         "# A purely combinational block\n\n"
         "Two inputs, one output, one enable. Synchronous to the bus.\n")
    r = _run(proj)
    assert r.returncode == _vx.RC_VACUOUS, (
        f"docs read, nothing analog in them: nothing was compared against "
        f"L5. rc must be {_vx.RC_VACUOUS}, got {r.returncode}. "
        f"stdout={r.stdout!r}")


def test_the_skip_states_its_denominator(tmp_path):
    """Which vacuity happened is a fact about the project, not noise.

    Before the fix both shapes printed the same sentence and the same rc, so
    "this project ships no documentation" and "this project's documentation
    describes a purely digital design" were the same record.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    out_empty = _run(empty).stdout

    withdocs = tmp_path / "withdocs"
    withdocs.mkdir()
    _doc(withdocs, "a.md", "purely digital counter\n")
    _doc(withdocs, "b.md", "bus interface, synchronous\n")
    out_docs = _run(withdocs).stdout

    assert "no scannable input document" in out_empty, out_empty
    assert "2 input document(s) scanned" in out_docs, out_docs
    assert out_empty != out_docs


def test_both_disclosure_channels_are_emitted(tmp_path):
    """rc 2 plus the line-start sentinel the per-step reader scans for.

    `_check_program_exit_zero` concatenates stdout and stderr before matching,
    which is why `_vacuous_exit.announce_vacuous` may write to stderr.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    r = _run(proj)
    assert r.returncode == _vx.RC_VACUOUS
    assert F._stdout_signals_vacuous(r.stdout + r.stderr), (
        f"stdout={r.stdout!r} stderr={r.stderr!r}")


# ---------------------------------------------------------------------------
# CONTROLS — identical before and after the fix.
# ---------------------------------------------------------------------------
def test_analog_content_recorded_in_l5_is_still_a_real_pass(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _doc(proj, "spec.md",
         "The block contains an internal LDO regulator for the core rail.\n")
    _l5(proj, [{"name": "core_ldo", "type": "ldo", "spec": "1.8V out"}])
    r = _run(proj)
    assert r.returncode == 0, (
        f"documented analog content that L5 records is a genuine PASS. "
        f"stdout={r.stdout!r}")
    assert "[PASS]" in r.stdout, r.stdout


def test_analog_content_absent_from_l5_is_still_a_real_fail(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    _doc(proj, "spec.md",
         "The block contains an internal LDO regulator for the core rail.\n")
    _l5(proj, [])
    r = _run(proj)
    assert r.returncode == 1, (
        f"documented analog content missing from L5 is a genuine FAIL. "
        f"stdout={r.stdout!r}")


def test_scan_order_is_deterministic(tmp_path):
    """`_scannable_docs` sorts; the FAIL message quotes `hits[cid][0]`.

    Before the extraction the walk used bare `iterdir()`, so which document
    the failure cited depended on readdir order — a gate's published evidence
    line is not allowed to depend on the filesystem.
    """
    import analog_content_detected_must_emit_l5_check as G
    proj = tmp_path / "proj"
    proj.mkdir()
    for name in ("z.md", "a.md", "m.md"):
        _doc(proj, name, "internal LDO regulator\n")
    names = [p.name for p in G._scannable_docs(proj)]
    assert names == sorted(names), names
    assert names == ["a.md", "m.md", "z.md"], names


# ---------------------------------------------------------------------------
# The consequence, through the real umbrella and the real static auditor.
# ---------------------------------------------------------------------------
def test_umbrella_no_longer_records_an_executed_pass_for_a_vacuous_run(
        tmp_path):
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top(input clk, output reg q);\n"
        "  always @(posedge clk) q <= ~q;\n"
        "endmodule\n")

    records = []
    F._run_structural_rtl_gates(proj, records_out=records)
    rec = next(r for r in records if r["name"] == _GATE_NAME)

    assert rec["verdict"] != "PASS", (
        f"a gate that compared nothing must not hold a PASS record. "
        f"record={rec}")
    assert rec["verdict"] == "SKIP", rec
    assert rec["evidence"].get("exit_code") == _vx.RC_VACUOUS, rec
    assert rec["evidence"].get("skip_kind") == "input-missing", rec


def test_the_gate_is_out_of_the_unrouted_inventory():
    """The baseline register must not outlive its truth.

    `gate_skip_routing_check`'s ratchet is exact in BOTH directions: an entry
    whose measured count reached zero FAILs the check with "delete the
    inventory entry". This pins that the deletion happened in the same commit
    as the fix rather than the register being left to claim a defect that no
    longer exists.
    """
    assert _GATE_NAME not in GSR._UNROUTED_INVENTORY
    res = GSR.audit(_PROGRAMS.parent)
    assert res.passed, [f.message for f in res.findings]
    # And the row itself, so this test cannot pass by the gate having
    # disappeared from the enumeration: it still HAS a skip path, and that
    # path is now routed. (`res.ratchet` has no per-gate measured map — a
    # `.get("measured", {})` here would be the very vacuity under fix.)
    row = next(r for r in res.rows if r.gate == _GATE_NAME)
    assert row.tier == 1, row          # its rc is read as a verdict today
    assert row.skip_paths == 1, row    # the branch still exists
    assert row.unrouted_paths == 0, row
    assert row.routed_paths == 1, row
    assert row.sentinel_only_paths == 0, (
        "routed by the rc channel, not only by the fragile stdout token")
