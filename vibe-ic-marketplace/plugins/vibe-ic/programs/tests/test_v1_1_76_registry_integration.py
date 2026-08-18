"""v1.1.76 — extraction-completeness wave-2 INTEGRATION invariants.

This pins the "do-the-right-thing" integration decisions (not the per-family unit
behavior, which lives in each test_v1_1_76_<family>.py):

  1. SINGLE SOURCE OF TRUTH — spec_artifact_registry.REGISTRY is the one catalog;
     benchmark/gates_atomic.py delegates to registry.generate() (it no longer keeps
     a second hand-maintained dispatch tuple that drifted).
  2. All 9 wave-2 families are wired and reachable through the registry.
  3. DEDUP — a literal Boolean equation is owned by comb_gate alone (residual no
     longer also fires on it): at most ONE registry generator fires per benchmark
     prompt EXCEPT the documented isomorphic-table overlaps (a complete single-
     output combinational table is legitimately seen as truth_table ≡ karnaugh_map
     ≡ next-state-bit ≡ kmap_sop; first-fire picks one, all host-verified correct).
  4. DETERMINISTIC dispatch on the REAL dataset prompts (skipped if the dataset is
     not present in this environment).
"""
import sys
import glob
import os
from pathlib import Path

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))
import spec_artifact_registry as R          # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DS = str(corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl"))

WAVE2_KEYS = {
    "mealy_fsm_sequence", "fsm_prose", "dff_edge", "counter_popcount",
    "priority_encoder", "vector_ops", "timing_waveform_ext", "comb_gate",
    "residual_combinational",
    # wave-3 (aggressive remainder)
    "arithmetic", "counter_advanced", "serial_protocol_fsm", "nextstate_misc",
    "behavioral_fsm", "comb_advanced",
    # wave-4 (multi-part decomposition of the hardest clusters)
    "sequential_waveform_multibit", "conway_2d", "gshare_predictor",
}

# Prob099_m2014_q6c is a KNOWN dataset defect: the official testbench instantiates
# ports Y2/Y4 that neither the prompt nor the reference declares, so it cannot
# compile against ANY implementation. nextstate_misc emits the correct (ref-
# equivalent) RTL but the problem is unscoreable — excluded from the host-PASS
# accounting, not a solver leak.
KNOWN_DATASET_DEFECTS = {"Prob099_m2014_q6c"}

# documented benign multi-recognition: a complete single-output combinational table
# is isomorphic across these views; first-fire picks one, all host-verified correct.
_ISOMORPHIC_TABLE = {
    "truth_table", "karnaugh_map", "karnaugh_map_sop", "fsm_next_state_bit",
    "comb_state_table", "fsm_prose",
}


def test_all_wave2_families_registered():
    keys = set(R.types())
    missing = WAVE2_KEYS - keys
    assert not missing, f"wave-2 families not wired into registry: {missing}"
    assert len(keys) == len(R.types()), "duplicate registry keys"


def test_gates_atomic_delegates_to_registry():
    # the single-source refactor: gates_atomic must import spec_artifact_registry
    # in its deterministic-synth block and must NOT keep the old hand-maintained
    # ('kmap_grid', _kmsynth)-style dispatch tuple.
    src = (PROG / ".." / "benchmark" / "gates_atomic.py").resolve().read_text()
    assert "spec_artifact_registry" in src
    assert "_reg.generate(" in src
    assert '("kmap_grid", _kmsynth)' not in src   # the drifted second list is gone


def test_residual_no_longer_owns_boolean_equations():
    # dedup: comb_gate owns boolean equations; residual fires ONLY on constant /
    # equality. A literal boolean-equation prompt must NOT be claimed by residual.
    import residual_combinational_synth as _rc
    p = (" - input x\n - input y\n - output z\n\n"
         "The module should implement the boolean function z = (x ^ y) & x.\n")
    assert _rc.synth(p, "TopModule") is None


def test_generate_is_deterministic():
    # generate() must be a pure deterministic function of the text (stable pick).
    p = (" - input clk\n - input reset\n - input in\n - output out\n"
         "Implement the following Moore state machine with two states.\n"
         "The reset state is B and reset is active-high synchronous.\n"
         "  B (out=1) --in=0--> A\n  B (out=1) --in=1--> B\n"
         "  A (out=0) --in=0--> B\n  A (out=0) --in=1--> A\n")
    k1, r1 = R.generate(p, "TopModule")
    k2, r2 = R.generate(p, "TopModule")
    assert k1 == k2 and r1 == r2 and k1 == "fsm_transition_table"


def test_no_unexpected_multifire_on_real_dataset():
    # On the real corpus, the ONLY prompts where >1 generator fires must be the
    # documented isomorphic-table set — never two DISTINCT-family solvers (e.g.
    # comb_gate + residual, or mux + shift). Skips if the dataset is absent.
    files = sorted(glob.glob(_DS + "/*_prompt.txt"))
    if not files:
        import pytest
        pytest.skip("VE-Human dataset not present")
    bad = []
    for f in files:
        txt = open(f, errors="replace").read()
        gens = [a.key for a in R.REGISTRY if a.generate and a.generate(txt, "TopModule")]
        if len(gens) > 1 and not set(gens) <= _ISOMORPHIC_TABLE:
            bad.append((os.path.basename(f), gens))
    assert not bad, f"unexpected cross-family multi-fire: {bad}"


def test_real_dataset_dispatch_spotcheck():
    # a few real prompts must route to their expected wave-2 family (skipped if
    # the dataset is absent). Pins that the wiring actually reaches each solver.
    expect = {
        "Prob017_mux2to1v": "multiplexer",
        "Prob085_shift4": "shift_register",
        "Prob108_rule90": "cellular_automaton",
        "Prob082_lfsr32": "galois_lfsr",
        "Prob071_always_casez": "priority_encoder",
        "Prob006_vectorr": "vector_ops",
        "Prob034_dff8": "dff_edge",
        "Prob009_popcount3": "counter_popcount",
        "Prob088_ece241_2014_q5b": "mealy_fsm_sequence",
        "Prob005_notgate": "comb_gate",
        "Prob001_zero": "residual_combinational",
        # wave-3
        "Prob024_hadd": "arithmetic",
        "Prob068_countbcd": "counter_advanced",
        "Prob137_fsm_serial": "serial_protocol_fsm",
        "Prob070_ece241_2013_q2": "nextstate_misc",
        "Prob096_review2015_fsmseq": "behavioral_fsm",
        "Prob055_conditional": "comb_advanced",
        # wave-4 (gshare_predictor now fires on Prob153 via the owner-directed house
        # default: predictor counter -> weakly-not-taken 2'b01, history -> 0)
        "Prob153_gshare": "gshare_predictor",
        "Prob144_conwaylife": "conway_2d",
        "Prob117_circuit9": "sequential_waveform_multibit",
        "Prob145_circuit8": "sequential_waveform_multibit",
    }
    checked = 0
    for prob, want in expect.items():
        p = f"{_DS}/{prob}_prompt.txt"
        if not os.path.exists(p):
            continue
        k, rtl = R.generate(open(p, errors="replace").read(), "TopModule")
        assert k == want and rtl, f"{prob}: got {k!r}, want {want!r}"
        checked += 1
    if checked == 0:
        import pytest
        pytest.skip("VE-Human dataset not present")
