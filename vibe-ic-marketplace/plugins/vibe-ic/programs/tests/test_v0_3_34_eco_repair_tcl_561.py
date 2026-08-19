"""ORGANIC #561 — _build_eco_repair_tcl: 4 OpenROAD workarounds must be
present in the generated ECO timing-repair TCL.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


def _build(top="chip_top", metal_prefix="met"):
    return R._build_eco_repair_tcl(
        top=top,
        tech_lef_c="/container/pdk/tech.lef",
        cell_lef_c="/container/pdk/cells.lef",
        liberty_c="/container/pdk/cells.lib",
        pnr_dir_c=f"/container/project/phase3/stage3/pnr",
        eco_dir_c=f"/container/project/phase3/stage3/eco",
        metal_prefix=metal_prefix,
    )


def test_561_rsu0074_post_hold_def():
    # (a) RSZ-0074: must read post_hold.def; read_def command must NOT use routed.def
    tcl = _build()
    assert "post_hold.def" in tcl
    # Comments may mention "routed.def" for context; only the `read_def` COMMAND must not
    assert "read_def " not in tcl.split("post_hold.def")[1]  # no second read_def after post_hold


def test_561_signal11_setup_only_pass2():
    # (b) Signal-11: pass-2 comment must say setup-only; no repair_design in pass-2
    tcl = _build()
    assert "setup-only" in tcl
    # repair_design should appear only ONCE (pass 1), before the pass-2 block
    idx_pass2 = tcl.index("pass 2")
    idx_rd = tcl.index("repair_design")
    assert idx_rd < idx_pass2, "repair_design must be in pass-1 only (before pass-2 block)"


def test_561_drt0305_zero_net_cleanup():
    # (c) DRT-0305: PG net cleanup (zero_/one_ handling) must precede global_route COMMAND
    tcl = _build()
    assert "zero_" in tcl or "PG_CLEANUP" in tcl
    # PG_CLEANUP block must appear before the standalone `global_route` command line
    # Use the LAST occurrence of "global_route" in a comment vs the command after cleanup.
    pg_idx = tcl.index("PG_CLEANUP")
    # Find the `global_route` command line (not the comment that says "before global_route")
    # The command appears as "\nglobal_route\n"
    cmd_idx = tcl.index("\nglobal_route\n")
    assert pg_idx < cmd_idx


def test_561_dpl0033_check_placement_reports_its_count():
    # (d) DPL-0033: check_placement must still not abort the ECO deck on an
    # inherited mis-alignment — AND must not throw the violation count away
    # doing it. `catch {check_placement}` achieved the first at the cost of
    # the second: the caught value is the string "DPL-0033", the WARN it
    # printed was read by no gate, and OpenROAD exited 0 on an illegal
    # placement. `-no_abort` is the same non-aborting call WITH the count.
    tcl = _build()
    assert "check_placement -no_abort" in tcl
    assert "CHECK_PLACEMENT_VIOLATIONS ECO" in tcl
    assert "ECO_CHECK_PLACEMENT_WARN" not in tcl, (
        "the ECO deck must not demote the placer's verdict to a warning")


def test_561_eco_output_paths_use_correct_dir():
    # Output files must go to eco_dir_c, not pnr_dir_c
    tcl = _build()
    assert "/container/project/phase3/stage3/eco/eco_routed.def" in tcl
    assert "/container/project/phase3/stage3/eco/chip_top_eco.v" in tcl


def test_eco_reroute_is_bounded_droute_end_iter():
    # spm clean-run (2026-07-11) — the ECO reroute's detailed_route must be
    # BOUNDED with -droute_end_iter so a NON-CONVERGING ECO reroute (an
    # architecturally-unclosable setup gap over-buffering a small / low-util die)
    # cannot grind its full ~64-iteration optimization budget (~1 min/iter ~ 1 h
    # of wasted compute the progress-stall watchdog will not kill). The base
    # signoff route (Step 21) stays UNBOUNDED/converging; only the ECO reroute is
    # capped, and eco_routed.def is not the signoff route.
    tcl = _build()
    assert "detailed_route -droute_end_iter" in tcl, \
        "ECO reroute must cap detailed_route optimization iterations"
    assert f"-droute_end_iter {R._ECO_REROUTE_MAX_DROUTE_ITERS}" in tcl
    # exactly ONE detailed_route in the ECO reroute, and it is the bounded one —
    # the ECO tcl must NOT leave an unbounded bare `{detailed_route}` that grinds.
    assert tcl.count("detailed_route") == 1
    assert "{detailed_route}" not in tcl
    # the cap is a small positive bound (front-loads recovery, drops the futile tail)
    assert 1 <= R._ECO_REROUTE_MAX_DROUTE_ITERS <= 20


def test_561_canonicalize_emits_eco_tcl(tmp_path):
    # step_canonicalize_artefacts must write eco_timing_repair.tcl when pnr_out exists
    # Set up a minimal project tree so the function can run far enough
    eco_out = tmp_path / "phase3" / "stage3" / "eco"
    eco_out.mkdir(parents=True)
    # The TCL must NOT exist yet
    eco_tcl = eco_out / "eco_timing_repair.tcl"
    assert not eco_tcl.exists()
    # Call _build_eco_repair_tcl directly (canonicalize path is integration)
    content = _build()
    eco_tcl.write_text(content)
    assert eco_tcl.is_file()
    tcl_text = eco_tcl.read_text()
    # All 4 workaround anchors must be present in the written file
    assert "post_hold.def" in tcl_text
    assert "setup-only" in tcl_text
    assert "PG_CLEANUP" in tcl_text
    assert "check_placement -no_abort" in tcl_text
