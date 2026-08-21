#!/usr/bin/env python3
"""Tests for design_one_shot_runner.py — Phase 2b orchestrator (L docs → SOF).

Wave 83 — coverage for previously untested orchestrator.

Phase 2b runs RTL gen, reference TB, Yosys synth, QSF/SDC gen, FPGA
compile + burn, and example_tester verify. Most steps shell into Quartus / Yosys
which are not installed in the test environment, so we exercise the
orchestrator's control-flow only via:
  - precondition gate (13 L docs)
  - --dry-run early-exit
  - report shape

Cases:
  1. POSITIVE_FAIL_MISSING_PROJECT — non-existent project → exit 2.
  2. PRECONDITION_FAIL_NO_L_DOCS — empty project → phase1_precheck FAIL,
                                     verdict FAIL, exit 1, report emitted.
  3. DRY_RUN_WITH_13_L_DOCS — all 13 L docs present → --dry-run prints
                                plan JSON and exits 0 without invoking
                                Quartus / Yosys.
  4. INTEGRATION_REPORT_SHAPE — emitted phase2_one_shot.json contains
                                  ic_class / steps / verdict.
  5. EDGE_PARTIAL_L_DOCS_STILL_FAILS — 12/13 L docs → still FAIL.
  6. EDGE_TOP_NAME_FORWARDED — --top-name accepted (smoke).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "design_one_shot_runner.py"


#: 60 s, not 90: the harness runs this file at `--timeout=180
#: --timeout-method=thread`, so a 90 s inner bound cannot fire before the
#: session is killed and every other file in the subset loses its verdict.
#: MEASURED over this file's 7 launches (9 passed in 1.55 s): worst single call
#: 0.139 s, so 60 s is ~430x the worst case and constrains nothing.
#: Was invisible to `ci_harness_timeout_ceiling_check` until vibe-ic#1277 —
#: the bound is a parameter default, which the gate could not read.
def _run(args: list, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def _seed_l_docs(project: Path, n: int = 13) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (gd / f"L{i}_TST.json").write_text("{}")


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "no_such"
    cp = _run([str(missing)])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


def test_precondition_fail_no_l_docs(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 1
    rep = project / "reports" / "orchestrator" / "phase2_one_shot.json"
    assert rep.is_file()
    body = json.loads(rep.read_text())
    assert body["verdict"] == "FAIL"
    pre = next(s for s in body["steps"]
               if s["name"] == "phase1_precheck")
    assert pre["status"] == "FAIL"
    assert "13" in pre["detail"]


def test_dry_run_with_13_l_docs(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_l_docs(project, 13)
    cp = _run([str(project), "--dry-run"])
    # --dry-run path returns 0 after printing plan.
    assert cp.returncode == 0, cp.stderr
    # stdout starts with a JSON list of step plan
    out = cp.stdout.strip()
    assert out.startswith("[")
    plan = json.loads(out)
    assert any(s["name"] == "phase1_precheck" and s["status"] == "PASS"
               for s in plan)


def test_integration_report_shape(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase2_one_shot.json").read_text())
    for k in ("project", "ic_class", "steps", "verdict"):
        assert k in body
    assert isinstance(body["steps"], list)


def test_edge_partial_l_docs_still_fails(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_l_docs(project, 12)
    cp = _run([str(project)])
    assert cp.returncode == 1
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase2_one_shot.json").read_text())
    assert body["verdict"] == "FAIL"
    pre = next(s for s in body["steps"]
               if s["name"] == "phase1_precheck")
    assert pre["status"] == "FAIL"
    assert "12" in pre["detail"]


def test_edge_top_name_forwarded(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_l_docs(project, 13)
    cp = _run([str(project), "--dry-run", "--top-name", "tst_chip_top"])
    assert cp.returncode == 0
    # Plan parses without error; --top-name doesn't appear in dry-run plan
    # but the program at least accepted it without argparse error.
    plan = json.loads(cp.stdout.strip())
    assert isinstance(plan, list)


# ── DFT clock-derivation regression (opentitan_aes × sky130A) ──────────────
# Root cause: the DFT clock scan matched a prose COMMENT
# ("... the input of the multiplier is blanked in the next clock cycle ..."
# in aes_ghash.sv) and injected a phantom clock "clock", while the real
# comportable `clk_i` was structurally unreachable by the old regex. Result:
# Fault ATPG ran `--clock clock` on a design with no such port → 0 scan flops
# → DT1 (transition-fault ATPG) hard-FAIL.
import importlib.util as _ilu


def _load_derive_clock():
    spec = _ilu.spec_from_file_location("_d1s_clk", str(PROG))
    mod = _ilu.module_from_spec(spec)
    sys.modules["_d1s_clk"] = mod
    spec.loader.exec_module(mod)
    return mod._derive_dft_clock_name


def test_dft_clock_prefers_clk_i_over_comment_phantom():
    derive = _load_derive_clock()
    rtl = (
        "// during the last clock cycle of the multiplication ...\n"
        "//   input of the multiplier is blanked in the next clock cycle ...\n"
        "module chip_top(\n"
        "  input  logic clk_i,\n"
        "  input  logic rst_ni,\n"
        "  input  logic clk_edn_i\n"
        ");\nendmodule\n"
    )
    # NEGATIVE CONTROL: the prose 'clock' must NOT win; the real port does.
    assert derive(rtl) == "clk_i"


def test_dft_clock_derivation_variants():
    derive = _load_derive_clock()
    assert derive("input logic clk_i,") == "clk_i"          # suffix-style
    assert derive("input clk,") == "clk"                    # bare
    assert derive("input logic clk_edn_i,\ninput logic clk_i,") == "clk_i"
    assert derive("/* input clock */ input logic clk_i;") == "clk_i"  # block cmt
    assert derive("input logic rst_ni;") == ""              # no clock


# ── DFT clock-derivation regression (caravel user_project_wrapper × sky130A) ─
# The fallback branch used to accept only names that START with `clk` or contain
# the literal `clock`, which EXCLUDED the ubiquitous suffix form `wb_clk_i` and
# then let a secondary `user_clock2` (contains `clock`) win. Measured: all 33
# flops in the wrapper clock off wb_clk_i, yet the old rule derived user_clock2.
def test_dft_clock_wrapper_suffix_beats_secondary_clock():
    derive = _load_derive_clock()
    # the exact competing pair, in a wrapper header
    wrapper = ("module user_project_wrapper(\n"
               "  input wb_clk_i,\n"
               "  input wb_rst_i,\n"
               "  input user_clock2\n"
               ");\nendmodule\n")
    assert derive(wrapper) == "wb_clk_i"          # not user_clock2
    # other suffix/infix clock names are now reachable in the fallback
    assert derive("input sys_clk;\ninput ready;") == "sys_clk"
    assert derive("input core_clk;\ninput data;") == "core_clk"
    # allow-list names are unaffected (first branch), still exact
    assert derive("input i_clk;\ninput user_clock2;") == "i_clk"
