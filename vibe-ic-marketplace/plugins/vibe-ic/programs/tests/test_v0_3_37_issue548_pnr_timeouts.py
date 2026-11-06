"""ORGANIC #548 — phase3 heavy-design timeouts: size-adaptive PnR timeout
+ reset_dependency_check O(N) Pattern B.

(a) pnr step timeout is fixed at 3600s → rc=124 kills a ~29k-cell design;
    fix: size-adaptive _pnr_timeout_s(cells) scales above _PNR_TIMEOUT_DEFAULT_S
    for large designs, and per-stage checkpoint DEFs are preserved on timeout
    so a re-run can resume from the last completed stage.

(b) reset_dependency_check Pattern B O(N²) triple-loop causes >300s runtime
    on a 10MB flat synth netlist; fix: pre-indexed structures reduce to O(N).
"""
import sys
import time
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


# ── (a) size-adaptive PnR timeout resolver ──────────────────────────────────


# ── (a) checkpoint preservation + resume detection ──────────────────────────


def test_pnr_checkpoint_defs_survive_timeout(tmp_path):
    """Intermediate stage DEFs are not in _docker_timeout_isolate outputs —
    they are preserved across a timeout kill.  Evidence: runner_round5_phase3.log
    shows rc=124 with placed.def + post_cts.def already written before the kill.
    This test verifies calling _docker_timeout_isolate on the FINAL output does
    not touch the per-stage checkpoint files."""
    (tmp_path / "pnr").mkdir()
    (tmp_path / "pnr" / "placed.def").write_text("VERSION 5.8 ;\n")
    (tmp_path / "pnr" / "post_cts.def").write_text("VERSION 5.8 ;\n")
    (tmp_path / "pnr" / "chip_top.def").write_text("VERSION 5.8 ;\n")
    # Simulate what step_pnr does on rc=124: isolate only the FINAL output.
    R._docker_timeout_isolate([tmp_path / "pnr" / "chip_top.def"])
    assert (tmp_path / "pnr" / "placed.def").is_file(), \
        "placed.def stage checkpoint must survive timeout"
    assert (tmp_path / "pnr" / "post_cts.def").is_file(), \
        "post_cts.def stage checkpoint must survive timeout"
    assert not (tmp_path / "pnr" / "chip_top.def").is_file(), \
        "final def correctly renamed as .timeout.partial"


# ── (b) reset_dependency_check Pattern B performance ─────────────────────────

def _make_flat_netlist(n_cells: int) -> str:
    """Generate a synthetic flat Verilog netlist with `n_cells` instances.
    No reset connections → no circular deps; used only for performance test."""
    lines = ["module top;"]
    for i in range(n_cells):
        lines.append(
            f"  sky130_fd_sc_hd__and2_1 u{i} (.A(a{i}), .B(b{i}), .X(x{i}));")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def _cost_ratio_within(fn, small, big, factor, floor, attempts=3):
    """(ok, small_cost, big_cost) — best-of-N, but only spend the extra runs
    when the first one FAILS.

    A correct implementation pays ONE measurement of each size. A scheduling
    blip — the only way a correct implementation can miss — gets two more
    chances, and the MINIMUM is kept because a scheduler can make a run slower
    and never faster. A genuinely quadratic implementation is not run six times
    before anyone is told.
    """
    best_small = best_big = float("inf")
    for _ in range(attempts):
        t0 = time.perf_counter()
        fn(small)
        best_small = min(best_small, time.perf_counter() - t0)
        t0 = time.perf_counter()
        fn(big)
        best_big = min(best_big, time.perf_counter() - t0)
        if best_big <= max(best_small * factor, floor):
            return True, best_small, best_big
    return False, best_small, best_big
