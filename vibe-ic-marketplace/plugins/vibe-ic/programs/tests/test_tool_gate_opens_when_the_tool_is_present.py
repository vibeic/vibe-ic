"""PAIRED GUARD for every `_HAVE_*` tool gate in this directory.

A skip is the correct response to a genuinely absent tool. A skip that fires
whether or not the tool is there is a SILENCED TEST wearing a skip's clothes,
and it is worse than the crash it replaced: the crash was at least loud.

The modules gated here launch `iverilog` (and `vvp`) directly and, before the
gate, raised `FileNotFoundError: No such file or directory: 'iverilog'` on any
host without it — including this one, where all eleven EDA tools are absent.
The gate converts that to a disclosed skip. Measured, per module, before/after:

    test_v1_1_63_full_moore_fsm_synth   2 failed,  7 passed ->  7 passed, 2 skipped
    test_v1_1_64_fsm_tabular_format     3 failed,  4 passed ->  4 passed, 3 skipped
    test_v1_1_65_ff_and_comb_state_synth 3 failed, 8 passed ->  8 passed, 3 skipped
    test_v1_1_76_mealy_sequence         2 failed, 11 passed -> 11 passed, 6 skipped

The PASSED counts are identical in every case: nothing that was running stopped
running, only the crashes became skips.

WHAT THIS FILE PROVES, on a host where the tool is missing: the gate is keyed on
the tool's PRESENCE and not stuck closed — with `shutil.which` reporting a path
the constant is True and the guard is a no-op. Without this, a gated module
could skip forever on every host and nothing would notice, which is the exact
failure the repo calls a check that passes over an empty population.

WHY THE REGISTER IS KEYED ON THE PATTERN AND NOT ON ONE NAME (#1385)
────────────────────────────────────────────────────────────────────
The first version scanned for the literal substring `_HAVE_TOOLS`. Measured on
`24ff95307`, that is one spelling out of TWENTY in use, across two
prefixes:

    _HAVE_IVERILOG 90   _HAVE_VERILATOR 9    _HAVE_TOOLS 5
    _HAVE_IV       24   _HAVE_DATASET   8    _HAVE_YOSYS 4
    _HAVE_EDA      20   _HAVE_SIM       7    _HAVE_RDL   3
    _HAVE_DS       16   _HAVE_CONTAINER 15

Eleven names for one concept, so the register covered 8 modules and the other
40 gated on a name it could not see. #1375 is the first live instance: it gates
seven tests on `_HAVE_EDA`, correctly, and this register would not have covered
a single one of them.

The key is the constant's DEFINITION, not its use in a `skipif(...)`. Both
gating shapes are in use here and only the definition catches both:

    @pytest.mark.skipif(not _HA(VE|S)_X, ...)  the majority
    if not _HA(VE|S)_X: pytest.skip(...)        the rest   <- in-body

Keying on `skipif(` would have dropped 7 pairs, SIX OF THEM modules this file
already covers — the widening would have narrowed it. The definition is also
what the assertions actually read, via `getattr(mod, const)`.

WHICH GATES THE `which` PROBE CANNOT DECIDE
───────────────────────────────────────────
`shutil.which` is not the discriminator for every `_HAVE_*`. Monkeypatching it
proves nothing about a gate keyed on a corpus directory or a package import, so
those are declared in `NOT_WHICH_GATES` with the discriminator NAMED.

That list is not an escape hatch. `test_a_declared_non_which_gate_is_really_not_which_keyed`
asserts each entry is genuinely INSENSITIVE to `which` — so a real tool gate
moved there to silence a failure fails immediately. An exclusion that must
prove it deserves the exclusion is the difference between a reasoned carve-out
and the silent omission that produced this gap in the first place.

CORRECTION, AND IT IS AGAINST THE FIRST VERSION OF THIS FILE
────────────────────────────────────────────────────────────
The first version keyed on the `_HAVE_` prefix alone. That is ALSO one spelling,
and it covered 59 of 102 pairs — missing 43 across nine `_HAS_*` names, found
while verifying #1430, which adds nine skips under `_HAS_IVERILOG`:

    _HAS_IVERILOG   27 pairs   <- the MOST common tool gate in this directory,
    _HAVE_IVERILOG  22 pairs      more frequent than the spelling I keyed on

I under-counted for exactly the reason the original defect existed: I censused
the population using the prefix I had already decided was the population. The
key is now `_HA(?:VE|S)_`, and the "eleven names" figure above was wrong — it
is twenty.

Widening also swept in two constants that share the prefix and are NOT gates
(a fixture string and an argv list). They are in `NOT_A_GATE` with the value
type that disqualifies them, and guarded: a bool cannot hide there.

    WHICH_GATES      92    shut under which->None, open under which->path
    NOT_WHICH_GATES  14    corpus dir, package import, two-stage docker probe
    NOT_A_GATE        2    not booleans; not gates at all
                    ---
                    108    every `_HA(VE|S)_*` definition in this directory

Nothing here shells out; `_HAVE_CONTAINER` is the one entry whose probe
attempts a real subprocess, and it fails closed immediately.

A GATE'S DISCRIMINATOR NEED NOT LIVE IN THE GATED MODULE (#1386, against #1311)
──────────────────────────────────────────────────────────────────────────────
Re-measured on `3d13e2c59`, the register drifted twice in two days, in two
DIFFERENT ways, and only one of them was the population growing:

  * two new modules gate on `_HAS_TOOLCHAIN` (`test_cvdp_gate_multifile_split`,
    `test_v1_1_46_pr42_emit_normalizer_hardening`). The pattern key noticed
    them the day they appeared, which is what it is for — registered above;
  * #1311 moved the cvdp cluster's `which` calls into `_sim_tools`, so
    `test_cvdp_gate._HAS_IVERILOG` / `_HAS_YOSYS` are DERIVED from a tuple
    resolved once at that helper's import. Reloading only the gated module
    re-runs `from _sim_tools import ...` against the cache, so the probe could
    not move those two gates at all.

The second is the interesting one, because the failure it produced was
ORDER-DEPENDENT rather than constant: the first `import_module` under a fake
also imported the helper under that fake and froze it there, so the CLOSED
direction passed and the OPENS direction failed — and had the parametrisation
run the other way round, the opposite two would have failed. `_probe` now
reloads the `which`-probing helpers (discovered by scanning, not listed) before
the gated module, and restores every one of them afterwards.

Parking those two in `NOT_WHICH_GATES` would also have gone green, and that is
exactly why it is wrong: through a cache they read INSENSITIVE to `which`, so
`test_a_declared_non_which_gate_is_really_not_which_keyed` — the guard on the
exclusion list — could not have caught the lie. An indirect tool gate is still
a tool gate; it needs a deeper probe, not a carve-out.
"""
from __future__ import annotations

import importlib
import re
import shutil
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

#: A module-level `_HAVE_* =` binding. This is the population key: it catches
#: the decorator and in-body gating shapes alike, and it names exactly the
#: attribute the assertions below read back off the reloaded module.
#: BOTH prefixes. `_HAS_` is not a variant spelling to be tidied away —
#: `_HAS_IVERILOG` (27 pairs) is the single most common tool-gate constant
#: in this directory, more frequent than `_HAVE_IVERILOG`. Keying on
#: `_HAVE_` alone covered 59 of 102 pairs and missed 43 across nine names.
_DEFN = re.compile(r"^(_HA(?:VE|S)_[A-Z0-9_]+)\s*=", re.M)

_SELF = Path(__file__).stem


def _scan() -> set:
    """Every (module, constant) pair defined in this directory."""
    found = set()
    for p in sorted(_TESTS.glob("test_*.py")):
        if p.stem == _SELF:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for const in set(_DEFN.findall(text)):
            found.add((p.stem, const))
    return found


def _reload(modname: str):
    return importlib.reload(importlib.import_module(modname))


def _which_probing_helpers() -> tuple:
    """Non-`test_*` modules in this directory that probe `shutil.which`.

    A gate's discriminator does not have to live in the gated module. #1311
    moved the cvdp cluster's two probes into `_sim_tools`, whose `MISSING` is
    resolved ONCE at that module's import — so `test_cvdp_gate._HAS_IVERILOG`
    is now derived rather than probed. Reloading only the gated module re-runs
    its `from _sim_tools import ...` and gets the same cached tuple back, so
    the probe could not move the gate at all.

    Discovered by scanning, not hand-listed: the day another helper starts
    probing `which`, the reload reaches it without an edit here.
    """
    helpers = []
    for p in sorted(_TESTS.glob("*.py")):
        if p.stem.startswith("test_") or p.stem == "conftest":
            continue
        if "shutil.which" in p.read_text(encoding="utf-8", errors="replace"):
            helpers.append(p.stem)
    return tuple(helpers)


#: Resolved once; asserted non-empty by
#: `test_the_probe_reaches_a_discriminator_that_lives_in_a_HELPER_module`.
_WHICH_HELPERS = _which_probing_helpers()

_ABSENT = lambda *_a, **_k: None                       # noqa: E731
_PRESENT = lambda name, *_a, **_k: f"/usr/bin/{name}"  # noqa: E731


def _probe(modname: str, const: str, fake):
    """`modname.const` as it reads when `shutil.which` behaves like `fake`.

    Reloads the helpers that own an INDIRECT discriminator before the gated
    module, so a gate derived from `_sim_tools.MISSING` moves with the fake
    exactly as a gate that calls `which` itself does.

    Then puts everything back — the patched function AND every module it
    reloaded. A probe that walked out leaving `_sim_tools.MISSING = ()` would
    hand the rest of the session a module that believes yosys is installed,
    and the 38 cvdp tests it guards would run and fail against a refusal. That
    is not hypothetical ordering-paranoia: before the restore existed, whether
    the cvdp gates read True or False depended on which parametrised test ran
    FIRST, because the first `import_module` under a fake also imported the
    helper under that fake and froze it there.
    """
    real = shutil.which
    shutil.which = fake
    try:
        for helper in _WHICH_HELPERS:
            _reload(helper)
        return getattr(_reload(modname), const)
    finally:
        shutil.which = real
        for helper in _WHICH_HELPERS:
            _reload(helper)
        _reload(modname)

#: Gates whose discriminator IS `shutil.which`. Each must be shut when `which`
#: finds nothing and open when it reports a path. Measured, not hand-listed.
WHICH_GATES = (
    ("test_bcd_synth", "_HAVE_SIM"),
    ("test_cvdp_gate", "_HAS_IVERILOG"),
    ("test_cvdp_gate", "_HAS_YOSYS"),
    ("test_cvdp_gate_multifile_split", "_HAS_TOOLCHAIN"),
    ("test_cvdp_gate_selfverify_wiring", "_HAVE_EDA"),
    ("test_cvdp_gate_selfverify_wiring", "_HAVE_IVERILOG"),
    ("test_cvdp_gate_selfverify_wiring", "_HAVE_YOSYS"),
    ("test_cvdp_gate_toolpath_must_not_disable_synth_smoke", "_HAS_TOOLS"),
    ("test_determinism_gates_promoted_to_phase2", "_HAS_IVERILOG"),
    ("test_dff_primitive_synth", "_HAVE_IVERILOG"),
    ("test_gate_directed_rtl_repair", "_HAS_IVERILOG"),
    ("test_general_synth", "_HAVE_IV"),
    ("test_hamming_synth", "_HAS_IVERILOG"),
    ("test_issue186_p2_regmap_transaction_oracle", "_HAVE_IVERILOG"),
    ("test_issue716_intended_transparent_latch_emit", "_HAS_AB"),
    ("test_issue716_intended_transparent_latch_emit", "_HAS_VERILATOR"),
    ("test_kmap_truth_table_oracle_check", "_HAS_EDA"),
    ("test_mbist_wrapper_gen", "_HAS_IVERILOG"),
    ("test_mux_compare_synth", "_HAS_IVERILOG"),
    ("test_organic_20260722_chip_top_power_pin_connect_guard", "_HAS_IVERILOG"),
    ("test_prompt_example_selftest", "_HAVE_IVERILOG"),
    ("test_ramp_waveform_oracle_check", "_HAS_IVERILOG"),
    ("test_round15_rs232_clear_control", "_HAVE_IVERILOG"),
    ("test_round16_latency_clear_prefix_localparam", "_HAVE_TOOLS"),
    ("test_round17_latency_inclusive_origin", "_HAVE_IVERILOG"),
    ("test_rtl_transitive_cone", "_HAS_IVERILOG"),
    ("test_rtl_transitive_cone", "_HAS_VVP"),
    ("test_rtllm_tier_pipeline", "_HAVE_IV"),
    ("test_serial_parallel_mul_synth", "_HAVE_IVERILOG"),
    ("test_shapec_emit_blocking_rules", "_HAS_IVERILOG"),
    ("test_table_lut_synth", "_HAVE_SIM"),
    ("test_v0_2_43_emit_blocking_port_rules", "_HAS_IVERILOG"),
    ("test_v0_2_46_transcripts_ladder_canonical", "_HAVE_TOOLS"),
    ("test_v0_2_50_msbfirst_direction_rule", "_HAS_IVERILOG"),
    ("test_v0_2_53_moore_output_reset_gated", "_HAS_IVERILOG"),
    ("test_v0_3_26_issue530_hygiene_prefixed_reset_mem_array", "_HAS_IVERILOG"),
    ("test_v0_3_27_issue533_fix_compile_neutrality", "_HAS_IVERILOG"),
    ("test_v1_0_23_issue626_cvdp_gate_defence_emit", "_HAS_IVERILOG"),
    ("test_v1_0_26_issue629_tb_reconcile_rtl_surface", "_HAS_IVERILOG"),
    ("test_v1_0_36_issue643_soc_wrapper_tb_compile", "_HAS_IVERILOG"),
    ("test_v1_0_37_issue645_use_power_pins_tb_consistency", "_HAS_IVERILOG"),
    ("test_v1_0_48_issue678_shapeb_export_preserves_variant_alias_wrapper", "_HAVE_IVERILOG"),
    ("test_v1_0_50_issue680_cvdp_gate_emit_format_normalize", "_HAS_IVERILOG"),
    ("test_v1_0_50_issue680_cvdp_gate_emit_format_normalize", "_HAS_TOOLS"),
    ("test_v1_0_50_issue680_cvdp_gate_emit_format_normalize", "_HAS_YOSYS"),
    ("test_v1_0_51_issue683_synth_top_graph_root_fallback", "_HAVE_YOSYS"),
    ("test_v1_0_53_issue688_harness_exact_selfverify", "_HAS_AB"),
    ("test_v1_0_53_issue688_harness_exact_selfverify", "_HAS_ABC"),
    ("test_v1_0_53_issue688_harness_exact_selfverify", "_HAS_IVERILOG"),
    ("test_v1_0_53_issue688_harness_exact_selfverify", "_HAS_VERILATOR"),
    ("test_v1_0_53_issue688_harness_exact_selfverify", "_HAS_VVP"),
    ("test_v1_0_63_issue700_diff_verify_harness", "_HAVE_IVERILOG"),
    ("test_v1_0_64_issue705_latency_conformance", "_HAVE_IVERILOG"),
    ("test_v1_0_66_issue707_shapeb_port_reorder", "_HAS_IVERILOG"),
    ("test_v1_0_68_issue707r2_shapeb_tb_inferred_order", "_HAS_IVERILOG"),
    ("test_v1_0_71_issue707r3_scoreside_port_permutation", "_HAS_IVERILOG"),
    ("test_v1_0_75_issue717_tb_vcs_construct_remediate", "_HAVE_IV"),
    ("test_v1_0_78_issue728_spec_example_smoke_tb", "_HAVE_IVERILOG"),
    ("test_v1_0_78_issue729_ppa_area_threshold", "_HAVE_IVERILOG"),
    ("test_v1_0_80_issue738_regmap_indirection", "_HAVE_IVERILOG"),
    ("test_v1_0_80_issue742_shapeb_binding_contracts", "_HAS_IVERILOG"),
    ("test_v1_0_83_issue518r2_colon_form_arstn", "_HAS_IVERILOG"),
    ("test_v1_0_83_issue742r2_apply_order_inline_comment", "_HAS_IVERILOG"),
    ("test_v1_0_83_issue755_latency_param_clear_multifile", "_HAVE_IVERILOG"),
    ("test_v1_0_85_issue767_unpacked_array_tb", "_HAVE_IV"),
    ("test_v1_0_87_issue770r2_latency_arbiter_onehot", "_HAVE_IVERILOG"),
    ("test_v1_0_93_issue784_emit_assert_discriminators", "_HAVE_TOOLS"),
    ("test_v1_1_1_issue787_latency_conformance_multibit_datapath", "_HAVE_IVERILOG"),
    ("test_v1_1_26_sync_reset_next_state_redundant_gate", "_HAS_IVERILOG"),
    ("test_v1_1_46_pr42_emit_normalizer_hardening", "_HAS_TOOLCHAIN"),
    ("test_v1_1_60_combdly_blkseq_style_suppress", "_HAS_VERILATOR"),
    ("test_v1_1_61_lint_advisory_iverilog_scored", "_HAS_IVERILOG"),
    ("test_v1_1_61_lint_advisory_iverilog_scored", "_HAS_VERILATOR"),
    ("test_v1_1_62_fsm_next_state_oracle", "_HAS_IVERILOG"),
    ("test_v1_1_62_oracle_table_synth", "_HAS_IVERILOG"),
    ("test_v1_1_63_full_moore_fsm_synth", "_HAVE_TOOLS"),
    ("test_v1_1_64_fsm_tabular_format", "_HAVE_TOOLS"),
    ("test_v1_1_65_ff_and_comb_state_synth", "_HAVE_TOOLS"),
    ("test_v1_1_76_behavioral_fsm", "_HAVE_IVERILOG"),
    ("test_v1_1_76_encoder_decoder", "_HAVE_IVERILOG"),
    ("test_v1_1_76_mealy_sequence", "_HAVE_TOOLS"),
    ("test_v1_1_76_nextstate_misc", "_HAS_IVERILOG"),
    ("test_v1_1_76_waveform_ext", "_HAVE_TOOLS"),
    ("test_v1_1_83_new_canonicals", "_HAVE_IV"),
    ("test_v1_1_84_arith_prose_fold", "_HAVE_IV"),
    ("test_v1_1_85_fsm_detector_fold", "_HAVE_IV"),
    ("test_v1_1_85_seq_mult_latency", "_HAVE_IV"),
    ("test_v1_3_79_tbgen_dut_output_clk_reset", "_HAS_IVERILOG"),
    ("test_verilator_timing_fallback_check", "_HAVE_VERILATOR"),
    ("test_verilog_selfcheck_lint", "_HAVE_VERILATOR"),
    ("test_verilogeval_human_tier1_solvers", "_HAVE_IVERILOG"),
    ("test_verilogeval_human_tier_pipeline", "_HAVE_IVERILOG"),
    ("test_verilogeval_tier_pipeline", "_HAVE_IVERILOG"),
    ("test_waveform_table_conformance", "_HAVE_IVERILOG"),
    ("test_worked_example_sequence_oracle_check", "_HAS_IVERILOG"),
)

#: Gates `shutil.which` cannot decide, each with the discriminator that DOES
#: decide it. Every entry is asserted to be genuinely which-insensitive below,
#: so this tuple cannot be used to park a broken tool gate.
NOT_WHICH_GATES = (
    ("test_dff_primitive_synth", "_HAVE_DATASET", "corpus dir"),
    ("test_general_synth", "_HAVE_DS", "corpus dir"),
    ("test_l4_systemrdl_export", "_HAVE_RDL", "package import"),
    ("test_rtllm_tier_pipeline", "_HAVE_DS", "corpus dir"),
    ("test_v1_0_78_issue729_ppa_area_threshold", "_HAVE_CONTAINER", "docker probe"),
    ("test_v1_0_80_issue739_ppa_unreachable_target_escape", "_HAVE_CONTAINER", "docker probe"),
    ("test_v1_0_83_issue756_ppa_disjunctive_clauses", "_HAVE_CONTAINER", "docker probe"),
    ("test_v1_0_85_issue768_ppa_reachability_submission_independent", "_HAVE_CONTAINER", "docker probe"),
    ("test_v1_0_85_issue769_ppa_generic_meets_target", "_HAVE_CONTAINER", "docker probe"),
    ("test_v1_1_76_encoder_decoder", "_HAVE_DS", "corpus dir"),
    ("test_v1_1_76_waveform_ext", "_HAVE_DS", "corpus dir"),
    ("test_verilogeval_human_tier1_solvers", "_HAVE_DATASET", "corpus dir"),
    ("test_verilogeval_human_tier_pipeline", "_HAVE_DATASET", "corpus dir"),
    ("test_verilogeval_tier_pipeline", "_HAVE_DATASET", "corpus dir"),
)

_NOT_WHICH_PAIRS = tuple((m, c) for m, c, _ in NOT_WHICH_GATES)

#: Constants that match the prefix but are NOT gates. Widening the key to
#: `_HAS_` swept in two module-level constants whose names collide with the
#: convention and whose values are not booleans at all — a fixture blob and an
#: argv list. They are recorded with the value TYPE that disqualifies them, and
#: `test_a_declared_non_gate_is_really_not_a_boolean` checks each one, so this
#: tuple cannot become a place to park a gate that has started failing.
NOT_A_GATE = (
    ("test_signoff_cell_aware_feol_cfg", "_HAS_GEOMETRY", "str: fixture report text"),
    ("test_verilator_coverage_measure", "_HAS_TOOLCHAIN", "list: argv fragment"),
)

_NOT_A_GATE_PAIRS = tuple((m, c) for m, c, _ in NOT_A_GATE)


@pytest.mark.parametrize("modname,const", WHICH_GATES)
def test_the_gate_is_CLOSED_when_the_tool_is_absent(modname, const):
    """Baseline: with `which` finding nothing, the gate must be shut."""
    assert _probe(modname, const, _ABSENT) is False, (
        f"{modname}.{const} is True while shutil.which finds nothing")


@pytest.mark.parametrize("modname,const", WHICH_GATES)
def test_the_gate_OPENS_when_the_tool_is_present(modname, const):
    """The one that matters: a permanent skip would pass the test above too.

    With `which` reporting a path for every tool the constant must be True, so
    the guard is a no-op and the real assertions run. If this fails, the gate
    has become unconditional and the module is silenced on every host.
    """
    assert _probe(modname, const, _PRESENT) is True, (
        f"{modname}.{const} is False even though shutil.which reports the tool "
        f"present — the skip is unconditional and the module is silenced")


@pytest.mark.parametrize("modname,const,why", NOT_WHICH_GATES)
def test_a_declared_non_which_gate_is_really_not_which_keyed(modname, const, why):
    """The guard ON the exclusion list.

    `NOT_WHICH_GATES` exists because `which` is the wrong probe for a corpus
    directory, a package import or a live container. That is a real reason —
    and it is also exactly the shape of an excuse, so it has to be checked. A
    genuine non-which gate reads the SAME under both fakes. A tool gate parked
    here to make a failure go away does not, and fails here.
    """
    absent = _probe(modname, const, _ABSENT)
    present = _probe(modname, const, _PRESENT)
    assert absent == present, (
        f"{modname}.{const} is declared not-which-keyed ({why}) but it CHANGED "
        f"{absent!r} -> {present!r} when shutil.which was patched. It is a "
        f"`which` gate: move it to WHICH_GATES, where both directions are proved.")


@pytest.mark.parametrize("modname,const,why", NOT_A_GATE)
def test_a_declared_non_gate_is_really_not_a_boolean(modname, const, why):
    """The guard ON `NOT_A_GATE`.

    A constant excluded for "not being a gate" must not be a bool. A real tool
    gate is True or False, so if one is moved here to stop it being probed —
    the obvious way to silence a gate that has started failing — this fails.
    The reason string carries the type that disqualifies it, and the type is
    re-derived here rather than trusted.
    """
    value = _probe(modname, const, _ABSENT)
    assert not isinstance(value, bool), (
        f"{modname}.{const} is declared a non-gate ({why}) but it IS a bool "
        f"({value!r}). Booleans are gates: move it to WHICH_GATES, or to "
        f"NOT_WHICH_GATES if `which` is not its discriminator.")
    assert type(value).__name__ in why, (
        f"{modname}.{const} is recorded as `{why}` but measures as "
        f"{type(value).__name__}. The recorded type must match the tree.")


def test_the_probe_reaches_a_discriminator_that_lives_in_a_HELPER_module():
    """PAIRED GUARD for the helper reload itself (#1386, against #1311).

    `test_cvdp_gate._HAS_YOSYS` is DERIVED from `_sim_tools.MISSING`, which is
    resolved once at that helper's import. So the obvious probe — reload the
    gated module under a patched `which` — re-runs a `from _sim_tools import`
    against a cache and cannot move the gate at all.

    This proves the difference in both directions on the real module, so the
    helper reload cannot be dropped as an unexplained line: the old probe is
    reconstructed here and required to be STUCK, and the probe this file uses
    is required to move.

    It names `test_cvdp_gate` / `_sim_tools` deliberately — that is the measured
    instance, and if #1311's indirection is ever undone this control fails
    loudly rather than quietly proving nothing.
    """
    assert _WHICH_HELPERS, (
        "no `which`-probing helper found in this directory — every gate whose "
        "discriminator lives one module up would be probed through a cache")
    assert "_sim_tools" in _WHICH_HELPERS, (
        "the helper that owns the cvdp gates' discriminator is not in the "
        f"reload set {_WHICH_HELPERS}")

    real = shutil.which
    shutil.which = _ABSENT
    try:                       # pin the helper cache at "nothing on PATH"
        _reload("_sim_tools")
        _reload("test_cvdp_gate")
    finally:
        shutil.which = real

    # THE OLD PROBE, reconstructed: reload the gated module only, with `which`
    # reporting the tool present. The helper cache is stale, so nothing moves.
    shutil.which = _PRESENT
    try:
        stuck = getattr(_reload("test_cvdp_gate"), "_HAS_YOSYS")
    finally:
        shutil.which = real
    assert stuck is False, (
        "reloading only the gated module moved an indirect gate — this control "
        "no longer demonstrates what the helper reload is for; re-derive it")

    # THE PROBE THIS FILE USES: it reaches `_sim_tools`, so the gate moves.
    assert _probe("test_cvdp_gate", "_HAS_YOSYS", _PRESENT) is True
    assert _probe("test_cvdp_gate", "_HAS_YOSYS", _ABSENT) is False


def test_the_probe_leaves_the_helpers_telling_the_truth():
    """A probe that walks out with a faked `_sim_tools` hands the rest of the
    session a module that believes yosys is installed — and the 38 cvdp tests
    it guards would then run against a refusal instead of skipping.

    Re-derived from `shutil.which` here rather than remembered, so this is a
    statement about THIS host and not about a recorded expectation.
    """
    truth = tuple(t for t in ("iverilog", "yosys") if shutil.which(t) is None)
    for fake in (_PRESENT, _ABSENT):
        _probe("test_cvdp_gate", "_HAS_YOSYS", fake)
        import _sim_tools
        assert _sim_tools.MISSING == truth, (
            f"after probing with {fake!r} the shared helper reports "
            f"MISSING={_sim_tools.MISSING!r}, but this host measures {truth!r}")


def test_every_defined_gate_is_registered():
    """The register must name every `_HAVE_*` in the directory, in one list or
    the other.

    Otherwise a module gated tomorrow gets a skip with no proof the skip can
    open — the register and the population drifting apart, which is the defect
    this repo removes everywhere else. Keyed on the pattern, so a TWELFTH
    spelling is covered the day it appears without an edit here.
    """
    registered = (set(WHICH_GATES) | set(_NOT_WHICH_PAIRS)
                  | set(_NOT_A_GATE_PAIRS))
    found = _scan()
    assert found == registered, (
        f"defined but not registered: {sorted(found - registered)}; "
        f"registered but no longer defined: {sorted(registered - found)}")


def test_the_register_is_not_checking_an_empty_population():
    """A register that scanned nothing has not passed.

    If the glob or the regex ever stops matching, every test above turns into a
    silent no-op and this file would go green over zero gates — the same
    silence it exists to prevent.
    """
    found = _scan()
    assert len(found) >= 90, (
        f"only {len(found)} `_HA(VE|S)_*` definitions found; 108 were present "
        f"when this was last re-measured. The scan is broken, not the tree.")
    assert len(WHICH_GATES) >= 75, (
        f"only {len(WHICH_GATES)} which-keyed gates registered; 92 when "
        f"re-measured on ab5a23a28")
