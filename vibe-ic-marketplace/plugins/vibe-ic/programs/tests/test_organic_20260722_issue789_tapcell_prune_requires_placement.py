"""ORGANIC-20260722 #789 — the #684 anti-flood tap prune REQUIRES a placement.

WHAT #789 WAS
-------------
`_build_tapcell_tcl` used to insert full-die well-tie taps and then, on a
low-utilisation die, prune every tap outside the occupied-cell bounding box.
That prune ran at the FLOORPLAN stage, before `global_placement`, so every
standard cell was still unplaced and the "occupied region" was a fiction.
Measured on a sparse ~2920x3520 um fixed wrapper: kept=8, pruned=134170 — then
placement scattered the real logic across the whole die and PERC sign-off
correctly refused, "a placed std cell at (2881.90,1808.80) um is infinitely
(no tap in neighbourhood) from the nearest tap ... a CONCLUSIVE latch-up
spacing exposure".

HOW IT IS FIXED TODAY (v1.5.39, PR #259)
----------------------------------------
Insertion and prune were SPLIT. `_build_tapcell_tcl` now only inserts, full-die
and unconditionally, at the canonical pre-placement position; the locality +
safety-lattice prune moved into `_build_tapcell_prune_tcl`, which the flow
emits AFTER `global_placement` (real geometry) and BEFORE `write_def
placed.def` (so placed.def carries the final tap set and DEF-stage
monotonicity holds).

WHY THIS FILE EXISTS
--------------------
That fix is correct but its correctness is carried ENTIRELY by the emission
ORDER in `_build_pnr_tcl_text`. `_build_tapcell_prune_tcl` is unconditionally
destructive — it takes no placement-status guard and cannot tell whether the
instances it measures are placed. Nothing pinned the order: moving
`{tapcell_prune_block}` back above `global_placement` re-creates the #789
latch-up exposure verbatim and 342 pnr-template tests stay green.

These tests close that hole. They assert on the EMITTED TEXT of the real
pnr.tcl (built from the real sub-block builders, exactly as `step_pnr` wires
them), so an ordering regression fails here and forces a re-evaluation instead
of reaching silicon.

The PERC / latch-up sign-off gate is deliberately NOT involved: it caught #789
and it was right. chip-AGNOSTIC — the invariants are about flow order and
about insertion being unconditional, never about any chip, vendor or SKU.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


def _pdk() -> "R.PdkConfig":
    return R.PdkConfig(
        name="fixture_pdk",
        liberty="/pdk/lib.lib", tech_lef="/pdk/tech.lef",
        cell_lef="/pdk/cells.lef", cell_gds=None,
        site="unithd", drc_deck=None, metal_prefix="met",
        tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
        antenna_diode_cell="sky130_fd_sc_hd__diode_2",
        pnr_exclude_cell_file="/pdk/drc_exclude.cells",
    )


def _build(**overrides) -> str:
    """The COMPLETE pnr.tcl from the REAL sub-block builders, wired exactly as
    `step_pnr` wires them (including `tapcell_prune_block`, whose keyword
    default is "" — a hand-rolled stand-in would not see the true order)."""
    pdk = _pdk()
    out_dir_c = "/out"
    plan = R._build_spare_cells_plan(
        2000, 0.02, (10, 10, 290, 290), liberty_path="", container="")
    spare_pts_um = [
        (int(i.get("llx", 0)), int(i.get("lly", 0)))
        for i in plan.get("instances", []) if i.get("cell")]
    kw = dict(
        tech_lef_c="/pdk/tech.lef", cell_lef_c="/pdk/cells.lef",
        macro_lefs_tcl="", liberty_c="/pdk/lib.lib",
        macro_libs_tcl="", netlist_c="/w/netlist.v", top="chip_top",
        sdc_c="/w/chip_top.sdc",
        dont_use_block=R._dont_use_tcl(pdk),
        metal_prefix=pdk.metal_prefix, die_w=300, die_h=300,
        core_pad=10, core_w=280, core_h=280, site=pdk.site,
        out_dir_c=out_dir_c,
        tapcell_block=R._build_tapcell_tcl(pdk),
        pdn_block=R._build_pdn_tcl(pdk),
        util=0.45,
        spare_protection_tcl=R._build_spare_protection_tcl(plan, out_dir_c),
        spare_postfix_tcl=R._build_spare_postfix_tcl(
            plan, tie_lo_cell="sky130_fd_sc_hd__conb_1", tie_lo_pin="LO"),
        clk_buf="sky130_fd_sc_hd__clkbuf_4",
        clk_buf_root="sky130_fd_sc_hd__clkbuf_16",
        routing_constraint_tcl="",
        pg_cleanup_block=R._pg_net_cleanup_tcl(),
        spef_repair_block=R._post_route_spef_repair_tcl(out_dir_c, "/nope"),
        antenna_repair_block=R._antenna_repair_tcl(pdk),
        filler_block="",
        tapcell_prune_block=R._build_tapcell_prune_tcl(pdk, spare_pts_um),
    )
    kw.update(overrides)
    return R._build_pnr_tcl_text(**kw)


def _command_lines(tcl: str):
    """Non-comment, non-blank lines. The doctrine comments NAME the commands
    while explaining them, so order assertions must scan COMMANDS only."""
    return [ln for ln in tcl.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def _only_index(cmds, predicate, what):
    hits = [i for i, ln in enumerate(cmds) if predicate(ln)]
    assert len(hits) == 1, f"expected exactly one {what}, got {len(hits)}: " \
                           f"{[cmds[i].strip()[:90] for i in hits]}"
    return hits[0]


def _tap_insert_idx(cmds):
    return _only_index(cmds, lambda ln: "tapcell -distance" in ln,
                       "full-die tapcell insertion")


def _global_place_idx(cmds):
    return _only_index(cmds, lambda ln: ln.lstrip().startswith(
        "global_placement"), "global_placement")


def _tap_destroy_idx(cmds):
    return _only_index(
        cmds,
        lambda ln: "odb::dbInst_destroy" in ln and "_tap_kill" in ln,
        "anti-flood tap prune (dbInst_destroy over the tap kill-list)")


def _placed_def_idx(cmds):
    return _only_index(
        cmds,
        lambda ln: ln.lstrip().startswith("write_def")
        and "placed.def" in ln, "write_def placed.def")


# ── the #789 invariant: no tap is destroyed before a placement exists ───────

def test_the_antiflood_tap_prune_runs_after_global_placement():
    """THE #789 GUARD. `_build_tapcell_prune_tcl` measures instance geometry
    and DESTROYS every tap without a cell in its neighbourhood. It takes no
    placement-status guard, so it is sound ONLY once `global_placement` has
    resolved real coordinates. Before placement the cells are stacked at the
    origin, the occupied region collapses to a ~one-cell box, and the prune
    strips every tap over the silicon the placer is about to use — the
    conclusive latch-up exposure PERC sign-off caught."""
    cmds = _command_lines(_build())
    gp = _global_place_idx(cmds)
    destroy = _tap_destroy_idx(cmds)
    assert destroy > gp, (
        "the #684 anti-flood tap prune is emitted BEFORE global_placement — "
        "it would prune well-tie taps against a placement that does not exist "
        "yet and leave later-placed cells untapped (ORGANIC #789 latch-up "
        "exposure). Keep the prune after placement, or give it a "
        "placement-status guard that self-disables and RETAINS the full-die "
        "taps.\n"
        f"  global_placement @ cmd {gp}: {cmds[gp].strip()[:90]}\n"
        f"  tap prune        @ cmd {destroy}: {cmds[destroy].strip()[:90]}")


def test_the_tap_prune_precedes_write_def_placed_def():
    """The other constraint the split relies on: placed.def must already carry
    the FINAL (pruned) tap set, so every later DEF stage only GROWS and the
    DEF-stage monotonicity gate stays satisfied."""
    cmds = _command_lines(_build())
    assert _tap_destroy_idx(cmds) < _placed_def_idx(cmds)


def test_full_die_tap_insertion_precedes_global_placement():
    """Insertion stays at the canonical pre-placement position so the placer
    flows logic AROUND the fixed taps. (If it is ever moved after placement,
    tapcell overlaps placed cells — DPL-0005 — so this is load-bearing.)"""
    cmds = _command_lines(_build())
    assert _tap_insert_idx(cmds) < _global_place_idx(cmds)


def test_insertion_prune_and_placement_are_in_the_one_correct_order():
    """The whole ordering in one assertion, for a readable failure."""
    cmds = _command_lines(_build())
    order = [
        ("tapcell insertion", _tap_insert_idx(cmds)),
        ("global_placement", _global_place_idx(cmds)),
        ("anti-flood tap prune", _tap_destroy_idx(cmds)),
        ("write_def placed.def", _placed_def_idx(cmds)),
    ]
    assert [i for _n, i in order] == sorted(i for _n, i in order), \
        f"pnr.tcl emission order is wrong: {order}"


# ── the CRITICAL SUBTLETY: taps are inserted on EVERY path ─────────────────

def test_taps_are_inserted_on_every_path():
    """Insertion must be UNCONDITIONAL. #789's predecessor had an `else` arm
    that printed a SKIPPED message and inserted NOTHING, so a naive gate on
    the whole block traded an under-tapped die for a COMPLETELY untapped one.
    The floorplan-stage block must therefore contain no utilisation /
    occupancy conditional and no prune — only the insertion and its NONFATAL
    report."""
    block = R._build_tapcell_tcl(_pdk())
    assert "tapcell -distance" in block
    # every arm reports; neither arm can silently insert nothing
    assert "TAPCELL_INSERTED" in block
    assert "TAPCELL_NONFATAL" in block
    # no utilisation/occupancy gate may wrap the insertion
    for gate in ("_tap_util", "getCoreArea", "SPARSE_DIE", "_tap_ncore",
                 "_tap_nplaced"):
        assert gate not in block, \
            f"insertion is conditional on {gate!r} — it must be unconditional"
    # and no tap may be destroyed at the floorplan stage
    assert "odb::dbInst_destroy" not in block


def test_the_only_no_insertion_path_is_a_pdk_without_a_tapcell_master():
    """The single legitimate no-insertion path declares itself, and it also
    emits no prune (nothing to prune)."""
    class _NoTap:
        tapcell_master = None
        tapcell_distance_um = 14.0
    block = R._build_tapcell_tcl(_NoTap())
    assert "TAPCELL_SKIPPED" in block
    assert "tapcell -distance" not in block
    assert R._build_tapcell_prune_tcl(_NoTap()) == ""


def test_the_flow_always_emits_an_insertion_when_the_pdk_has_a_master():
    """End-to-end: whatever else the template does, a PDK with a tapcell
    master always reaches a real `tapcell` command in the emitted pnr.tcl."""
    cmds = _command_lines(_build())
    assert any("tapcell -distance" in ln for ln in cmds)


# ── NO-LEAK: the prune itself is unchanged (dense die keeps every tap) ─────

def test_dense_die_still_retains_the_full_die_taps():
    """The prune only ever fires under the sparse-die threshold; a dense or
    unknown-utilisation die keeps ALL taps. Pinned so the #789 ordering guard
    is never 'fixed' by making the prune fire more widely."""
    prune = R._build_tapcell_prune_tcl(_pdk())
    assert "TAPCELL_PRUNE_DENSE_OR_UNKNOWN" in prune
    thr = R._sparse_die_fill_threshold_pct()
    assert f"$_tap_util < {thr}" in prune


def test_prune_failure_retains_the_full_die_taps():
    """FAIL-SAFE direction: if the odb prune errors, the taps STAY. An
    untapped well is a latch-up defect; surplus taps are only area."""
    prune = R._build_tapcell_prune_tcl(_pdk())
    assert "TAPCELL_PRUNE_NONFATAL" in prune
    assert "full-die" in prune and "retained" in prune
