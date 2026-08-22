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

    WHICH_GATES      96    shut under which->None, open under which->path
    NOT_WHICH_GATES  14    corpus dir, package import, two-stage docker probe
    NOT_A_GATE        2    not booleans; not gates at all
                    ---
                    112    every `_HA(VE|S)_*` definition in this directory

(re-measured on `1adbf3444`; 92/14/2 = 108 when the table was first written.
No test trusts these three numbers — `test_every_defined_gate_is_registered`
re-derives them from the tree, and nothing below asserts a remembered count.)

What shells out, and how far: `_HAVE_CONTAINER` is the one registered entry
whose probe attempts a real subprocess, and while the exclusion guard is
running even that is pinned shut (below). The only unpinned subprocess in this
file is the restore reload at the end of every probe, and the control module's
`sys.executable -c ""` — both bounded well under the harness timeout.

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

A TWO-STAGE GATE MOVES WITH `which` WITHOUT BEING `which`-KEYED (#1385)
──────────────────────────────────────────────────────────────────────
The guard on `NOT_WHICH_GATES` asked one question — does the constant read the
SAME under both fakes — and that question is not decidable on every host. The
five `_HAVE_CONTAINER` entries probe in two stages:

    if shutil.which("docker") is None: return False     # 1: NECESSARY
    cp = subprocess.run(["docker", "inspect", ..., "vibeic-eda"], ...)
    return cp.returncode == 0 and cp.stdout.strip() == "true"   # 2: DECIDING

`which` is necessary but not sufficient, so what the gate reads under a fake
`which` depends on stage 2 — i.e. on the host:

    host WITH a running `vibeic-eda`   absent False, present True   DIFFER -> RED
    host WITHOUT one                   absent False, present False  same   -> green

Measured, same tree, one variable — a `docker` earlier on `PATH` that exits 1:

    real host (docker present, `vibeic-eda` up)   5 failed, 207 passed
    identical tree, `docker` -> exit 1              0 failed, 212 passed

The advice the failure printed — "move it to WHICH_GATES" — inverts the
breakage rather than fixing it: `WHICH_GATES` proves the gate OPENS under a
fake `which`, which is true only while the container happens to be running.

The fix is to make `which` the ONLY varying input: the exclusion guard now
pins stage 2 to a fixed failure (`subprocess.run` -> returncode 1) for the
duration of the probe. The discrimination the guard exists for survives intact,
because a `which`-keyed gate has no stage 2 to pin:

    genuine two-stage gate, stage 2 pinned    False / False   same   PASS
    a `which` gate parked here as an excuse   False / True    differ FAIL

Both rows are PROVED, not asserted, by
`test_the_stage2_pin_still_catches_a_which_gate_parked_here`, which builds one
module of each shape and shows the second still reddens under the pin — and
shows the first is host-dependent WITHOUT the pin, using a stage 2 that
succeeds on any host rather than a docker that might not be there.

THE POPULATION FLOOR IS RE-DERIVED, NOT REMEMBERED (#1385)
──────────────────────────────────────────────────────────
`test_the_register_is_not_checking_an_empty_population` used two hand-written
constants, and both had drifted below the tree they guard:

    assert len(found) >= 90          # true count 112; the message said 108
    assert len(WHICH_GATES) >= 75    # true count  96; the message said  92

A floor that only moves when a human remembers, guarding a population that
moves whenever a module gains a tool gate, drifts by construction — `>= 75`
would have tolerated the silent loss of 21 registrations. Every number in that
test is now re-derived from the tree on each run: a SECOND, independent scan
for gating USES (`not _HA(VE|S)_*`) cross-checks the definition scan, each
holds the other up, and the `WHICH_GATES` floor is a fraction of the live
scan rather than a constant.
"""
from __future__ import annotations

import importlib
import re
import shutil
import subprocess
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

#: A gating USE of such a constant — `skipif(not _HAVE_X, ...)` and the in-body
#: `if not _HAVE_X: pytest.skip(...)` alike. Deliberately a DIFFERENT expression
#: over the same tree from `_DEFN`, so the two scans can hold each other up:
#: whichever one breaks, the other still sees the population and says so. It is
#: used only for counting, never as the register key — the definition is what
#: the assertions read back, and a use-keyed register would have been narrower
#: (see the CORRECTION note above).
_USE = re.compile(r"\bnot\s+(_HA(?:VE|S)_[A-Z0-9_]+)\b")

_SELF = Path(__file__).stem


def _scan(pattern: re.Pattern = _DEFN) -> set:
    """Every (module, constant) pair `pattern` finds in this directory."""
    found = set()
    for p in sorted(_TESTS.glob("test_*.py")):
        if p.stem == _SELF:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for const in set(pattern.findall(text)):
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


def _stage2_always_fails(args, *_a, **kw):
    """`subprocess.run` pinned to one host-independent answer: it FAILED.

    A two-stage probe (`which` the binary, then RUN it) reads differently on a
    host where stage 2 succeeds and on one where it does not — so a check that
    varies `which` alone is measuring the host, not the gate. Pinning stage 2
    to a fixed failure removes that second input; `which` is then the only
    thing that moves, which is what the exclusion guard means to ask about.

    Faithful to the real signature where it matters: `text=`/`encoding=` decide
    whether the empty streams are `str` or `bytes`, and `check=True` still
    raises, so a caller that relies on either is not handed a shape the real
    `subprocess.run` would never return.
    """
    textmode = bool(kw.get("text") or kw.get("universal_newlines")
                    or kw.get("encoding") or kw.get("errors"))
    empty = "" if textmode else b""
    if kw.get("check"):
        raise subprocess.CalledProcessError(1, args, output=empty, stderr=empty)
    return subprocess.CompletedProcess(args=args, returncode=1,
                                       stdout=empty, stderr=empty)


def _probe(modname: str, const: str, fake, *, pin_stage2: bool = False):
    """`modname.const` as it reads when `shutil.which` behaves like `fake`.

    Reloads the helpers that own an INDIRECT discriminator before the gated
    module, so a gate derived from `_sim_tools.MISSING` moves with the fake
    exactly as a gate that calls `which` itself does.

    With `pin_stage2`, `subprocess.run` is also held at a fixed failure for the
    duration, so a gate that shells out after `which` cannot make the answer
    depend on this host. Off by default: `WHICH_GATES` entries are declared
    single-stage, and pinning there would hide a gate that had grown a second
    stage instead of exposing it.

    Then puts everything back — the patched function AND every module it
    reloaded. A probe that walked out leaving `_sim_tools.MISSING = ()` would
    hand the rest of the session a module that believes yosys is installed,
    and the 38 cvdp tests it guards would run and fail against a refusal. That
    is not hypothetical ordering-paranoia: before the restore existed, whether
    the cvdp gates read True or False depended on which parametrised test ran
    FIRST, because the first `import_module` under a fake also imported the
    helper under that fake and froze it there.
    """
    real_which, real_run = shutil.which, subprocess.run
    shutil.which = fake
    if pin_stage2:
        subprocess.run = _stage2_always_fails
    try:
        for helper in _WHICH_HELPERS:
            _reload(helper)
        return getattr(_reload(modname), const)
    finally:
        shutil.which = real_which
        subprocess.run = real_run
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
    ("test_issue1437_absent_iverilog_reaches_a_declared_verdict", "_HAS_IVERILOG"),
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

    STAGE 2 IS PINNED (#1385). A live-container probe is one of the three
    reasons named above, and it runs the binary AFTER finding it — so on a host
    where that run succeeds the gate moves with `which` while still not being
    `which`-keyed, and this guard reddened for the host rather than for the
    tree (5 failed here, 0 on a host without the container, same tree). Holding
    `subprocess.run` at a fixed failure leaves `which` as the only varying
    input. What the guard discriminates is unchanged: a real `which` gate has
    no second stage to pin, so it still reads False -> True and still fails.
    """
    absent = _probe(modname, const, _ABSENT, pin_stage2=True)
    present = _probe(modname, const, _PRESENT, pin_stage2=True)
    assert absent == present, (
        f"{modname}.{const} is declared not-which-keyed ({why}) but with every "
        f"subprocess pinned to a failure it still CHANGED {absent!r} -> "
        f"{present!r} when shutil.which was patched. Nothing but `which` was "
        f"allowed to move, so `which` alone decides it: move it to "
        f"WHICH_GATES, where both directions are proved.")


#: Two one-file modules, written to a tmp dir (never into this directory — the
#: scan globs it, and the suite write-guard watches it) to exercise the stage-2
#: pin against both shapes it has to tell apart. The two-stage one deliberately
#: does NOT depend on docker: its stage 2 runs this interpreter with an empty
#: program, which succeeds on any host that can run this test at all, so the
#: host-dependence it demonstrates is reproducible everywhere.
_CTL_TWO_STAGE = '''\
import shutil
import subprocess
import sys


def _up() -> bool:
    if shutil.which("docker") is None:
        return False                                  # stage 1 — necessary
    cp = subprocess.run([sys.executable, "-c", ""],
                        capture_output=True, text=True, timeout=30)
    return cp.returncode == 0                         # stage 2 — deciding


_HAVE_CTL = _up()
'''

_CTL_WHICH_ONLY = '''\
import shutil

_HAVE_CTL = shutil.which("iverilog") is not None
'''


def test_the_stage2_pin_still_catches_a_which_gate_parked_here(tmp_path):
    """PAIRED GUARD for the stage-2 pin itself (#1385).

    The pin exists to stop `test_a_declared_non_which_gate_is_really_not_which_keyed`
    reddening for the host. A pin that also stopped it reddening for a real
    `which` gate would be worse than the redness, so both halves are proved
    here on modules built for the purpose:

      * WITHOUT the pin a genuine two-stage gate reads False -> True, i.e. it
        would FAIL the exclusion guard — the host-dependence, reproduced with
        no docker involved;
      * WITH the pin the same gate reads False -> False and PASSES;
      * WITH the pin a pure `which` gate still reads False -> True and still
        FAILS. The pin removes one input; it does not remove the question.
    """
    two_stage = tmp_path / "_i1385_ctl_two_stage.py"
    which_only = tmp_path / "_i1385_ctl_which_only.py"
    two_stage.write_text(_CTL_TWO_STAGE, encoding="utf-8")
    which_only.write_text(_CTL_WHICH_ONLY, encoding="utf-8")

    sys.path.insert(0, str(tmp_path))
    try:
        assert _probe(two_stage.stem, "_HAVE_CTL", _ABSENT) is False
        assert _probe(two_stage.stem, "_HAVE_CTL", _PRESENT) is True, (
            "the two-stage control was supposed to be which-SENSITIVE with its "
            "second stage free to succeed; if it is not, this test no longer "
            "demonstrates the host-dependence the pin was added for")

        assert _probe(two_stage.stem, "_HAVE_CTL", _ABSENT,
                      pin_stage2=True) is False
        assert _probe(two_stage.stem, "_HAVE_CTL", _PRESENT,
                      pin_stage2=True) is False, (
            "with subprocess pinned to a failure the two-stage control still "
            "opened — the pin did not reach stage 2, so the exclusion guard is "
            "still measuring the host")

        assert _probe(which_only.stem, "_HAVE_CTL", _ABSENT,
                      pin_stage2=True) is False
        assert _probe(which_only.stem, "_HAVE_CTL", _PRESENT,
                      pin_stage2=True) is True, (
            "a pure `which` gate no longer moves under the pin: the pin has "
            "blinded the exclusion guard, and NOT_WHICH_GATES has become the "
            "escape hatch it was written not to be")
    finally:
        sys.path.remove(str(tmp_path))
        for stem in (two_stage.stem, which_only.stem):
            sys.modules.pop(stem, None)


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


def _registered() -> set:
    """Every (module, constant) pair this file claims to account for."""
    return set(WHICH_GATES) | set(_NOT_WHICH_PAIRS) | set(_NOT_A_GATE_PAIRS)


def test_every_defined_gate_is_registered():
    """The register must name every `_HAVE_*` in the directory, in one list or
    the other.

    Otherwise a module gated tomorrow gets a skip with no proof the skip can
    open — the register and the population drifting apart, which is the defect
    this repo removes everywhere else. Keyed on the pattern, so a TWELFTH
    spelling is covered the day it appears without an edit here.
    """
    registered = _registered()
    found = _scan()
    assert found == registered, (
        f"defined but not registered: {sorted(found - registered)}; "
        f"registered but no longer defined: {sorted(registered - found)}")


def test_the_register_is_not_checking_an_empty_population():
    """A register that scanned nothing has not passed.

    If the glob or the regex ever stops matching, every test above turns into a
    silent no-op and this file would go green over zero gates — the same
    silence it exists to prevent.

    EVERY BOUND HERE IS RE-DERIVED, NOT REMEMBERED (#1385). The two it replaces
    were hand-written and had both drifted below the tree they guard —
    `>= 90` against 112 definitions, `>= 75` against 96 which-keyed gates, each
    printing a different, also-stale number in its own failure message. A
    constant floor guarding a population that grows whenever a module gains a
    tool gate drifts by construction: `>= 75` would have tolerated the silent
    loss of 21 registrations before objecting.

    So the definition scan and an INDEPENDENT scan for gating uses hold each
    other up — whichever expression breaks, the other still sees the population
    — and the `WHICH_GATES` bound is a fraction of the live scan. Nothing below
    needs a human to remember a number.

    What this deliberately does not cover: both regexes breaking in the same
    change AND the register being deleted to match. That is a hundred-line
    diff, not a drift, and `test_every_defined_gate_is_registered` is the guard
    that makes it visible.
    """
    found = _scan()
    gated = _scan(_USE)
    registered = _registered()

    assert len(gated) >= len(registered) // 2, (
        f"the independent scan for `not _HA(VE|S)_*` gating expressions found "
        f"{len(gated)} uses against a register of {len(registered)} pairs. It "
        f"is the cross-check on the definition scan; if it has gone quiet, it "
        f"is broken and cannot vouch for anything.")

    assert len(found) >= len(gated), (
        f"the definition scan found {len(found)} `_HA(VE|S)_*` definitions "
        f"while {len(gated)} are being GATED on by an independent scan of the "
        f"same tree. A gate cannot be used without being defined, so the "
        f"definition scan is broken, not the tree — and every parametrised "
        f"test above has silently stopped covering the difference.")

    assert len(found) >= len(registered), (
        f"the definition scan found {len(found)} definitions but this file "
        f"registers {len(registered)}. The register is edited by hand and the "
        f"scan is not, so a scan that sees FEWER gates than are written down "
        f"is the thing that broke.")

    assert len(WHICH_GATES) * 4 >= len(found) * 3, (
        f"only {len(WHICH_GATES)} of {len(found)} definitions are in "
        f"WHICH_GATES — the one list that proves a gate can OPEN. The other "
        f"two are reasoned carve-outs; once they hold more than a quarter of "
        f"the population this register has become a way of not proving things.")
