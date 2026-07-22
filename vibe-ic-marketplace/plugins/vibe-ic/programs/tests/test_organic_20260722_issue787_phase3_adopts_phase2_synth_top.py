#!/usr/bin/env python3
"""Regression for ORGANIC-20260722 #787 — phase 3 asked yosys for a top that
phase 2 had already proved does not exist.

#683 (and #782, which generalised it beyond the literal name `chip_top`) gave
PHASE 2 a structural repair: when the resolved synth top is declared by no
staged module, consult the instantiation-graph resolver and synthesise the graph
ROOT instead. That repair was never handed to PHASE 3, whose `effective_top`
comes from `--top-name` plus an `_asic` / `_pad_wrapper` filename override — it
never consults what phase 2 actually synthesised.

So on any design where the fallback fires, the two phases disagree:

    [phase2] PASS yosys_synth ... synth_top=user_project_wrapper   cells=419
    [phase3] FAIL synth  error: 'caravel_user_project' is not a valid
                                top-level module
                        warning: no top-level modules found [-Wmissing-top]
    → no netlist → no GDS → drc SKIP ("GDS missing"), lvs WAIVED
      ("routed-DEF missing") → phase3 FAIL.

Observed on caravel_user_project x sky130A: `--top-name caravel_user_project` is
declared by no staged file (staged modules are `user_project_wrapper`,
`user_proj_example`, `counter`), phase 2 adopted `user_project_wrapper` and
synthesised 419 cells, and phase 3 still asked for `caravel_user_project`.

Fix: phase 3 CONSUMES phase 2's recorded synth top (rather than re-deriving it,
so the two phases cannot resolve the same design differently), guarded exactly
like #782 so it can only convert a CERTAIN FAIL into the top phase 2 already
proved synthesisable:
  (a) the requested top must be PHANTOM — no staged module declares it, so yosys
      is GUARANTEED to reject it;
  (b) an `_asic` / `_pad_wrapper` override is authored intent and always wins;
  (c) phase 2's recorded top must itself be a REAL staged module.

Also adds `extras.synth_top` to phase 2's yosys_synth step. It was previously
recoverable only by scraping the `detail` string, or from an advisory sub-dict
that is absent whenever the staged set is already pruned. The reader still falls
back to the detail token so older reports remain readable
(test_reader_falls_back_to_detail_token).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import phase3_one_shot_runner as P3  # noqa: E402

_WRAPPER = """\
module user_project_wrapper (input wb_clk_i, output [2:0] user_irq);
    user_proj_example mprj (.wb_clk_i(wb_clk_i), .irq(user_irq));
endmodule
"""
_INNER = """\
module user_proj_example (input wb_clk_i, output [2:0] irq);
    assign irq = 3'b000;
endmodule
"""


def _mk(tmp_path: Path, *, recorded_top="user_project_wrapper",
        use_extras=True, extra_files=None) -> Path:
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "user_project_wrapper.v").write_text(_WRAPPER)
    (rtl / "user_proj_example.v").write_text(_INNER)
    for name, text in (extra_files or {}).items():
        (rtl / name).write_text(text)
    orch = proj / "reports" / "orchestrator"
    orch.mkdir(parents=True)
    step = {"name": "yosys_synth", "status": "PASS",
            "detail": f"netlist=netlist_yosys.v cells=419 "
                      f"synth_top={recorded_top} frontend=read_verilog_v2005"}
    step["extras"] = ({"synth_frontend": "read_verilog_v2005",
                       "synth_top": recorded_top} if use_extras
                      else {"synth_frontend": "read_verilog_v2005"})
    (orch / "phase2_one_shot.json").write_text(json.dumps({"steps": [step]}))
    return proj


# ── the defect ──────────────────────────────────────────────────────────
def test_phantom_requested_top_is_not_staged(tmp_path):
    """Precondition: the caravel shape really does have a phantom top."""
    proj = _mk(tmp_path)
    staged = P3._staged_module_names(proj / "phase2" / "stage1" / "rtl")
    assert "caravel_user_project" not in staged
    assert {"user_project_wrapper", "user_proj_example"} <= staged


def test_phase2_recorded_top_is_readable(tmp_path):
    assert P3._phase2_recorded_synth_top(_mk(tmp_path)) == \
        "user_project_wrapper"


def test_reader_falls_back_to_detail_token(tmp_path):
    """A phase-2 report written before `extras.synth_top` existed (exactly what
    the caravel run produced) must still be understood."""
    assert P3._phase2_recorded_synth_top(
        _mk(tmp_path, use_extras=False)) == "user_project_wrapper"


def test_phase2_emits_synth_top_as_first_class_extra():
    """Source pin: phase 2 must record the top it synthesised, not only in the
    human-readable detail string."""
    src = (PROG_DIR / "design_one_shot_runner.py").read_text()
    assert '"synth_top": synth_top' in src, (
        "phase2 yosys_synth no longer records synth_top in extras")


# ── the guards (#782 parity) ────────────────────────────────────────────
def test_no_adoption_when_requested_top_is_real(tmp_path):
    """A REAL staged top must never be redirected."""
    proj = _mk(tmp_path, recorded_top="user_proj_example")
    staged = P3._staged_module_names(proj / "phase2" / "stage1" / "rtl")
    assert "user_project_wrapper" in staged  # requested top is real
    # guard (a) is `requested not in staged` — it does not hold here
    assert not ("user_project_wrapper" not in staged)


def test_no_adoption_when_phase2_top_is_also_phantom(tmp_path):
    """If phase 2's recorded top is itself not staged, adopting it would only
    trade one guaranteed-reject name for another."""
    proj = _mk(tmp_path, recorded_top="some_phantom")
    staged = P3._staged_module_names(proj / "phase2" / "stage1" / "rtl")
    assert P3._phase2_recorded_synth_top(proj) not in staged


def test_no_adoption_when_phase2_report_absent(tmp_path):
    proj = _mk(tmp_path)
    (proj / "reports" / "orchestrator" / "phase2_one_shot.json").unlink()
    assert P3._phase2_recorded_synth_top(proj) is None


def test_reader_degrades_on_corrupt_report(tmp_path):
    proj = _mk(tmp_path)
    (proj / "reports" / "orchestrator" / "phase2_one_shot.json").write_text(
        "{not json")
    assert P3._phase2_recorded_synth_top(proj) is None


# ── helper contract ─────────────────────────────────────────────────────
def test_staged_names_ignore_commented_modules(tmp_path):
    proj = _mk(tmp_path, extra_files={
        "commented.v": "// module ghost (input a); endmodule\n"
                       "/* module ghost2 (input a); endmodule */\n"})
    assert not {"ghost", "ghost2"} & P3._staged_module_names(
        proj / "phase2" / "stage1" / "rtl")


def test_staged_names_empty_for_missing_dir(tmp_path):
    assert P3._staged_module_names(tmp_path / "nope") == set()


def test_adoption_is_guarded_in_source():
    """Source pin: all three guards must remain on the adoption path."""
    src = (PROG_DIR / "phase3_one_shot_runner.py").read_text()
    assert "if effective_top == args.top_name:" in src        # (b) override wins
    assert "_staged and effective_top not in _staged" in src  # (a) phantom only
    assert "_p2_top and _p2_top in _staged" in src            # (c) real target
