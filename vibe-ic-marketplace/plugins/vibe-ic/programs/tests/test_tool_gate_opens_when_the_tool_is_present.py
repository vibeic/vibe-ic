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
`24ff95307`, that is one spelling out of eleven in use:

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

    @pytest.mark.skipif(not _HAVE_X, ...)      45 pairs
    if not _HAVE_X: pytest.skip(...)            8 pairs   <- in-body

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

MEASURED COST, this host: 59 pairs, 118 module reloads, 1.67 s total
(0.028 s per pair). Nothing here shells out; `_HAVE_CONTAINER` is the one entry
whose probe attempts a real subprocess, and it fails closed immediately.
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
_DEFN = re.compile(r"^(_HAVE_[A-Z0-9_]+)\s*=", re.M)

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


def _reload_with_which(modname: str, fake):
    """Reload `modname` with `shutil.which` replaced, then put it back."""
    real = shutil.which
    shutil.which = fake
    try:
        return importlib.reload(importlib.import_module(modname))
    finally:
        shutil.which = real


_ABSENT = lambda *_a, **_k: None                       # noqa: E731
_PRESENT = lambda name, *_a, **_k: f"/usr/bin/{name}"  # noqa: E731

#: Gates whose discriminator IS `shutil.which`. Each must be shut when `which`
#: finds nothing and open when it reports a path. Measured, not hand-listed.
WHICH_GATES = (
    ("test_bcd_synth", "_HAVE_SIM"),
    ("test_cvdp_gate_selfverify_wiring", "_HAVE_EDA"),
    ("test_cvdp_gate_selfverify_wiring", "_HAVE_IVERILOG"),
    ("test_cvdp_gate_selfverify_wiring", "_HAVE_YOSYS"),
    ("test_dff_primitive_synth", "_HAVE_IVERILOG"),
    ("test_general_synth", "_HAVE_IV"),
    ("test_issue186_p2_regmap_transaction_oracle", "_HAVE_IVERILOG"),
    ("test_prompt_example_selftest", "_HAVE_IVERILOG"),
    ("test_round15_rs232_clear_control", "_HAVE_IVERILOG"),
    ("test_round16_latency_clear_prefix_localparam", "_HAVE_TOOLS"),
    ("test_round17_latency_inclusive_origin", "_HAVE_IVERILOG"),
    ("test_rtllm_tier_pipeline", "_HAVE_IV"),
    ("test_serial_parallel_mul_synth", "_HAVE_IVERILOG"),
    ("test_table_lut_synth", "_HAVE_SIM"),
    ("test_v0_2_46_transcripts_ladder_canonical", "_HAVE_TOOLS"),
    ("test_v1_0_48_issue678_shapeb_export_preserves_variant_alias_wrapper", "_HAVE_IVERILOG"),
    ("test_v1_0_51_issue683_synth_top_graph_root_fallback", "_HAVE_YOSYS"),
    ("test_v1_0_63_issue700_diff_verify_harness", "_HAVE_IVERILOG"),
    ("test_v1_0_64_issue705_latency_conformance", "_HAVE_IVERILOG"),
    ("test_v1_0_75_issue717_tb_vcs_construct_remediate", "_HAVE_IV"),
    ("test_v1_0_78_issue728_spec_example_smoke_tb", "_HAVE_IVERILOG"),
    ("test_v1_0_78_issue729_ppa_area_threshold", "_HAVE_IVERILOG"),
    ("test_v1_0_80_issue738_regmap_indirection", "_HAVE_IVERILOG"),
    ("test_v1_0_83_issue755_latency_param_clear_multifile", "_HAVE_IVERILOG"),
    ("test_v1_0_85_issue767_unpacked_array_tb", "_HAVE_IV"),
    ("test_v1_0_87_issue770r2_latency_arbiter_onehot", "_HAVE_IVERILOG"),
    ("test_v1_0_93_issue784_emit_assert_discriminators", "_HAVE_TOOLS"),
    ("test_v1_1_1_issue787_latency_conformance_multibit_datapath", "_HAVE_IVERILOG"),
    ("test_v1_1_63_full_moore_fsm_synth", "_HAVE_TOOLS"),
    ("test_v1_1_64_fsm_tabular_format", "_HAVE_TOOLS"),
    ("test_v1_1_65_ff_and_comb_state_synth", "_HAVE_TOOLS"),
    ("test_v1_1_76_behavioral_fsm", "_HAVE_IVERILOG"),
    ("test_v1_1_76_encoder_decoder", "_HAVE_IVERILOG"),
    ("test_v1_1_76_mealy_sequence", "_HAVE_TOOLS"),
    ("test_v1_1_76_waveform_ext", "_HAVE_TOOLS"),
    ("test_v1_1_83_new_canonicals", "_HAVE_IV"),
    ("test_v1_1_84_arith_prose_fold", "_HAVE_IV"),
    ("test_v1_1_85_fsm_detector_fold", "_HAVE_IV"),
    ("test_v1_1_85_seq_mult_latency", "_HAVE_IV"),
    ("test_verilator_timing_fallback_check", "_HAVE_VERILATOR"),
    ("test_verilog_selfcheck_lint", "_HAVE_VERILATOR"),
    ("test_verilogeval_human_tier1_solvers", "_HAVE_IVERILOG"),
    ("test_verilogeval_human_tier_pipeline", "_HAVE_IVERILOG"),
    ("test_verilogeval_tier_pipeline", "_HAVE_IVERILOG"),
    ("test_waveform_table_conformance", "_HAVE_IVERILOG"),
)

#: Gates `shutil.which` cannot decide, each with the discriminator that DOES
#: decide it. Every entry is asserted to be genuinely which-insensitive below,
#: so this tuple cannot be used to park a broken tool gate.
NOT_WHICH_GATES = (
    # corpus on disk — `_DATASET.is_dir()` / `.exists()`; no binary involved
    ("test_dff_primitive_synth", "_HAVE_DATASET", "corpus dir"),
    ("test_verilogeval_human_tier1_solvers", "_HAVE_DATASET", "corpus dir"),
    ("test_verilogeval_human_tier_pipeline", "_HAVE_DATASET", "corpus dir"),
    ("test_verilogeval_tier_pipeline", "_HAVE_DATASET", "corpus dir"),
    # corpus on disk — `_RTLLM_ROOT.is_dir()` / `_DS.is_dir()`
    ("test_general_synth", "_HAVE_DS", "corpus dir"),
    ("test_rtllm_tier_pipeline", "_HAVE_DS", "corpus dir"),
    ("test_v1_1_76_encoder_decoder", "_HAVE_DS", "corpus dir"),
    ("test_v1_1_76_waveform_ext", "_HAVE_DS", "corpus dir"),
    # python package import — `try: import systemrdl`
    ("test_l4_systemrdl_export", "_HAVE_RDL", "package import"),
    # TWO-STAGE probe: `_container_up()` checks `which("docker")` FIRST and
    # then runs a real `docker inspect`. Patching `which` gets past stage one
    # and dies at stage two, so `which` alone can never open it.
    ("test_v1_0_78_issue729_ppa_area_threshold", "_HAVE_CONTAINER", "docker probe"),
    ("test_v1_0_80_issue739_ppa_unreachable_target_escape", "_HAVE_CONTAINER", "docker probe"),
    ("test_v1_0_83_issue756_ppa_disjunctive_clauses", "_HAVE_CONTAINER", "docker probe"),
    ("test_v1_0_85_issue768_ppa_reachability_submission_independent", "_HAVE_CONTAINER", "docker probe"),
    ("test_v1_0_85_issue769_ppa_generic_meets_target", "_HAVE_CONTAINER", "docker probe"),
)

_NOT_WHICH_PAIRS = tuple((m, c) for m, c, _ in NOT_WHICH_GATES)


@pytest.mark.parametrize("modname,const", WHICH_GATES)
def test_the_gate_is_CLOSED_when_the_tool_is_absent(modname, const):
    """Baseline: with `which` finding nothing, the gate must be shut."""
    mod = _reload_with_which(modname, _ABSENT)
    assert getattr(mod, const) is False, (
        f"{modname}.{const} is True while shutil.which finds nothing")


@pytest.mark.parametrize("modname,const", WHICH_GATES)
def test_the_gate_OPENS_when_the_tool_is_present(modname, const):
    """The one that matters: a permanent skip would pass the test above too.

    With `which` reporting a path for every tool the constant must be True, so
    the guard is a no-op and the real assertions run. If this fails, the gate
    has become unconditional and the module is silenced on every host.
    """
    mod = _reload_with_which(modname, _PRESENT)
    assert getattr(mod, const) is True, (
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
    absent = getattr(_reload_with_which(modname, _ABSENT), const)
    present = getattr(_reload_with_which(modname, _PRESENT), const)
    assert absent == present, (
        f"{modname}.{const} is declared not-which-keyed ({why}) but it CHANGED "
        f"{absent!r} -> {present!r} when shutil.which was patched. It is a "
        f"`which` gate: move it to WHICH_GATES, where both directions are proved.")


def test_every_defined_gate_is_registered():
    """The register must name every `_HAVE_*` in the directory, in one list or
    the other.

    Otherwise a module gated tomorrow gets a skip with no proof the skip can
    open — the register and the population drifting apart, which is the defect
    this repo removes everywhere else. Keyed on the pattern, so a TWELFTH
    spelling is covered the day it appears without an edit here.
    """
    registered = set(WHICH_GATES) | set(_NOT_WHICH_PAIRS)
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
    assert len(found) >= 50, (
        f"only {len(found)} `_HAVE_*` definitions found; 59 were present when "
        f"this was written. The scan is broken, not the tree.")
    assert len(WHICH_GATES) >= 40, (
        f"only {len(WHICH_GATES)} which-keyed gates registered; 45 when written")
