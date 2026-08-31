"""#139(b) re-injected a module the official harness compiles itself.

The repair exists for a module DROPPED from the very file the author is
rewriting. It was also firing for a module the harness STAGES, and appending
that one is a duplicate declaration: elaboration dies on `already been declared
in this scope`.

Which provided module owns which source file is still decided from
`input.context` alone. The separate response-contract loader reads only the
output path keys that the official question shows to the candidate; it never
participates in this reinjection decision and never reads reference bodies.

Measured on 302 authored CVDP completions: 3 designs failed this way.
`cvdp_copilot_elevator_control_0033`/`0036` define `elevator_control_system` and
instantiate `floor_to_seven_segment`, which lives in a different provided file;
`cvdp_copilot_scrambler_0018` is the same shape with `intra_block`. On 0033/0036
it surfaced as a verilator lint failure that was never a lint issue.
"""
import importlib.util
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
for p in (str(PLUGIN / "benchmark"), str(PLUGIN / "programs")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _gate():
    spec = importlib.util.spec_from_file_location(
        "gate_reinject_under_test", PLUGIN / "benchmark" / "cvdp_gate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# the author rewrites rtl/pair.sv (it defines A and B, the delivery defines A)
# and also instantiates C, which lives in rtl/other.sv — a file the harness stages.
_CTX = {
    "rtl/pair.sv": "module A(input c);\n  B u(.c(c));\nendmodule\n"
                   "module B(input c);\nendmodule\n",
    "rtl/other.sv": "module C(input c);\nendmodule\n",
}
_EMITTED = "module A(input c);\n  B u(.c(c));\n  C v(.c(c));\nendmodule\n"


def test_a_harness_staged_module_is_not_appended():
    """THE REGRESSION: C lives in a provided file the delivery does not rewrite,
    so the harness compiles it — appending a copy duplicates the declaration."""
    g = _gate()
    _, reincluded = g.preserve_dropped_context_modules(
        _EMITTED, list(_CTX.values()), ctx_by_path=_CTX)
    assert "C" not in reincluded, reincluded


def test_a_module_dropped_from_the_rewritten_file_is_still_repaired():
    """The other tail: #139(b) must keep doing what it was written for. B was
    dropped from rtl/pair.sv, the very file the delivery rewrites."""
    g = _gate()
    _, reincluded = g.preserve_dropped_context_modules(
        _EMITTED, list(_CTX.values()), ctx_by_path=_CTX)
    assert reincluded == ["B"], reincluded


def test_without_the_path_map_the_behaviour_is_unchanged():
    """A caller that cannot supply the owning paths keeps the old repair."""
    g = _gate()
    _, reincluded = g.preserve_dropped_context_modules(
        _EMITTED, list(_CTX.values()))
    assert set(reincluded) == {"B", "C"}, reincluded


def test_the_gate_still_does_not_read_output_context():
    """The compliance boundary this fix had to respect: `output.context` is the
    reference-solution field. The decision is made from `input.context` only."""
    src = (PLUGIN / "benchmark" / "cvdp_gate.py").read_text(encoding="utf-8")
    fn = src.split("def _load_context_rtl_by_path", 1)[1].split("\ndef ", 1)[0]
    assert '"output"' not in fn and "'output'" not in fn, \
        "the path-keyed loader must read input.context only"
