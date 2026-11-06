"""ORGANIC batch — Cluster D: clock/derived/FPGA checker fixes.

#569 derived_clock clock-usage confirmation + clock_plan comment-strip parity
#572 waiver step-id↔name cross-check / derived_clock dir --sdc / l10_tb paths
#558 fpga_burn JTAG-absent → SKIP (not FAIL)
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

import design_one_shot_runner as P2             # noqa: E402
import l10_tb_conformance_check as L10          # noqa: E402


# ── #569 — clock-usage confirmation ────────────────────────────────────────


# ── #569 adversarial-review no-leak regressions ───────────────────────────


# ── #572b — derived_clock accepts a DIRECTORY --sdc ────────────────────────


# ── #572a — waiver step-id↔name cross-check ────────────────────────────────


# ── #572c — l10_tb path fallback ───────────────────────────────────────────
def test_572c_tb_dir_falls_back_to_sim_root(tmp_path, monkeypatch):
    sim = tmp_path / "phase2/stage1/sim"
    sim.mkdir(parents=True)
    (sim / "tb_top.v").write_text("module tb_top; endmodule\n")
    monkeypatch.chdir(tmp_path)
    # default tb-dir is phase2/stage1/sim/tb (absent); must resolve to sim/
    resolved = L10._resolve_tb_dir("phase2/stage1/sim/tb")
    assert resolved is not None
    assert L10._tb_files_under(Path(resolved))


# ── #558 — fpga_burn JTAG-absent signature ─────────────────────────────────
def test_558_jtag_absent_signature():
    assert P2._jtag_hardware_absent("Error: No JTAG hardware available")
    assert P2._jtag_hardware_absent("jtagconfig\nNo JTAG hardware")
    # a real programming failure on an attached board is NOT the absent sig
    assert not P2._jtag_hardware_absent(
        "Error (213): Programming failed; verify mismatch at addr 0x40")
