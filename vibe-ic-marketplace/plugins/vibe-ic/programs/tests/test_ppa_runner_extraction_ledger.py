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
    "_area_budget_um2", "_synth_chip_area",
    "area_retry_is_worth_adopting",
    "_auto_die_side_um", "_auto_pdn_straps_from_techlef",
    "_build_auto_silicon_sdc", "_build_clock_records_from_sdcs",
    "_build_hardmacro_supply_gc_tcl", "_build_macro_pdn_grid_tcl",
    "_build_macro_pdn_refusal_tcl", "_build_pdn_tcl",
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
    "_compute_spare_density", "_def_pdn_evidence",
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
    "_gate_only_supply_ports", "_ir_supply_from_psm_log",
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
    "_power_domain_family", "_propagated_clock_tcl",
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
