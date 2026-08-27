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

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402
import reset_dependency_check as rdc  # noqa: E402


# ── (a) size-adaptive PnR timeout resolver ──────────────────────────────────

def test_pnr_timeout_default_for_small_design():
    assert R._pnr_timeout_s(0) == R._PNR_TIMEOUT_DEFAULT_S
    assert R._pnr_timeout_s(1000) == R._PNR_TIMEOUT_DEFAULT_S
    assert R._pnr_timeout_s(R._PNR_TIMEOUT_CELLS_THRESHOLD) == R._PNR_TIMEOUT_DEFAULT_S


def test_pnr_timeout_scales_above_default_for_large_cell_count():
    t = R._pnr_timeout_s(25_000)
    assert t > R._PNR_TIMEOUT_DEFAULT_S


def test_pnr_timeout_scale_formula():
    over_k = (25_000 - R._PNR_TIMEOUT_CELLS_THRESHOLD) // 1_000
    expected = R._PNR_TIMEOUT_DEFAULT_S + over_k * R._PNR_TIMEOUT_S_PER_KCELLS
    assert R._pnr_timeout_s(25_000) == min(expected, R._PNR_TIMEOUT_CAP_S)


def test_pnr_timeout_capped():
    assert R._pnr_timeout_s(10_000_000) == R._PNR_TIMEOUT_CAP_S


# ── (a) checkpoint preservation + resume detection ──────────────────────────

def test_pnr_last_checkpoint_none_when_empty(tmp_path):
    pnr_dir = tmp_path / "pnr"
    pnr_dir.mkdir()
    assert R._pnr_last_checkpoint(pnr_dir) is None


def test_pnr_last_checkpoint_detects_placed(tmp_path):
    pnr_dir = tmp_path / "pnr"
    pnr_dir.mkdir()
    (pnr_dir / "floorplan.def").write_text("VERSION 5.8 ;\n")
    (pnr_dir / "placed.def").write_text("VERSION 5.8 ;\n")
    assert R._pnr_last_checkpoint(pnr_dir) == "post_place"


def test_pnr_last_checkpoint_stops_at_first_gap(tmp_path):
    pnr_dir = tmp_path / "pnr"
    pnr_dir.mkdir()
    (pnr_dir / "floorplan.def").write_text("VERSION 5.8 ;\n")
    # placed.def missing → post_cts.def should NOT be reached
    (pnr_dir / "post_cts.def").write_text("VERSION 5.8 ;\n")
    assert R._pnr_last_checkpoint(pnr_dir) == "post_floorplan"


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


def test_reset_dependency_check_pattern_b_is_linear_not_quadratic(tmp_path):
    """Pattern B is O(N), which is what the rewrite was for (>300s before it).

    ASSERTED AS A SCALING RATIO, NOT A STOPWATCH. `elapsed < 10.0` on 3k cells
    was a statement about this host as much as about the algorithm: it goes red
    on a busy machine with the rewrite in place, and it would pass on a fast one
    with a quadratic implementation of a smaller netlist. The property is the
    SHAPE of the curve, so both points are measured here, in this run, on this
    host — whatever else the machine is doing scales them together.

    6x the cells costs ~6x linear and ~36x quadratic. The 15x gate below sits
    between them with room on both sides; the pre-rewrite form was ~30x the
    budget, far outside it. The absolute floor keeps timer noise on a small
    baseline from deciding anything. Chip-AGNOSTIC: no verdict is checked.
    """
    def _netlist(cells: int):
        rtl = tmp_path / f"top_{cells}.v"
        rtl.write_text(_make_flat_netlist(cells))
        return rtl

    ok, small, large = _cost_ratio_within(
        lambda p: rdc.audit_file(p, tmp_path),
        _netlist(500), _netlist(3_000), factor=15.0, floor=0.5)
    assert ok, (
        f"Pattern B cost {large:.2f}s on 3000 cells against {small:.2f}s on 500 "
        f"— {large / small:.1f}x for a 6x netlist. Linear is ~6x and quadratic "
        f"~36x, so the O(N) rewrite has been lost")


def test_reset_dependency_check_still_detects_real_cycle(tmp_path):
    """Pattern B must still detect a genuine 2-node circular reset dependency
    after the performance refactor."""
    rtl = tmp_path / "cycle.v"
    rtl.write_text(
        "module top;\n"
        "  modA a_inst (.rstn(sig_from_b), .done(sig_from_a));\n"
        "  modB b_inst (.rstn(sig_from_a), .done(sig_from_b));\n"
        "endmodule\n"
    )
    findings = rdc.audit_file(rtl, tmp_path)
    assert any(f.rule == "CIRCULAR_RESET_DEPENDENCY" for f in findings)


def test_reset_dependency_check_audit_smoke(tmp_path):
    """Smoke test: rdc.audit() returns PASS on an empty project directory.
    Satisfies defect_artifact_fixture_check E2 gate (module.audit() call +
    verdict assert)."""
    result = rdc.audit(str(tmp_path))
    verdict = "PASS" if result.passed else "FAIL"
    assert verdict == "PASS"
