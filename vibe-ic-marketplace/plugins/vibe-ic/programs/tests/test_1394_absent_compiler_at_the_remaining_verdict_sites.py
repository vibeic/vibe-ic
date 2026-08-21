#!/usr/bin/env python3
"""vibe-ic#1394 residual — the absent-compiler defect at the TWO reference-TB
verdict sites #1398 did not reach.

#1398 established the predicate (`_compiler_was_not_found`) and the principle:
a compiler that never EXECUTED produced no evidence about the DUT, so the step
must not return a verdict on the design. It wired that into ONE of the three
places `step_reference_tb` turns a non-zero rc into a status. The other two
were still live, and both were reachable on the same host shape the issue
describes — iverilog only inside the container, run tree outside its bind
mounts, so the dispatch falls back to a host that has none.

MEASURED on 8HD-9 against `assign data_out = data_in;`, on main at f0bc498a
with the container up and the tree outside the mount::

    [AID path]        FAIL  "iverilog rc=127 stderr=COMMAND_NOT_FOUND:
                             [Errno 2] No such file or directory: 'iverilog'"
    [oracle TB path]  FAIL  "per-IC oracle TB (tb_core_top_oracle.v) failed to
                             compile against rtl/ — real structural defect
                             (#439). iverilog rc=127 stderr=COMMAND_NOT_FOUND"

The oracle site matters more than its position suggests: it is tried FIRST, so
on any project carrying an oracle TB the site #1398 guarded is never consulted
and the run still ends in a FAIL that cites rc=127 as proof of a defect.

TEETH, in both files and both directions: when the compiler RAN and rejected
the source, both sites still FAIL. The guard keys on `_compiler_was_not_found`,
never on a bare `rc != 0` — a predicate that matched "No such file or
directory" would convert a missing-`include` defect into a skip, which is the
inverse of this bug and worse than it.

chip/tool-AGNOSTIC: host/container tool-locality only. No chip, PDK, process or
vendor literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as dosr  # noqa: E402

#: The two rc-shapes the sites must tell apart, exactly as the runners emit
#: them (`_run` on FileNotFoundError, and a real iverilog rejection).
_ABSENT = (127, "", "COMMAND_NOT_FOUND: [Errno 2] No such file or "
                    "directory: 'iverilog'")
_REJECTED = (1, "", "core_top.v:1: syntax error\nI give up.\n")

_GOOD_RTL = ("module core_top(input clk, input reset_n, input data_in, "
             "output data_out); assign data_out = data_in; endmodule\n")


def _make_project(root: Path, top: str = "core_top") -> Path:
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": top,
        "top_ports": [{"name": "clk", "direction": "input"},
                      {"name": "reset_n", "direction": "input"},
                      {"name": "data_in", "direction": "input"},
                      {"name": "data_out", "direction": "output"}]}))
    rtl_dir = root / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / f"{top}.v").write_text(_GOOD_RTL)
    return root


def _pin_compile(monkeypatch, result):
    """Pin what the compile stage returns, so the site under test is reached
    deterministically on any host — with or without a simulator."""
    monkeypatch.setattr(dosr, "_iverilog_available", lambda *a, **k: True)
    monkeypatch.setattr(dosr, "_run_iverilog_stage",
                        lambda argv, run_dir, container, timeout=120: result)


def _seed_oracle_tb(proj: Path, top: str = "core_top") -> None:
    """An oracle TB makes `_run_oracle_tb` the site that decides — it is tried
    before the skeleton path, which is why guarding only the skeleton left the
    verdict wrong for every project that has one."""
    sim = proj / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / f"tb_{top}_oracle.v").write_text(
        f"module tb_{top}_oracle; {top} d(.clk(1'b0), .reset_n(1'b1), "
        f".data_in(1'b0), .data_out()); "
        f"initial $display(\"ORACLE_TB_DONE pass=1/1\"); endmodule\n")


# --------------------------------------------------------------------------
# SITE 1 — the AID reference-TB path (no availability probe at all)
# --------------------------------------------------------------------------
def test_aid_track_absent_compiler_skips_instead_of_failing(
        tmp_path, monkeypatch):
    _pin_compile(monkeypatch, _ABSENT)
    proj = _make_project(tmp_path)
    sr = dosr.step_reference_tb(proj, "core_top",
                                "aid_class_half_duplex_single_wire")
    assert sr.status == "SKIP", (sr.status, sr.detail)
    assert sr.extras.get("iverilog_available") is False
    assert sr.extras.get("functional_verified") is False
    assert "NOT FOUND" in sr.detail
    # it must not claim the sim happened, nor accuse the design.
    assert "defect" not in sr.detail.lower()


def test_aid_track_rejected_source_still_fails(tmp_path, monkeypatch):
    """TEETH. Same site, same class, compiler RAN and rejected the source."""
    _pin_compile(monkeypatch, _REJECTED)
    proj = _make_project(tmp_path)
    sr = dosr.step_reference_tb(proj, "core_top",
                                "aid_class_half_duplex_single_wire")
    assert sr.status == "FAIL", (sr.status, sr.detail)
    assert "syntax error" in sr.detail


# --------------------------------------------------------------------------
# SITE 2 — the per-IC oracle TB path, which is consulted FIRST
# --------------------------------------------------------------------------
def test_oracle_track_absent_compiler_never_names_the_dut(
        tmp_path, monkeypatch):
    _pin_compile(monkeypatch, _ABSENT)
    proj = _make_project(tmp_path)
    _seed_oracle_tb(proj)
    sr = dosr.step_reference_tb(proj, "core_top", "processor_cpu")
    assert sr.status in ("WAIVED", "SKIP"), (sr.status, sr.detail)
    assert "structural defect" not in sr.detail
    assert sr.extras.get("functional_verified") is not True


def test_oracle_track_rejected_source_still_fails(tmp_path, monkeypatch):
    """TEETH. A real compile rejection at the oracle site keeps its #439
    structural-defect FAIL — the guard reads the predicate, not `rc != 0`."""
    _pin_compile(monkeypatch, _REJECTED)
    proj = _make_project(tmp_path)
    _seed_oracle_tb(proj)
    sr = dosr.step_reference_tb(proj, "core_top", "processor_cpu")
    assert sr.status == "FAIL", (sr.status, sr.detail)
    assert "#439" in sr.detail
    assert "syntax error" in sr.detail


# --------------------------------------------------------------------------
# The two shapes must stay distinguishable at the predicate, or both sites
# above are guarding on a coin flip.
# --------------------------------------------------------------------------
def test_the_two_rc_shapes_are_told_apart():
    assert dosr._compiler_was_not_found(*_ABSENT) is True
    assert dosr._compiler_was_not_found(*_REJECTED) is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
