"""Tests for general_synth.py — the §4.05-APPROVED general structural solver
bank wired into the RTLLM tier pipeline.

Two layers:
  * PURE-LOGIC (always run): the mechanical §4.05 magic-constant gate over the
    assembled bank (must be CLEAN, and the gate must itself CATCH a planted magic
    constant — it is not a no-op), plus per-emitter §4.05 NEGATIVE cases (a near-miss
    / different-width / renamed-input prose must produce a CORRECT emit or SKIP —
    NEVER a wrong emit).
  * DATASET+IVERILOG (auto-skipped when the RTLLM dataset or iverilog/vvp are
    absent): each kept emitter fires on its design AND the emit iverilog-PASSES that
    design's own testbench; a no-cross-fire sweep asserting no emitter
    fires-and-FAILS on any of the 50 designs.

chip-AGNOSTIC: every assertion keys on STRUCTURE (the operation cue + interface
shape + golden-vs-testbench result), never on a design name embedded in the emitter.
"""
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import general_synth as G            # noqa: E402
import rtllm_tier_pipeline as P            # noqa: E402
import port_parser as PP                   # noqa: E402
import prose_port_block_read as BR             # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_RTLLM_ROOT = corpus_path("_extbench/RTLLM")
_HAVE_IV = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_HAVE_DS = _RTLLM_ROOT.is_dir()
_needs_iv = pytest.mark.skipif(not _HAVE_IV, reason="iverilog/vvp not installed")
_needs_ds = pytest.mark.skipif(not _HAVE_DS, reason="RTLLM dataset absent")


# the §4.05-kept emitters and the RTLLM design each is expected to Tier-1-solve.
# (the bank dispatches by STRUCTURE; this map is for the dataset/iverilog layer only.)
_EMITTER_DESIGN = {
    "_try_bcd_adder": "adder_bcd",
    "_try_comparator": "comparator_3bit",
    "_try_subtractor": "sub_64bit",
    "_try_seq_multiplier": "multi_16bit",
    "_try_divider": "div_16bit",
    "_try_pipe_adder": "adder_pipe_64bit",
    "_try_johnson_counter": "JC_counter",
    "_try_updown_counter": "up_down_counter",
    "_try_barrel_shifter": "barrel_shifter",
    "_try_right_shifter": "right_shifter",
    "_try_edge_detect": "edge_detect",
    "_try_pulse_detect": "pulse_detect",
    # _try_comb_multiplier fires on 0 of the 50 (its forms are caught by the seq
    # multiplier / the arith ext); it is kept but has no dataset positive.
    "_try_comb_multiplier": None,
}

# the keep-list the orchestrator approved (the DROPPED _try_mod_counter is NOT here).
_KEEP_LIST = [
    "_try_comparator", "_try_subtractor", "_try_bcd_adder", "_try_comb_multiplier",
    "_try_seq_multiplier", "_try_divider", "_try_updown_counter",
    "_try_johnson_counter", "_try_right_shifter", "_try_barrel_shifter",
    "_try_edge_detect", "_try_pulse_detect", "_try_pipe_adder",
]


def _design_dir(basename: str):
    if not _HAVE_DS:
        return None
    hits = list(_RTLLM_ROOT.glob(f"**/{basename}/design_description.txt"))
    return hits[0].parent if hits else None


def _iface(design_dir):
    prompt = P.design_prompt(str(design_dir))
    bridged = BR.bridge_prompt(prompt)
    ins, outs = PP.parse_ports(bridged)
    return prompt, ins, outs


# --------------------------------------------------------------------------- #
# bank shape — the kept set is exactly the 13 §4.05-approved emitters
# --------------------------------------------------------------------------- #
def test_bank_is_exactly_the_kept_set():
    names = [s.__name__ for s in G.SOLVERS]
    assert set(names) == set(_KEEP_LIST), (set(names) ^ set(_KEEP_LIST))
    # the DROPPED + every REJECTED overfit emitter is absent from the module.
    forbidden = ["_try_mod_counter", "_try_booth_multiplier", "_try_pipe_multiplier",
                 "_try_float_multiplier", "_try_alu", "_try_lfsr", "_try_calendar",
                 "_try_parallel2serial", "_try_serial2parallel", "_try_width_8to16",
                 "_try_instr_reg", "_try_mac_pe", "_try_freq_div_fixed",
                 "_try_freq_div_even", "_try_freq_div_odd", "_try_freq_div_frac",
                 "_try_mealy_10011", "_try_seq_detect_1001", "_try_traffic_light"]
    for f in forbidden:
        assert not hasattr(G, f), f"forbidden/overfit emitter `{f}` present in bank"


# --------------------------------------------------------------------------- #
# MECHANICAL §4.05 magic-constant gate — CLEAN over the bank, and not a no-op
# --------------------------------------------------------------------------- #
def test_magic_constant_gate_clean():
    assert G.magic_constant_violations() == []


def test_magic_constant_gate_catches_a_planted_constant():
    """The gate must FIRE on a body that emits a bare sized magic constant, and must
    NOT fire on a width-derived `{ow}'d{maxv}` or a 1-bit `1'b1` — otherwise it is a
    no-op backstop."""
    bad = (
        "def _try_bad(p, i, o, t):\n"
        "    return \"    if (cnt == 8'd49) x <= 0;\\n\"\n"
        "def _try_ok(p, i, o, t):\n"
        "    return f\"    if (x == {ow}'d{maxv}) y <= 0;\\n    z <= 1'b1;\\n\"\n"
    )
    v = G.magic_constant_violations(source=bad)
    assert any("8'd49" in x and "_try_bad" in x for x in v), v
    assert not any("_try_ok" in x for x in v), v


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVES — a near-miss / different-width / renamed-input prose must give a
# CORRECT emit or SKIP, never a wrong one. These run with NO dataset (pure-logic).
# --------------------------------------------------------------------------- #
def test_comparator_skips_when_not_three_flag_outputs():
    # comparator cue present but only one output -> SKIP (no wrong 3-flag emit).
    rtl = G._try_comparator("a 4-bit comparator", [("a", 4), ("b", 4)],
                            [("eq", 1)], "T")
    assert rtl is None


def test_comparator_renamed_inputs_still_correct():
    # different operand NAMES (x/y) + flag names gt/eq/lt -> still binds correctly.
    rtl = G._try_comparator("compare two operands",
                            [("x", 8), ("y", 8)],
                            [("gt", 1), ("eq", 1), ("lt", 1)], "Cmp")
    assert rtl is not None
    assert "assign gt = (x > y);" in rtl
    assert "assign eq = (x == y);" in rtl
    assert "assign lt = (x < y);" in rtl


def test_comparator_skips_on_mismatched_operand_widths():
    rtl = G._try_comparator("compare", [("a", 8), ("b", 4)],
                            [("g", 1), ("e", 1), ("l", 1)], "T")
    assert rtl is None


def test_subtractor_skips_when_bcd_present():
    # 'subtract' + 'bcd' is the BCD path, not the plain subtractor -> SKIP.
    rtl = G._try_subtractor("a bcd subtractor", [("a", 8), ("b", 8)],
                            [("y", 8), ("ovf", 1)], "T")
    assert rtl is None


def test_subtractor_width_driven_overflow_bit():
    # the overflow index must follow the operand WIDTH, not a hardcoded position.
    rtl = G._try_subtractor("subtractor", [("a", 16), ("b", 16)],
                            [("res", 16), ("ovf", 1)], "Sub")
    assert rtl is not None
    assert "a[15]" in rtl and "b[15]" in rtl  # width-1 == 15 for 16-bit operands


def test_bcd_adder_skips_without_bcd_cue():
    rtl = G._try_bcd_adder("a plain adder", [("a", 4), ("b", 4)],
                           [("sum", 4), ("cout", 1)], "T")
    assert rtl is None


def test_comb_multiplier_skips_when_clock_present():
    # a clocked input means this is NOT the combinational multiplier path -> SKIP.
    rtl = G._try_comb_multiplier("a multiplier",
                                 [("clk", 1), ("a", 4), ("b", 4)], [("p", 8)], "T")
    assert rtl is None


def test_comb_multiplier_skips_on_wrong_product_width():
    # product width must equal aw+bw; a mismatched width -> SKIP (no wrong emit).
    rtl = G._try_comb_multiplier("multiplier", [("a", 4), ("b", 4)],
                                 [("p", 7)], "T")
    assert rtl is None


def test_divider_skips_when_clocked():
    rtl = G._try_divider("a divider", [("clk", 1), ("a", 8), ("b", 8)],
                         [("q", 8), ("r", 8)], "T")
    assert rtl is None


def test_johnson_skips_on_plain_counter_prose():
    # a plain 'counter' (no johnson/twisted cue) must NOT be claimed by johnson.
    rtl = G._try_johnson_counter("a binary counter",
                                 [("clk", 1), ("rst", 1)], [("q", 4)], "T")
    assert rtl is None


def test_updown_skips_without_direction_port():
    rtl = G._try_updown_counter("an up-down counter",
                                [("clk", 1), ("rst", 1)], [("q", 4)], "T")
    assert rtl is None


def test_pipe_adder_skips_without_pipeline_cue():
    rtl = G._try_pipe_adder("a plain adder",
                            [("clk", 1), ("rst", 1), ("i_en", 1), ("a", 8), ("b", 8)],
                            [("result", 9), ("o_en", 1)], "T")
    assert rtl is None


def test_edge_detect_skips_without_edge_cue():
    rtl = G._try_edge_detect("a flip flop",
                             [("clk", 1), ("rst", 1), ("a", 1)],
                             [("rise", 1), ("down", 1)], "T")
    assert rtl is None


def test_pulse_detect_skips_without_pulse_cue():
    rtl = G._try_pulse_detect("an edge detector",
                              [("clk", 1), ("rst", 1), ("din", 1)], [("dout", 1)], "T")
    assert rtl is None


def test_synth_skips_on_empty_prompt():
    assert G.synth("", [], [], "T") is None


def test_synth_skips_on_unrelated_prompt():
    # an out-of-scope structure (a FIFO) matches no kept emitter -> SKIP.
    assert G.synth("an asynchronous FIFO with full/empty flags",
                   [("clk", 1), ("din", 8)], [("dout", 8), ("full", 1)], "T") is None


# --------------------------------------------------------------------------- #
# DATASET + IVERILOG — each kept emitter fires + iverilog-PASSES on its design
# --------------------------------------------------------------------------- #
@_needs_ds
@_needs_iv
@pytest.mark.parametrize("emitter,design", [
    (e, d) for e, d in _EMITTER_DESIGN.items() if d is not None])
def test_emitter_positive_fires_and_iverilog_passes(emitter, design):
    dd = _design_dir(design)
    assert dd is not None, f"design dir for {design} not found"
    prompt, ins, outs = _iface(dd)
    top = P.required_module_name(str(dd)) or "TopModule"
    fn = getattr(G, emitter)
    rtl = fn(prompt, ins, outs, top)
    assert rtl is not None, f"{emitter} did not fire on {design}"
    compiled, passed, log = P.iverilog_score(str(dd), rtl, top)
    assert passed, f"{emitter} emit FAILED iverilog on {design}: {log}"


@_needs_ds
@_needs_iv
def test_no_cross_fire_and_fail_sweep():
    """Each emitter may fire on <=1..2 of the 50 designs, but it must NEVER
    fire-and-FAIL: every emit that fires must iverilog-PASS that design's own
    testbench. (This is the binding §4.05 no-cross-fire rule.)"""
    designs = sorted(P.find_designs(str(_RTLLM_ROOT)))
    fire_fail = []
    for d in designs:
        prompt = P.design_prompt(d)
        bridged = BR.bridge_prompt(prompt)
        try:
            ins, outs = PP.parse_ports(bridged)
        except Exception:
            ins, outs = [], []
        top = P.required_module_name(d) or "TopModule"
        for s in G.SOLVERS:                       # synth() dispatch: first match wins
            try:
                rtl = s(prompt, ins, outs, top)
            except Exception:
                rtl = None
            if rtl:
                compiled, passed, log = P.iverilog_score(d, rtl, top)
                if not passed:
                    fire_fail.append((s.__name__, Path(d).name, log[:120]))
                break
    assert not fire_fail, f"emitters fired-and-FAILED: {fire_fail}"


@_needs_ds
@_needs_iv
def test_floors_and_originals_unchanged_by_the_bank():
    """The 4 golden-fails-own-test floors stay Tier5 and are NOT solved by the bank;
    the 13 pre-bank Tier1 designs stay Tier1."""
    floors = {"radix2_div", "ring_counter", "asyn_fifo", "clkgenerator"}
    originals = {"accu", "adder_16bit", "adder_32bit", "adder_8bit", "multi_pipe_4bit",
                 "fixed_point_adder", "fixed_point_substractor", "LIFObuffer",
                 "synchronizer", "RAM", "ROM", "signal_generator", "square_wave"}
    for d in P.find_designs(str(_RTLLM_ROOT)):
        name = Path(d).name
        if name in floors:
            assert P.classify(d) == P.TIER_FLOOR, f"{name} no longer a Tier5 floor"
        if name in originals:
            assert P.classify(d) == P.TIER_PROGRAM, f"{name} no longer Tier1"
