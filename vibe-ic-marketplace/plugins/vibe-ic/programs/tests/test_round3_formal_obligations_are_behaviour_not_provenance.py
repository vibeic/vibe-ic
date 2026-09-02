"""ROUND-3 (subservient x gf180mcuD, 2026-09-02): `formal_harness_gen` must
not enumerate L-document PROVENANCE leaves as temporal obligations.

MEASURED on the round-2 project: Step 5 requested 7 expert obligations from
L8, three of which were `clock_and_reset_waveform.derived_from.0`,
`.derived_from.1` (paths of the emitting L documents) and
`.extraction_strategy` (the emitter's name), plus `clocks.0.name` (a port
binding). They were selected because the CONTAINER key contains "reset".
No property can discharge a provenance path, so the only honest disposition
was UNANSWERABLE and Step 5 could never complete on any design that ships
an L8 — the expert fallback was unfinishable by construction.

Now a leaf qualifies by its OWN key, its nearest GROUP key, or a sequencing
statement in its VALUE; provenance keys and artefact-path values never do.

FALSIFICATION (two-tree, MEASURED 2026-09-02 on 8f3755d9f): on the pre-fix
tree 4 of 6 fail (`test_real_shape_yields_only_the_reset_declarations`,
`test_provenance_leaves_are_never_obligations`,
`test_value_semantics_qualify_without_a_matching_key`,
`test_artefact_path_values_never_qualify`); the two CONTROL tests pass on
both trees.

chip-AGNOSTIC: neutral keys/values; the real-shape fixture is the emitter's
generic L8 key layout, not a design.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import formal_harness_gen as F  # noqa: E402


_L8_SHAPE = {
    "clocks": [{"name": "clk_a"}],
    "resets": [{"name": "rst_a", "polarity": "active_high",
                "port_description": "synchronous, active-high; internals clear "
                                    "the cycle after assert"}],
    "derived_from": ["phase1/generated_docs/L8_X.json",
                     "phase1/generated_docs/L9_Y.json"],
    "extraction_strategy": "l8_clock_reset_waveform_emit",
}


def test_real_shape_yields_only_the_reset_declarations():
    got = F._timing_semantics({"clock_and_reset_waveform": _L8_SHAPE})
    assert [k for k, _ in got] == [
        "clock_and_reset_waveform.resets.0.name",
        "clock_and_reset_waveform.resets.0.polarity",
        "clock_and_reset_waveform.resets.0.port_description",
    ]


def test_provenance_leaves_are_never_obligations():
    got = F._timing_semantics({"clock_and_reset_waveform": {
        "clocks": [{"name": "clk_a"}],
        "derived_from": ["phase1/generated_docs/L8_X.json"],
        "extraction_strategy": "l8_clock_reset_waveform_emit"}})
    assert got == []


def test_control_leaf_key_semantics_still_qualify():
    """CONTROL (both trees): a leaf whose own key states sequencing is kept
    even under a container that does not."""
    assert F._timing_semantics({"sram": {"read_latency_cycles": 1}}) == [
        ("sram.read_latency_cycles", "1")]


def test_control_group_key_semantics_still_qualify():
    """CONTROL (both trees): leaves under a `resets` group are kept."""
    got = F._timing_semantics({"resets": [{"name": "rst_n", "polarity": "active_low"}]})
    assert got == [("resets.0.name", "rst_n"), ("resets.0.polarity", "active_low")]


def test_value_semantics_qualify_without_a_matching_key():
    got = F._timing_semantics({"bus": {"note_free": "data valid one cycle after cyc"}})
    assert got == [("bus.note_free", "data valid one cycle after cyc")]


def test_artefact_path_values_never_qualify():
    assert F._timing_semantics({"resets": [{"trace": "phase1/generated_docs/L8.json"}]}) == []
