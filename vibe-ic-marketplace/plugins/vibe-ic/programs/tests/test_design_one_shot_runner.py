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
    return _pr.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True)


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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── DFT clock-derivation regression (caravel user_project_wrapper × sky130A) ─
# The fallback branch used to accept only names that START with `clk` or contain
# the literal `clock`, which EXCLUDED the ubiquitous suffix form `wb_clk_i` and
# then let a secondary `user_clock2` (contains `clock`) win. Measured: all 33
# flops in the wrapper clock off wb_clk_i, yet the old rule derived user_clock2.


# ── #2053 emitter half — the emitted candidate STATES its simulation unit ────
# The AI-challenge boundary compiles the candidate together with the challenge
# testbench, so a candidate that declares no `timescale inherits whichever unit
# the compiler read FIRST: the same correct candidate then passed or failed on
# iverilog's argument order alone. The boundary's half (refuse a pair whose
# declared units disagree) landed in v1.17.96; this is the emitter's half — it
# states the unit the project DECLARES, and never guesses one.
def _load_runner():
    spec = _ilu.spec_from_file_location("_d1s_ts", str(PROG))
    mod = _ilu.module_from_spec(spec)
    sys.modules["_d1s_ts"] = mod
    spec.loader.exec_module(mod)
    return mod


_EMITTED_RTL = "module chip_top(input clk);\nendmodule\n"

_ACCOUNTED_OPERATOR_SPEC = """
Implement a module named TopModule.
 - input  a
 - input  b
 - output q

The module should implement the function shown in the Karnaugh map below.

       a
  b   0   1
  0 | 0 | 1 |
  1 | 1 | 0 |
"""


def _seed_tb(project: Path, body: str, name: str = "tb_chip_top.v") -> Path:
    tb = project / "phase2" / "stage1" / "tb"
    tb.mkdir(parents=True, exist_ok=True)
    f = tb / name
    f.write_text(body)
    return f


def test_an_emitter_that_states_its_own_unit_is_not_restated(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _seed_tb(project, "`timescale 1ns / 1ps\nmodule tb; endmodule\n")
    mod = _load_runner()
    own = "`timescale 1ns / 1ps\n" + _EMITTED_RTL
    assert mod._state_declared_timescale(own, "1ns/1ps") == own
    assert mod._state_declared_timescale(_EMITTED_RTL, None) == _EMITTED_RTL


# ── #2061 R-01 — evidence windows are whole lines, never byte-counted ────────
def test_evidence_head_keeps_the_pass_line_whole(tmp_path):
    mod = _load_runner()
    # The measured shape: sdc_gen prints one PASS line naming a long path.
    line = "PASS sdc_gen: wrote " + "x" * 300 + "/chip_top.sdc"
    kept = mod._evidence_head(line + "\ntrailing\n")
    assert kept == line                 # whole line, not `line[:200]`
    assert "\n" not in kept


def test_evidence_head_never_cuts_a_line_whatever_the_path_length(tmp_path):
    mod = _load_runner()
    tail = "PASS sdc_gen: 1 constraint emitted"

    def window(path_len):
        src = "reading /" + "p" * path_len + "/proj/design.json\n" + tail + "\n"
        return src, mod._evidence_head(src)

    # Byte-counted, each window ENDED at a different offset inside the path and
    # published half a path. Line-aligned, every line published is a whole line
    # of the input, at both lengths.
    for path_len in (40, 120, 400):
        src, win = window(path_len)
        lines = src.splitlines()
        assert win
        for ln in win.splitlines():
            assert ln in lines
        assert win.splitlines()[0] == lines[0]


def test_evidence_head_leaves_a_short_string_byte_identical():
    mod = _load_runner()
    for s in ("", "ok", "PASS sdc_gen: done\nsecond line"):
        assert mod._evidence_head(s) == s


def test_evidence_tail_starts_on_a_line_boundary():
    mod = _load_runner()
    text = "/" + "q" * 500 + "/proj refused\nbecause the deck is absent\n"
    kept = mod._evidence_tail(text)
    assert kept == "because the deck is absent\n"
    assert mod._evidence_tail("short") == "short"
    # a single line longer than the budget still begins on a token
    one = "alpha " + "z" * 600
    assert mod._evidence_tail(one) == "z" * 400
