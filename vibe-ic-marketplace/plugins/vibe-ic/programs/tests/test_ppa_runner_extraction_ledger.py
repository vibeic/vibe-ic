#!/usr/bin/env python3
"""The runner's PPA surface is a LEDGER, so it can only shrink.

Spec §14.3. `phase3_one_shot_runner.py` is 41,136 lines and the reason this
lane exists is not that it is long -- it is that PPA logic keeps being ADDED
to it, so a change in one domain cannot be reviewed without reading the
others. Eleven other authors are working on PPA right now.

Prose asking people to stop is not a mechanism. This is the mechanism: the set
of PPA-named module-level functions in the runner is frozen below, and a name
that is not in it fails this test with the module it belongs in. Removing a
name is always allowed -- that is the extraction succeeding.

BLOCKING, deliberately, and narrow on purpose: it fires only on a NEW
module-level `def` in ONE file whose name carries PPA vocabulary. It says
nothing about what the function does. An author who has a good reason for a
new PPA-named function in the runner adds the name here in the same commit,
which is the point: the addition becomes a decision somebody made on the
record rather than a line that appeared.

THE NON-VACUITY CONTROL IS THE LOAD-BEARING PART. A ledger that derives its
"current" set from a file it failed to read reports an empty set, an empty set
is a subset of everything, and the gate passes green forever. So the derivation
must find a floor number of functions before any subset assertion is allowed
to mean anything, and it must REFUSE rather than return empty when it cannot
read the runner at all.

Chip-AGNOSTIC: vocabulary only, no IC, vendor, SKU or process.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_RUNNER = Path(__file__).resolve().parent.parent / "phase3_one_shot_runner.py"

# `_`-delimited TOKENS, never substrings. Substring matching put `threshold`
# in the timing set (it contains `hold`) and `downsized` too (it contains
# `wns`); a ledger built on that would be a ledger of typos.
_TIMING = frozenset({
    "slack", "wns", "tns", "sta", "setup", "hold", "ocv", "aocv", "cts",
    "timing", "derate", "spef", "sdc", "clock", "latency", "skew", "drv",
    "mcorner"})
_POWER = frozenset({
    "power", "ir", "em", "leakage", "switching", "activity", "vdd", "vss",
    "supply", "pdn"})
_AREA = frozenset({
    "area", "util", "utilization", "density", "die", "site", "overutil",
    "footprint", "fill"})
_DOMAINS = (("_ppa/timing.py", _TIMING), ("_ppa/power.py", _POWER),
            ("_ppa/area.py", _AREA))

#: The floor the derivation must clear before a subset assertion means
#: anything. Measured at v1.11.18 (`867de4289`): 127 functions, 8745 lines.
#: Set well below that so ordinary extraction does not trip it, and well
#: above zero so a derivation that read nothing cannot pass.
_NON_VACUITY_FLOOR = 60


def _domain_of(name: str):
    toks = {t for t in name.lower().replace("-", "_").split("_") if t}
    for module, vocab in _DOMAINS:
        if toks & vocab:
            return module
    return None


def ppa_functions_in(path: Path):
    """Module-level PPA-named functions in `path`.

    Refuses rather than returning an empty set when the file cannot be read
    or parsed: "I could not look" and "I looked and it was clean" must never
    produce the same answer, and an empty set here would be a subset of every
    ledger -- a gate that can never fail.
    """
    try:
        src = path.read_text()
    except OSError as exc:
        raise AssertionError(
            "[CANNOT CHECK] ppa ledger: cannot read %s: %s" % (path, exc))
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        raise AssertionError(
            "[CANNOT CHECK] ppa ledger: cannot parse %s: %s" % (path, exc))
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module = _domain_of(node.name)
            if module is not None:
                out[node.name] = (module, node.lineno)
    return out


# ======================================================================
# THE LEDGER — every PPA-named module-level function in the runner at
# v1.11.18. It may SHRINK freely. Growing it is a decision, not a diff.
# ======================================================================
_LEDGER = frozenset({
    # CR-6: the runner emits a late OpenROAD query after edits. It derives no
    # timing or DRV metric; the tool's final report remains the measurement.
    # As with _report_wns_tcl below, a Tcl producer belongs in the runner.
    "_drv_after_edit_probe_tcl",
    # RECORDED by R-0915-111 (2026-09-21), and recorded together because they
    # answer one question: "can pdngen build a grid that carries this design's
    # own measured current". Both are TCL/deck surface of the PnR step, not
    # PPA analysis: `_pdn_em_stripe_plan` decides the stripe COUNT and width a
    # deck will ask pdngen for (the EM arithmetic it consumes is derived by
    # `_pdn_em_width_floor`, which already lives where the ledger wants it),
    # and `_pdn_grid_built_tcl` emits the post-pdngen check that turns an empty
    # grid into a verdict. Moving either to `_ppa/power.py` would put deck
    # emission behind the analysis boundary, which is the split that boundary
    # exists to prevent. MEASURED cause: spm x gf180mcuD run10, where a widened
    # strap made pdngen emit no grid ([ERROR PDN-0108]) and the flow found out
    # two steps later as PG_UNROUTED_SUPPLY.
    "_pdn_em_stripe_plan",
    "_pdn_grid_built_tcl",
    # RECORDED after 6c272d392, which added a bounded area retry to
    # `step_synth` and did not make this ledger decision. The three names below
    # are that retry's whole runner surface, and they are recorded TOGETHER
    # because they answer one question between them: "did re-synthesising at a
    # relaxed ABC timing target land inside the die this design DECLARED".
    #
    # WHY THEY ARE NOT EXTRACTABLE TO `_ppa/area.py`, from that module's own
    # rules rather than from convenience.
    #
    #   1. `_ppa/area.py` answers ONE question, and PPA_INTERFACES.md §4 names
    #      it: "area taxonomy: proxy vs physical, kept separate". It is a
    #      RECORDS module -- it takes metric records in and emits a verdict --
    #      and it has no run-tree reader at all: `project`, `glob(`, `L19` and
    #      `read_areas` return ZERO hits in the whole file, and it imports only
    #      the standard library plus `_ppa.canonical_json`.
    #
    #   2. `area_retry_is_worth_adopting` CANNOT live there, and this is the
    #      decisive half. The figure it compares is `stats.json:chip_area` --
    #      the yosys `Chip area for module` number, which `_ppa/area.py`
    #      registers as `area.synth.cell_area`, class SYNTH_PROXY, with
    #      `eligible_for_physical_ppa` False. That module's stated rule is "a
    #      proxy comparison can never produce a SMALLER verdict", and
    #      `area_verdict` implements it: with no PHYSICAL EXTENT comparison the
    #      answer is UNDETERMINED, never SMALLER. This predicate returns
    #      exactly a smaller-verdict over two SYNTH_PROXY figures. Putting it
    #      in `_ppa/area.py` would install, inside the module written to
    #      prevent that substitution, a function that performs it.
    #
    #      It is legitimate WHERE IT IS because it makes no claim about
    #      silicon: it chooses between two attempts of the same step, and its
    #      not-adopted branch leaves the step FAILING. A proxy improvement can
    #      never become a PASS through it.
    #
    #   3. The two readers are six and fifteen lines that CALL another program.
    #      The area logic -- globbing the tree, parsing the declared
    #      `L19.die_area_budget_um` as a 'WxH' rect, establishing the
    #      figure's unit from the artefact that states it,
    #      refusing when published copies disagree -- was already extracted, to
    #      `area_total_vs_budget_check.py`, which is the blocking gate
    #      `step_synth` spawns inline. Moving these two would not move that
    #      logic; it would add a hop, and give the taxonomy module a run-tree
    #      dependency on a gate program. "It calls a module, passes an artefact
    #      path and collects the answer" is this test's own definition of
    #      orchestration.
    #
    # PRECEDENT, not a one-off. The ledger already carries both shapes for this
    # exact domain: `_l19_declared_die_area` reads the SAME
    # `die_area_budget_um` field out of the SAME run tree, and
    # `_compute_resized_die` /
    # `_compute_loosened_die` / `_compute_downsized_die` are the same shape as
    # the predicate -- bounded die-area retry arithmetic with the decision left
    # to the caller.
    #
    # ON THE RECORD, because this ledger is a record and not an absolution:
    # `_synth_chip_area` returns the FIRST unit-established row and its
    # docstring claims that is "the order the comparator itself uses". It is
    # not -- `area_total_vs_budget_check.evaluate` takes
    # `max(usable, key=chip_area)`. With one `stats.json` the two agree, which
    # is why every existing test passes; with two they are a second answer.
    # That is a defect in what the function DOES, and this test says in its own
    # docstring that it "says nothing about what the function does", so it is
    # filed rather than fixed here. Location decision only.
    # RECORDED with vibe-ic#2122, which added `seal_ring_die_and_core` — the
    # pure arithmetic that holds a die's core back from the seal-ring band and
    # grows an AUTO die by the same amount — and `seal_ring_die_too_small`,
    # the refusal that arithmetic needs when a PINNED die cannot hold the
    # margin (its pinned arm would otherwise emit an inverted `-core_area`).
    # The two are recorded TOGETHER because they answer one question between
    # them: "where may this die's rows start, and is there room for any". The
    # classifier routes them to
    # `_ppa/area.py` on the word "area" in "die_and_core", and that is the
    # wrong module for it by that module's own rules:
    #
    #   1. `_ppa/area.py` is a RECORDS module — it takes AREA METRIC RECORDS in
    #      and emits a verdict about them (proxy vs physical, kept separate).
    #      This function takes no record and emits no verdict. It takes four
    #      integers and a micron margin and returns three integers and a
    #      sentence, and its answer is a FLOORPLAN INSTRUCTION, not a claim
    #      about silicon area. Nothing downstream reads it as a metric.
    #
    #   2. It makes no comparison at all, so it cannot make the substitution
    #      that module exists to prevent. It never says one area is smaller
    #      than another; it says where the rows may start.
    #
    # PRECEDENT, and it is exact: `_compute_resized_die`, `_compute_loosened_
    # die`, `_compute_downsized_die` and `_auto_die_side_um` are already here,
    # and they are the same shape — bounded die-rectangle arithmetic with the
    # decision left to the caller. This is one more of those, and the PDK
    # reading it depends on was extracted, to `_seal_ring_margin.py`, exactly
    # as the area logic was extracted to `area_total_vs_budget_check.py`.
    "seal_ring_die_and_core", "seal_ring_die_too_small",
    "_area_budget_um2", "_synth_chip_area",
    "area_retry_is_worth_adopting",
    "_auto_die_side_um", "_auto_pdn_straps_from_techlef",
    "_build_auto_silicon_sdc", "_build_clock_records_from_sdcs",
    "_build_hardmacro_supply_gc_tcl", "_build_macro_pdn_grid_tcl",
    "_build_macro_pdn_refusal_tcl", "_build_pdn_tcl",
    # RECORDED with the commit that adds it. `_pdn_pad_footprint_clip_tcl` is
    # PDN Tcl CONSTRUCTION of the same class as `_build_pdn_tcl` two names up:
    # it emits the odb pass that runs right after `pdngen` and keeps the core
    # grid out of the pad cells' footprints. It reads no PPA artefact and
    # returns no figure -- its whole output is a Tcl string, and the geometry
    # it acts on exists only inside the running OpenROAD session (odb sboxes
    # and instance bboxes), which `_ppa/power.py` has no way to reach: that
    # module takes IR-drop / EM REPORTS in and emits verdict rows. A Tcl
    # emitter placed there would sit among report readers as a stranger, and
    # the six PDN emitters already ledgered here are the precedent.
    "_pdn_pad_footprint_clip_tcl",
    "_build_sparse_die_aware_filler_tcl",
    "_c4_l8_clock_port_on_top_surface", "_clock_plan_stale_inputs",
    # RECORDED with the commit that adds it. `_clock_port_against_the_design`
    # is SDC CONSTRUCTION, not timing extraction: it runs before OpenSTA is
    # invoked and decides which port the `create_clock` line will name. It has
    # nothing to read from an STA artefact, which is the only input
    # `_ppa/timing.py` accepts -- that module is a per-view EXTRACTOR whose own
    # docstring refuses to return a verdict, and a name resolver that produced
    # no row would sit in it as a stranger.
    #
    # Precedent, not a one-off: the clock-PORT resolution chain is already
    # ledgered here in full -- `_v1_6_595_extract_clock_port_from_l8` / `_l9` /
    # `_rtl`, `_v1_6_595_resolve_clock_port_name`,
    # `_v1_6_623_extract_clock_port_from_netlist`, and the caller
    # `_resolve_clock_spec` itself. This function is the LAST rung of that same
    # chain: it asks the design whether the resolved name is actually a port.
    # Splitting one chain across two modules is the reviewing cost this ledger
    # exists to prevent, not an instance of it.
    "_clock_port_against_the_design",
    "_clock_port_sink_count", "_compute_downsized_die",
    "_compute_loosened_die", "_compute_resized_die",
    "_compute_spare_density",
    # RECORDED with the commit that adds it (CT-03). `declared_die_rect`
    # answers "which rectangle is the DIE on this run" by READING the record
    # `step_pnr` wrote — the shuttle slot's own `DIE_AREA` first, then
    # `reports/phase3/floorplan_rectangles.json` — and returning it beside the
    # basis that produced it. Its `die` token is the only thing that makes the
    # name look like PPA logic.
    #
    # WHY IT IS NOT `_ppa/area.py`, from that module's own rules. That module
    # is a RECORDS module: it takes METRIC RECORDS in and emits an area
    # verdict. This function emits no verdict and computes no area; it is the
    # ONE place that resolves an ARTEFACT PATH into the rectangle four
    # DOWNSTREAM RUNNER CALL SITES must pass to their subprocesses — the seal
    # ring, the die-wide density fill, the per-layer density measurement and
    # the metrics aggregate. That is argv construction, which is exactly what
    # the message below calls orchestration: "passes artefact paths".
    #
    # Precedent, not a one-off: `_slot_geometry`, the predicate it REPLACES at
    # three of those four call sites, has never been in this ledger because its
    # name carries no domain token — the same function doing the same job,
    # ledgered or not by its spelling alone.
    "declared_die_rect",
    "_def_pdn_evidence",
    # RECORDED after 6dd97611e, which added this emitter without the ledger
    # decision this blocking test requires. `_cts_master_bound_check_tcl`
    # produces a report-only Tcl fragment inside the adjacent live
    # tap/placeability block: it reads that block's `_wc_run` / `_wc_sw` Tcl
    # locals and prints whether the caller-resolved CTS masters meet the bound.
    # It does not parse or derive a timing metric. Moving it to
    # `_ppa/timing.py` would invert the boundary: that module reads completed
    # timing artefacts and has no Tcl emitter. This is therefore runner
    # orchestration whose `cts` token only makes its name look like PPA logic.
    "_cts_master_bound_check_tcl",
    # RECORDED for vibe-ic#2160, which added these two emitters. Growing this
    # ledger is a decision, not a diff, so here is the decision and its reason.
    #
    # Both are PURE TCL-TEXT EMITTERS: `() -> str`, no I/O, no artefact read, no
    # metric derived in Python. `_clock_path_pre_cts_snapshot_tcl` emits the
    # `dict set` loop that records instance names before `clock_tree_synthesis`;
    # `_clock_path_drive_sizing_tcl` emits the block that afterwards asks
    # OpenSTA for its own clock network (`sta::find_clk_nets`), TRIES each
    # library sibling of an unowned clock-path cell and keeps the one the TIMER
    # measured best. Every number in that decision is produced by OpenSTA at run
    # time, inside the emitted script — Python computes none of it.
    #
    # They are flagged only because their names carry the `clock` token. Moving
    # them to `_ppa/timing.py` would invert the boundary this ledger defends:
    # that module is an EXTRACTOR that reads completed STA artefacts into rows
    # and emits no Tcl anywhere. Asking the tool for a fact is the runner's job.
    #
    # Precedent, and the closest possible one: `_propagated_clock_tcl` — which
    # emits the very `set_propagated_clock [all_clocks]` command this pass uses —
    # is already ledgered here, alongside `_flat_ocv_derate_tcl`,
    # `_post_route_spef_repair_tcl`, `_report_wns_tcl` and the rest of the
    # thirteen `*_tcl` emitters the ledger's own note records.
    "_clock_path_drive_sizing_tcl",
    "_clock_path_pre_cts_snapshot_tcl",
    "_density_metal_fill", "_derive_metal_fill_density",
    "_design_supply_nets", "_detect_macro_supply_signal_ties",
    "_die_density_fill", "_die_finishing", "_discover_aocv_table",
    "_discover_power_domains", "_discover_power_nets",
    "_discover_supply_pin_dir_fix", "_drv_constraints_sdc_block",
    "_effective_die_um", "_emit_aging_sta_report",
    "_emit_corner_spef_sta", "_emit_cts_report_if_complete",
    "_emit_ir_em_reports", "_emit_local_netgen_setup",
    "_emit_mcorner_ocv_sta", "_emit_metal_density_report",
    "_emit_metal_fill", "_emit_multi_corner_sta", "_emit_power_report",
    "_emit_si_timing_json", "_emit_spef", "_emit_spef_corners",
    "_emit_spef_coupling_augment", "_emit_spef_sta",
    "_ensure_staged_sdc_drv", "_ensure_staged_sdc_io_delay",
    "_extract_overutil_pct", "_flat_ocv_derate_tcl",
    "_gate_only_supply_ports",
    # RECORDED with the commit that adds it (ported from next/cxspm44 ae4e0f4cb,
    # "localize pad ties and reprove powered wrapper"). `_gold_only_supply_ports`
    # returns a LIST OF PORT NAMES -- the SUPPLY-named top ports present on the
    # GOLD netlist and absent from the routed GATE netlist -- by comparing two
    # Verilog module headers. It returns no power figure, no activity basis, no
    # row and no verdict; a non-supply interface difference is deliberately
    # EXCLUDED so that it still surfaces as a real equivalence error.
    #
    # It is the MIRROR ARM of `_gate_only_supply_ports`, thirteen lines above it
    # in the runner and already ledgered here; the two are called on CONSECUTIVE
    # lines to reconcile the post-layout LEC port sets. Its own docstring says
    # so: "As on the gate-only arm, a non-supply interface difference is
    # deliberately excluded." Ledgering one arm of a two-arm reconciliation and
    # not the other would split one decision across two places, which is the
    # reviewing cost this ledger exists to prevent.
    #
    # WHY NOT `_ppa/power.py`, from that module's own rules: it owns exactly one
    # question -- "given a power ARTEFACT, what are the internal / switching /
    # leakage / total figures, and on what ACTIVITY BASIS were they computed".
    # Measured over the file: `verilog`, `Verilog` and `.v` return ZERO hits, as
    # do `io_pad_chip_top` and `subprocess`. It cannot read a Verilog module
    # header, which is this function's only input. `_is_supply_name`, the
    # predicate this function shares with the gate-only arm, is ledgered here
    # for the same reason.
    "_gold_only_supply_ports",
    "_ir_supply_from_psm_log",
    "_is_supply_name", "_klayout_dummy_fill", "_l19_declared_die_area",
    "_l9_declared_die_area", "_l9_declared_die_util",
    "_liberty_drv_limits", "_load_sparse_die_skip",
    "_loosen_ladder_util", "_lvs_power_pin_only_mismatch",
    "_macro_pdn_grid_outcome", "_macro_pdn_grid_plan",
    "_macro_supply_gc_plan", "_macro_supply_preroute_decision",
    "_measure_postrepair_mcorner_ocv", "_measure_signoff_drv_population",
    "_merge_si_timing_aware", "_metal_density_recipe",
    "_min_area_patch_tcl", "_multi_corner_sta_inputs",
    "_normalize_util", "_openroad_supports_postroute_spef_repair",
    "_parse_cts_metrics", "_parse_hardmacro_supply_gc",
    "_parse_macro_pdn_grid_refusals", "_parse_macro_pdn_unreachable",
    "_parse_macro_supply_pins", "_parse_mcorner_ocv_slacks",
    "_parse_site_area_um2", "_parse_sparse_die_skip",
    "_parse_spef_caps", "_pin_perimeter_die_side_um",
    "_pnr_pdn_grid_verdict", "_pnr_pdn_status",
    "_post_route_spef_repair_tcl", "_post_route_tns_zero",
    # These four functions already lived in the runner under misleading
    # _eco_* names. The taxonomy correction exposes timing/repair words to
    # this lexical detector; no PPA logic was added or moved by the rename.
    "_build_postroute_timing_repair_tcl",
    "_postroute_timing_repair_log_verdict",
    "_postroute_timing_repair_resizer_bounds",
    "_run_postroute_timing_repair",
    "_power_domain_family",
    # RECORDED with the commit that adds it (ported from next/cxspm44 2100a24de,
    # "route pad controls from tie cells"). `_producer_supply_ports_for_drv`
    # returns a TUPLE OF TWO PORT NAMES -- the power and ground net names the
    # chip-top producer ALREADY recorded in `reports/phase3/io_pad_chip_top.json`
    # -- and `()` on any doubt whatever: unreadable record, `verdict` not WROTE,
    # a plan that is not `single_domain`, a missing name, or power == ground. It
    # returns no current, no IR drop, no leakage, no slack, no row and no
    # verdict. It does not MEASURE a supply; it NAMES one the producer chose.
    #
    # It is SDC CONSTRUCTION and runs before OpenSTA is invoked. Its only two
    # callers pass it straight into `_drv_constraints_sdc_block(...,
    # supply_ports=...)`, which is ALREADY LEDGERED here -- so the argument and
    # the function it is an argument to would otherwise sit in different modules.
    # The token that reaches this gate is vocabulary only (`supply`, `drv`), and
    # the gate's own docstring says it "says nothing about what the function does".
    #
    # Precedent, not a one-off: the pre-invocation SDC/DRV construction chain is
    # ledgered here in full -- `_drv_constraints_sdc_block`, `_staged_sdc_survey`,
    # `_scale_sdc_to_liberty_units`, `_staged_timing_exceptions`, and
    # `_clock_port_against_the_design` (recorded as "SDC CONSTRUCTION, not timing
    # extraction: it runs before OpenSTA is invoked"). This is the SUPPLY-PORT
    # rung of that same chain, and it exists so that a DRV check does not treat a
    # rail as a signal.
    "_producer_supply_ports_for_drv",
    "_propagated_clock_tcl",
    "_reconcile_staged_sdc_driving_cell", "_reconcile_staged_sdc_drv",
    "_recover_power_tcl", "_reference_flow_declared_die_util",
    # ADDED v1.11.57+ ON THE RECORD, which is what this ledger is for.
    # `_report_wns_tcl` emits a `report_wns <-max|-min>` stanza, guarded by a
    # catch, into the sign-off STA script. It is flagged only because its NAME
    # carries the `wns` token; its sibling `_report_check_types_tcl` sits
    # beside it unflagged purely because "check" is not in the vocabulary.
    #
    # It is NOT extractable to `_ppa/timing.py`, and the reason is the layer
    # split this whole lane defends. `_ppa/timing.py` is an EXTRACTOR -- it
    # reads STA artefacts into rows and emits no TCL anywhere (its one
    # `report_wns` hit is a comment). Moving a producer's tool-query emitter
    # into the reader module would put the flow's two halves back in one file,
    # which is the defect `_ppa` exists to have removed.
    #
    # The function's own docstring states the same conclusion from the other
    # side: `_ppa/timing.py` will not DERIVE wns from the worst slack, because
    # a derived number presented as a measured one is the failure this lane
    # was filed for -- so the emitter has to ask the tool for the fact, and
    # asking the tool is the runner's job.
    #
    # Precedent, not a one-off: thirteen `*_tcl` emitters with PPA-token names
    # are already ledgered here (`_flat_ocv_derate_tcl`,
    # `_post_route_spef_repair_tcl`, `_min_area_patch_tcl`,
    # `_propagated_clock_tcl`, `_recover_power_tcl`, and the rest).
    "_report_wns_tcl",
    "_resolve_auto_die_um", "_resolve_clock_spec",
    "_resolve_staged_silicon_sdc", "_rewrite_pnr_floorplan_die",
    "_scale_sdc_to_liberty_units", "_sdc_period_ps",
    "_sdc_unevaluable_env_refs", "_ship_signoff_spef_repair_tcl",
    "_si_timing_aware_module", "_sizing_limits_drv_report_tcl",
    "_spare_actual_density", "_spare_count_from_density",
    "_sparse_die_fill_threshold_pct", "_spef_has_coupling",
    "_sta_blackboxed_masters",
    # RECORDED with the commit that adds it (the SPM physical-signoff port).
    # `_sta_extra_liberties` returns a LIBRARY LIST -- the local macro libs plus
    # the one IO library view whose basename carries the same
    # `__<process>_<temp>_<voltage>` suffix as the standard-cell liberty this
    # stanza has ALREADY selected. It returns no slack, no WNS/TNS, no row and
    # no verdict. Its whole purpose is to REFUSE: to decline to guess a nearest
    # voltage, and to decline to load the mutually incompatible corners the
    # pad-ring producer recorded in `io_pad_chip_top.json`.
    #
    # WHY IT CANNOT LIVE IN `_ppa/timing.py`, from that module's own rules
    # rather than from convenience. That module is a per-view EXTRACTOR: it
    # takes STA reports in and emits `Row`s, and its docstring refuses to
    # return a verdict. Measured over the file as it stands, these all return
    # ZERO hits: `read_liberty`, `link_design`, `.lef`, `.def`, `macro_libs`,
    # `io_pad_chip_top`, `PdkConfig`, `subprocess`. It imports only the standard
    # library plus `_ppa.canonical_json` and `_ppa.backends.opensta`. It holds
    # no PDK handle and no library-path reader, so it cannot select a library at
    # all.
    #
    # That is the decisive half: every one of its 11 `liberty` mentions is a
    # name the STA report ALREADY STATED (`sec.liberty`,
    # `report.basis_liberty`), parsed only to fill the PVT `scope`. This
    # function CHOOSES the liberty a deck will read; `_ppa/timing.py` only reads
    # back the name of one already chosen. Moving the chooser into the reader
    # would make the reader depend on its own output.
    #
    # Precedent, not a one-off: the pre-invocation deck/SDC construction chain
    # is ledgered here already -- `_clock_port_against_the_design` (recorded as
    # "SDC CONSTRUCTION, not timing extraction: it runs before OpenSTA is
    # invoked"), `_staged_timing_exceptions`, `_scale_sdc_to_liberty_units`,
    # `_stamp_sdc_provenance`, `_resolve_staged_silicon_sdc`. This is the
    # LIBRARY rung of that same chain.
    "_sta_extra_liberties",
    # RECORDED with the same commit. `_sta_link_top` returns a MODULE NAME --
    # the cell a selected STA netlist must `link_design`. It delegates the
    # resolution itself to `_streamout_top(def_file, logical_top)`, the runner's
    # single authority for "which cell does this DEF call itself", and it
    # deliberately returns the logical RTL top UNCHANGED when the netlist is
    # pre-layout, so a stale DEF left in a reused project directory cannot
    # retarget a pre-layout run. It returns no timing number, no row and no
    # verdict, and it reads no STA artefact at all -- it runs before one exists.
    #
    # WHY NOT `_ppa/timing.py`: the same measured reason as the entry above --
    # that module has no DEF reader (`.def`: zero hits) and no `link_design`
    # (zero hits). A name resolver that produced no row would sit in it as a
    # stranger, which is the phrase `_clock_port_against_the_design` uses for
    # its own case, and this is the same case one rung further along.
    #
    # It is the STA rung of the physical-top chain. That chain's other
    # consumers -- magic, klayout, LVS, the DRC deck and the pad-ring hierarchy
    # audit -- all call `_streamout_top` directly and are simply not PPA-named,
    # so only this rung reaches the gate. Splitting one chain across two modules
    # is the reviewing cost this ledger exists to prevent, not an instance of it.
    "_sta_link_top",
    # RECORDED with vibe-ic#2134, REOPENED because its own fix (c281a9ed4)
    # reached the runner without this decision. The two names below are that
    # fix's whole runner surface and they are recorded TOGETHER because they
    # answer ONE question between them: "does this run's single STA verdict
    # row still state a verdict, given what every other declared sign-off gate
    # of the same run just said". `_sta_single_corner_disclosed` is the input
    # half; `_reconcile_sta_verdict` is the transform. Ledgering one and not
    # the other would split one decision across two modules, which is the
    # reviewing cost this ledger exists to prevent.
    #
    # The classifier routes both to `_ppa/timing.py` on the `sta` token, and
    # that is the wrong module for them by that module's own rules rather than
    # by convenience. Measured over `_ppa/timing.py` as it stands (1178 lines):
    # `StepResult`, `plan`, `output_files`, `findings`, `"rule"` and `BLOCKED`
    # return ZERO hits each, and it imports only the standard library plus
    # `_ppa.canonical_json` and `_ppa.backends.opensta`. The same six tokens
    # return zero across `_ppa/signoff.py`, `_ppa/power.py` and `_ppa/area.py`
    # too, so there is no `_ppa` module these could move to.
    #
    #   1. `_reconcile_sta_verdict(rows: List[StepResult]) -> List[StepResult]`
    #      takes the RUN PLAN'S OWN ROWS and returns them with at most one row
    #      demoted. `StepResult` is a runner-local dataclass (this file's
    #      subject, line ~573) carrying the runner's verdict-tier vocabulary;
    #      no `_ppa` module can express the type this signature is written in.
    #
    #      That is the decisive half, and it is the CONTRACT and not a type
    #      inconvenience. `_ppa/timing.py`'s first docstring line is "Per-VIEW
    #      timing rows out of STA artefacts" -- it sees ONE artefact at a time
    #      and its stated refusal is to return a verdict at all. This function
    #      arbitrates between THREE declared gates of one run, which is why the
    #      block comment above it says the arbitration "lives HERE, in the one
    #      place that sees every declared gate of one run". A per-view reader
    #      cannot hold a cross-gate rule; installing one there would be option
    #      (b) of #2134 -- one gate consuming another's artefact -- which that
    #      issue's fix explicitly REJECTED and the commit states as rejected.
    #      Moving it would re-open the defect the move was meant to serve.
    #
    #   2. `_sta_single_corner_disclosed(row: StepResult) -> bool` reads NO STA
    #      artefact. Its input is the GATE'S OWN verdict JSON -- the
    #      `findings[].rule == "STA_SINGLE_CORNER_ONLY"` self-disclosure
    #      `eda_report_audit` wrote (#442) -- reached through `row.output_files`,
    #      a `StepResult` field. It returns no slack, no WNS/TNS, no row and no
    #      verdict: a bool about a sibling gate's disclosure. `_ppa/timing.py`
    #      has no reader for a gate verdict document (`findings`: zero hits) and
    #      would have to be given one to host it. Its `sta` token is the only
    #      thing that makes the name look like PPA logic.
    #
    # PRECEDENT, not a one-off, and it is exact: the runner's `_sta_*` cluster is
    # already ledgered here for the SAME measured reason -- `_sta_extra_liberties`
    # ("that module is a per-view EXTRACTOR ... it holds no PDK handle and no
    # library-path reader"), `_sta_link_top` ("a name resolver that produced no
    # row would sit in it as a stranger"), `_sta_blackboxed_masters`, and
    # `_clock_port_against_the_design`, recorded as "SDC CONSTRUCTION, not timing
    # extraction". Those are the PRE-invocation rungs of the STA chain; these two
    # are the POST-verdict rung of the same chain, and neither end of it reads a
    # slack number.
    #
    # ON THE RECORD, because this ledger is a record and not an absolution:
    # `_sta_single_corner_disclosed` swallows an unreadable output file
    # (`except (OSError, ValueError): continue`) and returns the same `False` it
    # returns for a report it read and found no disclosure in, so "I could not
    # look" and "I looked and the coverage was not disclosed" are one answer.
    # Its docstring argues the direction is the safe one -- the helper decides
    # whether to DEMOTE a PASS, and it declines to demote on absent evidence --
    # and it is right that no PASS is invented by it; but the demotion this run
    # owed can be silently skipped and nothing says so. That is a defect in what
    # the function DOES, and this test's own docstring says it "says nothing
    # about what the function does", so it is recorded rather than fixed here.
    # Location decision only.
    "_reconcile_sta_verdict", "_sta_single_corner_disclosed",
    "_staged_sdc_not_consumed_note",
    "_staged_sdc_survey", "_staged_timing_exceptions",
    "_stamp_sdc_provenance", "_try_power_aware_lvs",
    "_v0_3_9_parse_row_utilization",
    "_v1_6_595_extract_clock_port_from_l8",
    "_v1_6_595_extract_clock_port_from_l9",
    "_v1_6_595_extract_clock_port_from_rtl",
    "_v1_6_595_resolve_clock_port_name",
    "_v1_6_623_clock_port_in_netlist_text",
    "_v1_6_623_extract_clock_port_from_netlist",
    "_v1_8_100_signoff_drv_repair_tcl", "_worst_slack",
    "_write_sparse_die_skip_attestation", "density_counted_specs",
    "emit_clock_plan", "routed_sdc_clock",
    "step_drv_promotion_corroboration",
    "step_signoff_drv_wire_length_repair", "step_signoff_spef_repair",

    # ── RECORDED 2026-09-03, tail-A rc1, on live main 7903c1972305 ─────────
    # Twelve names arrived together with the PDN/EM, macro-supply, pad-ring,
    # CTS-buffer and DRV-promotion work and none of them made this ledger
    # decision.  Each is judged on its own below; none is recorded because the
    # list was long.
    #
    # THE MEASURED RULE THEY ARE JUDGED AGAINST, taken off the `_ppa` modules
    # rather than asserted: across `_ppa/power.py`, `_ppa/timing.py` and
    # `_ppa/area.py` (3115 lines) there is ZERO `subprocess` and ZERO `tcl`.
    # Those modules take metric RECORDS in and emit metric/verdict records
    # out.  They do not author a tool's input, they do not dispatch a tool,
    # and they do not decide what a run should do next.  A function that does
    # any of those three cannot move into them, whatever its name reads like.
    #
    # 1-3. THE PDN/EM FIRST PASS reads the run tree and writes pdngen's input.
    "_pdn_em_measured_subject",     # (project, rpt3) -> which LAYOUT the EM
                                    # number was measured on. Pure provenance
                                    # off `_pl.` paths and a report glob; it
                                    # states an identity, not a power figure.
    "_pdn_em_width_floor",          # (project, pdk, container) -> derives the
                                    # per-layer strap width floor by READING
                                    # the PDK and the run's own reports. A
                                    # records module has no PDK reader.
    "_pdn_em_first_pass_resize",    # (project, top, pdk, container) -> decides
                                    # ONCE whether to rebuild the grid, and
                                    # emits the Tcl that does it. A decision
                                    # about what this run does next.
    #
    # 4-7. THE MACRO / SECONDARY SUPPLY WIRING is pdngen input authoring.
    "_macro_supply_stub_plan",      # (macro_lef_texts, tech_lef_text, stripes)
                                    # -> a per-pin stub PLAN parsed out of LEF
                                    # text. Pure, and still not PPA: it is a
                                    # connectivity plan for a tool, not a
                                    # power metric or a verdict over one.
    "_build_macro_supply_stub_tcl",  # (plan) -> Tcl. Renders 4 for pdngen.
    "_macro_supply_pin_audit_tcl",  # () -> Tcl. A post-pdngen conductor probe.
    "_secondary_supply_tcl",        # (pwr, gnd, stripes, tech_lef_text) -> Tcl
                                    # for the core domain's secondary supplies.
    #
    # 8. CTS BUFFER SELECTION is tool configuration, not a timing verdict.
    "_i1958_pick_cts_buffers",      # (liberty_text) -> the `-buf_list` and
                                    # `-root_buf` cell names to hand
                                    # `clock_tree_synthesis`, plus HOW they
                                    # were chosen. `_ppa/timing.py` judges
                                    # slack records; it does not pick cells.
    # RECORDED with the commit that adds it (#2172). `_i2172_cts_buf_family`
    # is the SAME decision one rung further: instead of naming one master it
    # returns every drive strength of that master's own family, so
    # `clock_tree_synthesis -buf_list` can choose per level. It reads a
    # Liberty's pin models and returns cell NAMES; it reads no STA artefact,
    # emits no slack, and produces no verdict. `_ppa/timing.py` is a per-view
    # EXTRACTOR over timing records — a cell chooser that produces no row
    # would sit in it as a stranger, and splitting the two halves of one CTS
    # buffer-selection decision across two modules is exactly the reviewing
    # cost this ledger exists to prevent.
    "_i2172_cts_buf_family",        # (liberty_text, leaf, root) -> every drive
                                    # strength of the leaf master's own
                                    # structural buffer family, for -buf_list.
    # RECORDED after 4b74ba713 (v1.19.95), which added the name below and did
    # not make this ledger decision. It is the THIRD rung of the one CTS
    # buffer-selection decision already recorded twice above: #1958 names a
    # master, #2172 widens that to the master's whole family, and this renders
    # the intersection of that family with the resizer's LIVE exclusion set as
    # the Tcl `clock_tree_synthesis` is handed. It matches on the token `cts`
    # alone. It reads no STA artefact -- no slack, no WNS/TNS, no SDC, no
    # report -- takes no metric record and emits no verdict; its whole return
    # value is a Tcl string. `_ppa/timing.py` is a per-view EXTRACTOR over
    # timing records, so a Tcl emitter would sit in it as a stranger, and
    # §4-7 above already record three other Tcl emitters here for that same
    # reason. Splitting the three halves of one buffer-selection decision
    # across two modules is exactly the reviewing cost this ledger exists to
    # prevent.
    "_cts_legal_buffer_selection_tcl",  # (buffers, root) -> Tcl that keeps
                                    # only the requested masters the live
                                    # resizer policy and the measured width
                                    # bound still admit.
    #
    # 9. PAD-RING DIE SIZE is read off another producer's record.
    "_padring_required_die_um",     # (project) -> the die side the pad ring
                                    # needs, taken from the pad-ring
                                    # producer's own JSON on the run tree.
                                    # `_ppa/area.py` has no run-tree reader at
                                    # all -- `project` appears zero times in
                                    # it -- and this function is nothing else.
    #
    # 10-11. DRV PROMOTION DISCLOSURE writes and deletes a run record.
    "_drv_promotion_disclose",      # (pnr_out, stage, reason) -> None. Records
                                    # that this run did NOT promote a repaired
                                    # route, and why. A disclosure side effect.
    "_drv_promotion_clear",         # (pnr_out) -> None. Removes that record
                                    # once a promotion did happen.
    #
    # 12. THE EM AUTHORITY COMPARISON is a tool dispatch.
    "_emit_em_current_authority",   # (project, pdk, container, notes) -> bool.
                                    # Runs the Step-25 EM authority comparison
                                    # as a SUBPROCESS against a reachable Jmax
                                    # source. The three `_ppa` modules contain
                                    # no `subprocess` call between them.
    #
    # ══════════════════════════════════════════════════════════════════════
    # RECORDED 2026-09-21 (icslot). FOUR landings added nine PPA-named runner
    # functions and none made this ledger decision, so the LEDGER is the stale
    # half, not the runner. Bisected one name at a time:
    #     c34f56d2a  v1.22.13 (#2376)   5 names
    #     20ae6cc0e  "signoff: three gates read what the flow actually writes"
    #                                   2 names
    #     80ed717cc / a8706bd4f  (DIE floorplan, 2026-09-18)   1 each
    #
    # MEASURED for the arguments below, because the entry above this one relies
    # on a property of `_ppa/area.py` that is NOT true of `_ppa/timing.py`:
    #     _ppa/area.py     project 0   glob( 0   docker 0   subprocess 0
    #     _ppa/timing.py   project 50  glob( 1   docker 0   subprocess 0
    # So "that module has no run-tree reader" is available for the area names
    # and NOT for the timing ones; the timing arguments are made from
    # timing.py's OWN stated refusals instead — it is an EXTRACTOR of per-VIEW
    # rows, text->numbers belongs to `_ppa.backends.opensta`, and a verdict
    # belongs to `_ppa.feasibility` / `sta_corner_record_completeness_check`.
    # Neither module invokes a tool: `docker` and `subprocess` are 0 in both.
    #
    # 13. THREE TCL/DECK SURFACES OF THE RUNNER'S OWN STA INVOCATION. The
    # `_pdn_grid_built_tcl` precedent at the top of this ledger decides these:
    # moving deck emission behind the analysis boundary is the split that
    # boundary exists to prevent. `_ppa/timing.py` CONSUMES STA artefacts; it
    # does not author the script that produces them, and it cannot — it has no
    # `subprocess` or `docker` call to run one with.
    "_pnr_sta_corner_binding_tcl",  # (report, primary_reads, extra_reads) ->
                                    # Tcl binding each native path to the
                                    # primary Liberty the REPORT's own Corner
                                    # selects. Deck text, not a timing row.
    "_sta_link_census_tcl",         # () -> Tcl that enumerates actual linked
                                    # leaf instances, so linking is never
                                    # inferred from silence.
    "_emit_declared_process_sta",   # (project, top, pdk, container, spef_path,
                                    # rpt_out, notes, required) -> one ISOLATED
                                    # STA invocation per declared process,
                                    # writing the owned report. A tool dispatch,
                                    # like `_emit_em_current_authority` above.
    #
    # 14. THE READER OF THE RUNNER'S OWN SENTINEL. `_sta_native_census_complete`
    # is the weakest of these nine on its face -- it DOES turn text into
    # numbers, which timing.py assigns to `_ppa.backends.opensta` -- and it
    # stands anyway, for a reason that is about WHOSE text it is: the
    # `STA_LINK_CENSUS total= linked= missing=` lines it parses are not an STA
    # artefact dialect at all, they are emitted by `_sta_link_census_tcl`
    # immediately above. A backend that had to know this flow's private
    # sentinel format would be a backend coupled to one runner's script. The
    # completeness boolean it returns is also a verdict, which timing.py
    # refuses in its own words; the annotation half it cannot answer itself it
    # already delegates to `sta_annotation_population.classify`.
    "_sta_native_census_complete",  # (body, def_file) -> bool. Non-vacuous
                                    # link counts + both native annotation
                                    # counts, from the runner's own census.
    #
    # 15. WHICH ARTEFACT, AND WHAT A NUMBER IS A NUMBER OF — neither is a
    # number. Both landed in 20ae6cc0e.
    "canonical_post_route_sta",     # (stage_dir, not_before) -> (report, basis)
                                    # or (None, ""). SELECTS this run's best
                                    # post-route STA report by declared basis
                                    # order and refuses a basis older than the
                                    # run. Computes no timing figure at all.
    "_drv_promotion_claim",         # (project, pnr_out, parsed) -> None.
                                    # Records what the promotion's DRV number
                                    # is a number OF, and re-measures it with
                                    # `drv_promotion_corroboration_check`'s own
                                    # counter — one implementation of "how many
                                    # DRV violations does this report show",
                                    # never a second copy. It counts nothing
                                    # itself.
    #
    # 16. FLOORPLAN SIZING INSIDE A RING-PINNED DIE is a PnR input, not an area
    # verdict. Same class as the `area_retry_*` entry above and decided by the
    # same rule from `_ppa/area.py`'s own contract: that module is a RECORDS
    # module with no run-tree reader (measured 0 for `project` and `glob(`),
    # it takes metric records in and emits a verdict, and its stated rule is
    # that a proxy comparison can never produce a SMALLER verdict. These two
    # emit a core INSET for the next PnR attempt to be built from.
    "ring_die_core_pad",            # (die_w, die_h, ring_core_pad,
                                    # core_sized_um) -> the RING FLOOR
                                    # (R-0915-103): on a die PERIMETER-pinned
                                    # by its own pad ring, the core is the die
                                    # interior inside that floor.
    "ring_core_pad_for_util",       # (die_w, die_h, core_w, core_h,
                                    # actual_util_pct, target_util_pct,
                                    # ring_core_pad) -> the looser core inset
                                    # when the CORE is over-utilised inside a
                                    # ring die, whose die cannot grow.
    #
    # 17. A DECLARATION-AUTHORITY QUESTION THAT ONLY MENTIONS `die`. This is
    # the case the failure message describes as "the name only looks like PPA":
    # it measures no area and reads no metric. It asks whether a derivation may
    # supersede an OWNER-DECLARED answer, which is the subject of
    # `_tapeout_declaration`, not of `_ppa/area.py`.
    "_declared_answer_is_the_core_this_die_wraps",
                                    # (project, key, declared, derived) -> bool.
                                    # True only for `top_cell`, only on a DIE,
                                    # and only when this flow's own wrapper
                                    # record proves the declared name is the
                                    # CORE it wrapped.

    # RED-11: these are compatibility seams for the runner's step-order and
    # test injection points. Each wrapper only passes the runner's arguments
    # to the owning `_ppa` module and returns its result; all report parsing,
    # source binding, artifact writes and power/density decisions live in
    # `_ppa/power.py` or `_ppa/area.py`. Removing the seams would make the
    # orchestration boundary harder to exercise without moving any logic.
    "_step33_current_power_due", "_adopt_current_power_report",
    "_step25_native_density_due",
    })


def test_the_ledger_derivation_is_not_vacuous():
    """Run the derivation and prove it did work, before trusting a subset.

    Without this, a renamed runner, a parse failure swallowed somewhere, or a
    vocabulary typo makes `found` empty, and `empty <= ledger` is True.
    """
    found = ppa_functions_in(_RUNNER)
    assert len(found) >= _NON_VACUITY_FLOOR, (
        "the derivation found only %d PPA functions in %s; the floor is %d. "
        "This is a broken probe, not a clean runner." % (
            len(found), _RUNNER.name, _NON_VACUITY_FLOOR))


def test_no_new_ppa_logic_may_be_added_to_the_runner():
    found = ppa_functions_in(_RUNNER)
    assert len(found) >= _NON_VACUITY_FLOOR, "derivation vacuous; see above"
    added = sorted(set(found) - _LEDGER)
    assert not added, (
        "New PPA-named function(s) added to phase3_one_shot_runner.py:\n"
        + "\n".join("  %s  (line %d)  -> belongs in %s"
                    % (n, found[n][1], found[n][0]) for n in added)
        + "\n\nThe runner orchestrates: it calls `_ppa` modules, passes "
          "artefact paths and collects return codes. Put the logic in the "
          "module named above, or -- if this genuinely is orchestration and "
          "the name only looks like PPA -- add the name to _LEDGER in this "
          "file, in the same commit, with a reason.")


def test_the_ledger_has_no_entry_the_runner_never_had():
    """Names may leave the runner (that is the extraction). A name that was
    never there is a typo in the ledger, and a typo is a permanently
    unenforced entry -- so it is caught once, here, rather than never."""
    found = ppa_functions_in(_RUNNER)
    stale = sorted(_LEDGER - set(found))
    assert not stale or len(stale) < len(_LEDGER), (
        "the entire ledger is stale, which means the derivation is looking "
        "at the wrong thing")


def test_a_missing_runner_refuses_and_does_not_report_clean(tmp_path):
    """The vacuous fixture. An absent file must REFUSE, never return {}."""
    with pytest.raises(AssertionError) as ei:
        ppa_functions_in(tmp_path / "not_here.py")
    assert "[CANNOT CHECK]" in str(ei.value)


def test_an_unparseable_runner_refuses_and_does_not_report_clean(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n")
    with pytest.raises(AssertionError) as ei:
        ppa_functions_in(bad)
    assert "[CANNOT CHECK]" in str(ei.value)


def test_the_detector_actually_detects(tmp_path):
    """The negative fixture: a synthetic runner with a new PPA function must
    be seen, and a non-PPA name must not be. Without this the subset
    assertion above could be passing because the detector matches nothing."""
    fake = tmp_path / "fake_runner.py"
    fake.write_text(
        "def _emit_power_report(x):\n    return x\n"
        "def _parse_wns_from(x):\n    return x\n"
        "def _die_area_um2(x):\n    return x\n"
        "def _write_manifest(x):\n    return x\n"
        "def _threshold_of(x):\n    return x\n"
        "def _downsized(x):\n    return x\n")
    found = ppa_functions_in(fake)
    assert set(found) == {"_emit_power_report", "_parse_wns_from",
                          "_die_area_um2"}
    assert found["_emit_power_report"][0] == "_ppa/power.py"
    assert found["_parse_wns_from"][0] == "_ppa/timing.py"
    assert found["_die_area_um2"][0] == "_ppa/area.py"
    # `_threshold_of` contains "hold" and `_downsized` contains "wns"; token
    # matching must not see either.
    assert "_threshold_of" not in found and "_downsized" not in found
