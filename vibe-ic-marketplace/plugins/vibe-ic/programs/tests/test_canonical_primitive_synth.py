#!/usr/bin/env python3
"""Tests for canonical_primitive_synth.py.

POSITIVE: for each of the 9 dataset design_description.txt files, detect_shape
must return the expected shape, and --from-desc emit must produce RTL whose
declared module name matches the spec's 'Module name:' token.

NEGATIVE: a handful of OTHER RTLLM specs (adder_8bit, freq_divbyeven,
synchronizer, multi_16bit) must detect_shape -> None (no mis-fire).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import os
import pytest

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent                         # .../programs
PROG = PROGRAMS / "canonical_primitive_synth.py"
# Resolved from the environment, not hardcoded: a personal home path in
# shipped source is unresolvable for every other user, and
# `shipped_path_portability_check` blocks on it. The dataset-backed tests
# already skip when the corpus is absent, so an unset var simply skips.
# Reintroduced twice by stacked PRs authored against an older base — hence
# the gate, and hence this comment sitting where the literal used to be.
RTLLM = Path(os.environ.get("VIBEIC_RTLLM_CORPUS",
                            Path.home() / "_bench_rtllm2_scratch/RTLLM"))
# The dataset-backed tests only run where the RTLLM corpus is checked out locally;
# in CI it is absent, so they skip. The self-contained inline tests below prove
# the detection contract with NO external dataset (they always run).
_need_dataset = pytest.mark.skipif(
    not RTLLM.exists(), reason="RTLLM dataset not present on this host")

sys.path.insert(0, str(PROGRAMS))
import canonical_primitive_synth as rcs  # noqa: E402

# spec-dir (relative to RTLLM) -> (expected_shape, expected_module)
POSITIVE = {
    "Miscellaneous/Frequency divider/freq_divbyodd":
        ("odd_clock_divider", "freq_divbyodd"),
    "Miscellaneous/Frequency divider/freq_divbyfrac":
        ("frac_clock_divider_3p5", "freq_divbyfrac"),
    "Miscellaneous/Others/pulse_detect":
        ("pulse_detect_0to1to0", "pulse_detect"),
    "Miscellaneous/Others/serial2parallel":
        ("serial_to_parallel_8", "serial2parallel"),
    "Miscellaneous/Others/parallel2serial":
        ("parallel_to_serial_4", "parallel2serial"),
    "Arithmetic/Divider/div_16bit":
        ("combinational_long_divider", "div_16bit"),
    "Miscellaneous/Others/traffic_light":
        ("traffic_light_fsm", "traffic_light"),
    "Arithmetic/Divider/radix2_div":
        ("radix2_signed_divider", "radix2_div"),
    "Arithmetic/Other/float_multi":
        ("ieee754_single_multiplier", "float_multi"),
    "Memory/FIFO/asyn_fifo":
        ("async_gray_fifo", "asyn_fifo"),
    "Arithmetic/Multiplier/multi_pipe_8bit":
        ("pipelined_unsigned_multiplier_8", "multi_pipe_8bit"),
    "Memory/Shifter/barrel_shifter":
        ("barrel_shifter_right_8", "barrel_shifter"),
    "Miscellaneous/Signal generation/signal_generator":
        ("triangle_wave_generator_5", "signal_generator"),
    "Control/Finite State Machine/fsm":
        ("mealy_seq_detector_10011", "fsm"),
    "Arithmetic/Adder/adder_pipe_64bit":
        ("pipelined_ripple_adder_64", "adder_pipe_64bit"),
}

NEGATIVE = [
    "Arithmetic/Adder/adder_8bit",
    "Miscellaneous/Frequency divider/freq_divbyeven",
    "Miscellaneous/Others/synchronizer",
    "Arithmetic/Multiplier/multi_16bit",
]


def _desc(reldir: str) -> str:
    return (RTLLM / reldir / "design_description.txt").read_text(errors="replace")


def _module_decl(rtl: str) -> str:
    # top module: for asyn_fifo the top is asyn_fifo (dual_port_RAM is a submodule).
    mods = re.findall(r"(?m)^\s*module\s+([A-Za-z_]\w*)", rtl)
    return mods[-1] if mods else ""


@_need_dataset
@pytest.mark.parametrize("reldir,expected", POSITIVE.items())
def test_detect_positive(reldir, expected):
    shape, module = expected
    desc = _desc(reldir)
    assert rcs.detect_shape(desc) == shape


@_need_dataset
@pytest.mark.parametrize("reldir,expected", POSITIVE.items())
def test_emit_from_desc(reldir, expected, tmp_path):
    shape, module = expected
    spec = RTLLM / reldir / "design_description.txt"
    out = tmp_path / f"{module}.v"
    r = subprocess.run(
        [sys.executable, str(PROG), "--from-desc", str(spec), "--out", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    j = json.loads(r.stdout)
    assert j["verdict"] == "EMIT"
    assert j["shape"] == shape
    assert j["module"] == module
    rtl = out.read_text()
    # emitted RTL declares a module whose (top) name matches the spec module name
    assert re.search(r"(?m)^\s*module\s+" + re.escape(module) + r"\b", rtl)
    # and the spec's own Module name token equals that module
    assert rcs.module_name_of(_desc(reldir)) == module


@_need_dataset
@pytest.mark.parametrize("reldir", NEGATIVE)
def test_detect_negative(reldir):
    desc = _desc(reldir)
    assert rcs.detect_shape(desc) is None, f"mis-fired on {reldir}"


def test_emit_covers_all_nine():
    shapes = {s for s, _ in POSITIVE.values()}
    for s in shapes:
        rtl = rcs.emit_rtl(s)
        assert "module" in rtl and "endmodule" in rtl


# ============================================================================
# Self-contained inline tests — NO external dataset, always run (incl. CI).
# These pin the STRUCTURAL detection contract with synthetic descriptions that
# reproduce each shape's signature, and prove fail-closed DEFER on near-misses.
# ============================================================================
_INLINE_POS = {
    "odd_clock_divider": (
        "Module name:\n    freq_divbyodd\n"
        "A frequency divider that divides the input clock by odd numbers.\n"
        "Input ports:\n clk: Input clock.\n rst_n: Active low reset.\n"
        "Output ports:\n clk_div: Divided clock output.\n"
        "The parameter NUM_DIV defaults to 5.\n"),
    "frac_clock_divider_3p5": (
        "Module name:\n    freq_divbyfrac\n"
        "A fractional frequency divider (3.5x) using the double-edge clocking "
        "technique. MUL2_DIV_CLK = 7.\n"
        "Input ports:\n clk: Input clock.\n rst_n: Active low reset.\n"
        "Output ports:\n clk_div: Fractionally divided clock output.\n"),
    "pulse_detect_0to1to0": (
        "Module name:\n    pulse_detect\n"
        "Pulse detection: when data_in changes from 0 to 1 to 0 this is a pulse.\n"
        "Input ports:\n clk: Clock.\n rst_n: Reset.\n data_in: One-bit input.\n"
        "Output ports:\n data_out: pulse indicator.\n"),
    "combinational_long_divider": (
        "Module name:\n    div_16bit\n"
        "Implement a 16-bit divider in combinational logic. The dividend is "
        "16-bit and the divisor is 8-bit.\n"
        "Input ports:\n A: 16-bit dividend.\n B: 8-bit divisor.\n"
        "Output ports:\n result: 16-bit quotient.\n odd: 16-bit remainder.\n"),
    "pipelined_unsigned_multiplier_8": (
        "Module name:\n    multi_pipe_8bit\n"
        "Implement an unsigned 8bit multiplier based on pipelining processing.\n"
        "Input ports:\n clk: Clock.\n rst_n: Active-low reset.\n"
        " mul_en_in: Input enable.\n mul_a: 8-bit multiplicand.\n"
        " mul_b: 8-bit multiplier.\n"
        "Output ports:\n mul_en_out: Output enable.\n mul_out: 16-bit product.\n"),
    "barrel_shifter_right_8": (
        "Module name:\n    barrel_shifter\n"
        "A barrel shifter for shifting bits efficiently, controlled by ctrl.\n"
        "Input ports:\n in: 8-bit input to be shifted.\n ctrl: 3-bit shift amount.\n"
        "Output ports:\n out: 8-bit shifted output.\n"),
    "triangle_wave_generator_5": (
        "Module name:\n    signal_generator\n"
        "Implement a Triangle Wave generator whose 5-bit wave cycles between "
        "0 and 31.\n"
        "Input ports:\n clk: Clock.\n rst_n: Active-low reset.\n"
        "Output ports:\n wave: 5-bit output waveform.\n"),
    "mealy_seq_detector_10011": (
        "Module name:\n    fsm\n"
        "Implement a Mealy FSM detection circuit that detects a single-bit input "
        "IN. When the input is 10011, output MATCH is 1.\n"
        "Input ports:\n IN: Input signal.\n CLK: Clock.\n RST: Reset.\n"
        "Output ports:\n MATCH: match indicator.\n"),
    "pipelined_ripple_adder_64": (
        "Module name:\n    adder_pipe_64bit\n"
        "Implement a 64-bit ripple carry adder with several registers to enable "
        "the pipeline stages.\n"
        "Input ports:\n clk: Clock.\n rst_n: Active low reset.\n i_en: Enable.\n"
        " adda: 64-bit A.\n addb: 64-bit B.\n"
        "Output ports:\n result: 65-bit sum.\n o_en: Output enable.\n"),
    "parallel_to_serial_4": (
        "Module name:\n    parallel2serial\n"
        "Implement a module for parallel-to-serial conversion, where every four "
        "input bits are converted to a serial one bit output (from MSB to LSB).\n"
        "Input ports:\n clk: Clock.\n rst_n: Active low reset.\n"
        " d: 4-bit parallel data input.\n"
        "Output ports:\n valid_out: Valid signal.\n dout: Serial output.\n"),
}

# Near-miss descriptions that MUST fail-closed to None (no template mis-fire).
_INLINE_NEG = [
    # even divider — same clk/rst_n/clk_div ports, but "even" not "odd"/"3.5".
    ("Module name:\n    freq_divbyeven\n"
     "A frequency divider that divides by even numbers.\n"
     "Input ports:\n clk\n rst_n\n Output ports:\n clk_div\n"),
    # a plain 8-bit adder — no matching shape.
    ("Module name:\n    adder_8bit\n"
     "An 8-bit adder.\n Input ports:\n a\n b\n Output ports:\n sum\n"),
    # right port names but wrong function word (a *multiplier*, not divider).
    ("Module name:\n    mul_16bit\n"
     "A 16-bit multiplier in combinational logic.\n"
     "Input ports:\n A: 16-bit.\n B: 8-bit.\n Output ports:\n result\n odd\n"),
    # a Mealy FSM with the fsm ports but a DIFFERENT pattern (1011, not 10011) —
    # the mealy_seq_detector_10011 shape must fail-closed on a foreign pattern.
    ("Module name:\n    fsm\n"
     "Implement a Mealy FSM that detects the input pattern 1011.\n"
     "Input ports:\n IN\n CLK\n RST\n Output ports:\n MATCH\n"),
    # the sibling sequence_detector — an FSM, but NOT module `fsm`, so no misfire.
    ("Module name:\n    sequence_detector\n"
     "A finite state machine detecting the 1001 sequence via states.\n"
     "Input ports:\n clk\n reset_n\n data_in\n Output ports:\n detected\n"),
    # a plain combinational 64-bit adder with the adda/addb ports but NO pipeline —
    # pipelined_ripple_adder_64 must fail-closed without the "pipeline" structure.
    ("Module name:\n    adder_pipe_64bit\n"
     "A 64-bit ripple carry adder, purely combinational.\n"
     "Input ports:\n clk\n rst_n\n i_en\n adda\n addb\n Output ports:\n result\n o_en\n"),
    # a pipelined adder of a DIFFERENT width (32-bit), wrong module name — no misfire.
    ("Module name:\n    adder_pipe_32bit\n"
     "A 32-bit pipelined ripple carry adder.\n"
     "Input ports:\n clk\n rst_n\n i_en\n adda\n addb\n Output ports:\n result\n o_en\n"),
    # right module name + ports for parallel2serial but NO parallel-to-serial
    # phrase — the detector must fail-closed rather than key on ports alone.
    ("Module name:\n    parallel2serial\n"
     "A generic 4-bit register block.\n"
     "Input ports:\n clk\n rst_n\n d\n Output ports:\n valid_out\n dout\n"),
]


@pytest.mark.parametrize("shape,desc", _INLINE_POS.items())
def test_inline_detect_positive(shape, desc):
    assert rcs.detect_shape(desc) == shape


@pytest.mark.parametrize("desc", _INLINE_NEG)
def test_inline_detect_negative_failclosed(desc):
    assert rcs.detect_shape(desc) is None


def test_module_name_extraction():
    assert rcs.module_name_of("Module name:\n    freq_divbyodd\n") == "freq_divbyodd"


def test_parallel2serial_dout_is_combinational():
    """The load-bearing property: the parallel2serial template must drive dout
    with a CONTINUOUS assign (combinational MSB of the shift register), never a
    registered `dout <=`. Registering it delays every serial bit one cycle — the
    exact r8 failure this shape was added to fold in. This test FAILS if a future
    edit registers dout."""
    rtl = rcs.emit_rtl("parallel_to_serial_4")
    # strip // comments so the explanatory prose can't satisfy/trip the checks
    code = "\n".join(re.sub(r"//.*$", "", ln) for ln in rtl.splitlines())
    assert re.search(r"assign\s+dout\s*=", code), "dout must be a continuous assign"
    assert not re.search(r"\bdout\s*<=", code), "dout must NOT be registered"
    # dout is a plain wire output (not `output reg`)
    assert re.search(r"output\s+dout\b", code), "dout must be a wire output, not reg"


# ============================================================================
# Runner-integration: the step_rtl_gen hook _try_canonical_primitive_rtl must
# fire on a project whose phase1/input_doc description states a canonical shape,
# emit RTL to phase2/stage1/rtl/, and DEFER (None) on a non-matching project.
# Self-contained (inline description); no external dataset.
# ============================================================================
def _load_runner():
    sys.path.insert(0, str(PROGRAMS))
    import design_one_shot_runner as mod  # noqa: E402
    return mod


def _mk_project(tmp_path, desc_text):
    idoc = tmp_path / "phase1" / "input_doc"
    idoc.mkdir(parents=True)
    (idoc / "design_description.txt").write_text(desc_text)
    return tmp_path


def test_hook_fires_and_emits(tmp_path):
    R = _load_runner()
    proj = _mk_project(tmp_path, _INLINE_POS["pulse_detect_0to1to0"])
    res = R._try_canonical_primitive_rtl(proj, 0.0)
    assert res is not None and res.status == "PASS"
    assert res.extras.get("deterministic_generator") == "canonical_primitive_synth"
    assert res.extras.get("shape") == "pulse_detect_0to1to0"
    emitted = list((proj / "phase2" / "stage1" / "rtl").glob("*.v"))
    assert [p.name for p in emitted] == ["pulse_detect.v"]
    assert "module pulse_detect" in emitted[0].read_text()


def test_hook_defers_on_nonmatching(tmp_path):
    R = _load_runner()
    proj = _mk_project(tmp_path, _INLINE_NEG[1])   # a plain 8-bit adder
    assert R._try_canonical_primitive_rtl(proj, 0.0) is None


def test_hook_author_guard_never_overwrites(tmp_path):
    R = _load_runner()
    proj = _mk_project(tmp_path, _INLINE_POS["pulse_detect_0to1to0"])
    rtl_dir = proj / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "existing.v").write_text("module existing(); endmodule\n")
    # RTL already present → the guard must DEFER (never clobber the design's own).
    assert R._try_canonical_primitive_rtl(proj, 0.0) is None


# ============================================================================
# issue #2035, families F6 + F7, and the architecture question underneath them.
#
# MEASURED FIRST (base 764d6b3e5, host 8HD-8): two neutral input-only
# descriptions naming `Module name: barrel_shifter` with ports in/ctrl/out both
# returned EMIT rc=0 and were overwritten with the fixed three-mux hierarchy --
# one of them while the input said in plain words that no submodule and no
# generate block may be used. Detection was doing duty as topology selection,
# which is why an ALTERNATIVE-ARCHITECTURE CONTROL could not be satisfied at all.
#
# These tests pin, in order: the sixteen templates do not move; a stated
# structural directive withdraws a template and is NAMED for the AI author; and
# F6/F7 are COMPOSED from the acceptance contract the input states rather than
# from a seventeenth and eighteenth fixed template.
# ============================================================================

_ARCH_CONFLICT_DESC = (
    "Module name:\n    barrel_shifter\n"
    "A barrel shifter for shifting bits efficiently, controlled by ctrl.\n"
    "Input ports:\n in: 8-bit input to be shifted.\n ctrl: 3-bit shift amount.\n"
    "Output ports:\n out: 8-bit shifted output.\n"
    "This block is delivered as a single leaf cell: the implementation must not\n"
    "instantiate any submodule and must not use a generate block.\n")

_F6_DESC = (
    "Module name:\n    elastic_stage\n"
    "An elastic pipeline stage between a producer and a consumer.\n"
    "Input ports:\n clk: Clock signal.\n rst_n: Active low reset signal.\n"
    " up_data [7:0]: The 8-bit word offered by the producer.\n"
    " up_valid: High when the producer is offering up_data.\n"
    " dn_ready: High when the consumer can take a word this cycle.\n"
    "Output ports:\n up_ready: High when this stage can take a word.\n"
    " dn_data [7:0]: The word offered to the consumer.\n"
    " dn_valid: High when dn_data is being offered.\n"
    "Implementation:\n"
    "A transfer happens when that interface's valid and ready are both high.\n"
    "The stage must register the output and buffer one additional transfer so\n"
    "the producer is only stalled when no slot is free. No word that was not\n"
    "accepted may be captured, no accepted word may be lost under backpressure,\n"
    "and accepted words must leave in the order they arrived.\n")

# Same shape, same words, a DIFFERENT legitimate architecture: zero added
# latency. This is the alternative-architecture control for the contract layer.
_F6_STORAGE_SENTENCE = (
    "The stage must register the output and buffer one additional transfer so\n"
    "the producer is only stalled when no slot is free. ")
assert _F6_STORAGE_SENTENCE in _F6_DESC, "fixture drifted"

_F6_ALT_DESC = _F6_DESC.replace(
    _F6_STORAGE_SENTENCE,
    "This stage must not add latency: the offered word is seen by the consumer\n"
    "in the same cycle it is offered. ")

# Same shape with the storage policy simply NOT STATED: must route to AI by name.
_F6_UNSTATED_DESC = _F6_DESC.replace(_F6_STORAGE_SENTENCE, "")

_F7_DESC = (
    "Module name:\n    pulse_divider\n"
    "An event ratio divider.\n"
    "Input ports:\n clk: Clock signal.\n rst_n: Active low reset signal.\n"
    " in_data [7:0]: The 8-bit payload accompanying an input event.\n"
    " in_valid: Pulses high for one cycle on each input event.\n"
    "Output ports:\n out_data [7:0]: The forwarded payload.\n"
    " out_valid: Pulses high for one cycle on each output event.\n"
    "Implementation:\n"
    "The divider emits one output event for every 1 input events. Counting an\n"
    "input event and emitting the output event are the same cycle's work.\n")


def test_sixteen_templates_are_byte_identical_to_their_own_text():
    """The contract layer must not re-author a working emitter: every template
    shape still emits exactly its `_TEMPLATES` entry, and `desc_text` is ignored
    for them. Compared by MEMBERSHIP of the shape-key set, not by count."""
    assert set(rcs._TEMPLATES) == {k for k, _ in rcs._DETECTORS}
    for shape, text in rcs._TEMPLATES.items():
        assert rcs.emit_rtl(shape) == text
        assert rcs.emit_rtl(shape, _F6_DESC) == text


def test_stated_directive_withdraws_the_fixed_topology():
    """OLD WRONG BEHAVIOUR, on input-only material: this description matches the
    barrel-shifter detector while forbidding the very structure the template is
    built from, and used to be answered with that template anyway."""
    assert rcs._is_barrel_shifter(
        _ARCH_CONFLICT_DESC, rcs.module_name_of(_ARCH_CONFLICT_DESC),
        rcs._port_tokens(_ARCH_CONFLICT_DESC) - rcs._NOISE) is True
    conflict = rcs.architecture_conflict(
        _ARCH_CONFLICT_DESC, "barrel_shifter_right_8")
    assert conflict is not None
    assert conflict["polarity"] == "forbid"
    assert conflict["property"] in {"submodule_instantiation", "generate_block"}
    assert rcs.detect_shape(_ARCH_CONFLICT_DESC) is None


def test_withdrawn_topology_is_routed_to_ai_by_name():
    """No hidden DEFER: the program says WHICH stated directive it could not
    honour, so the AI author is handed the decision rather than guessing it."""
    why = rcs.route_to_ai_reason(_ARCH_CONFLICT_DESC)
    assert why is not None and why["route"] == "ai_author"
    assert why["kind"] == "architecture_conflict"
    assert why["shape_declined"] == "barrel_shifter_right_8"
    assert "must not" in why["stated"].lower()


@pytest.mark.parametrize("shape,desc", _INLINE_POS.items())
def test_canonical_descriptions_state_no_conflicting_directive(shape, desc):
    """The withdrawal must not fire on ordinary prose: every canonical
    description still detects its own shape, i.e. the DEFER population grew only
    for inputs that really do state a contradicting directive."""
    assert rcs.architecture_conflict(desc, shape) is None
    assert rcs.detect_shape(desc) == shape


def test_template_commitments_are_derived_from_the_template_text():
    """Commitments are read out of the emitted RTL, so a re-authored template
    cannot leave a hand-written second list behind, stale."""
    barrel = rcs.template_commitments("barrel_shifter_right_8")
    assert {"submodule_instantiation", "generate_block"} <= barrel
    assert "gray_code" not in barrel
    assert "gray_code" in rcs.template_commitments("async_gray_fifo")


def test_f6_contract_is_extracted_from_the_input():
    c = rcs.extract_handshake_contract(_F6_DESC)
    assert c is not None and c.kind == "elastic_stage"
    assert c.unresolved == []
    assert (c.up["valid"], c.up["ready"], c.up["data"]) == (
        "up_valid", "up_ready", "up_data")
    assert (c.down["valid"], c.down["ready"], c.down["data"]) == (
        "dn_valid", "dn_ready", "dn_data")
    assert c.width == 8 and c.storage == "skid" and c.ordering == "fifo"
    assert c.clock == "clk" and c.reset == "rst_n" and c.reset_active_low is True


def test_f6_is_composed_not_templated():
    """F6 is a consumer of the contract layer: no `_TPL_` exists for it, and the
    emitted module carries the INPUT's own module and port names."""
    assert "elastic_handshake_stage" not in rcs._TEMPLATES
    shape = rcs.detect_shape(_F6_DESC)
    assert shape == "elastic_handshake_stage"
    rtl = rcs.emit_rtl(shape, _F6_DESC)
    assert "module elastic_stage (" in rtl
    for port in ("up_valid", "up_ready", "up_data",
                 "dn_valid", "dn_ready", "dn_data"):
        assert port in rtl
    # acceptance-qualified storage: every capture is gated by an ACCEPTED
    # transfer, never by valid alone.
    assert "wire up_fire = up_valid && up_ready;" in rtl
    assert "if (up_fire) held_data <= up_data;" in rtl
    assert "skid_data  <= up_data;" in rtl
    assert "assign up_ready = !skid_valid;" in rtl


def test_f6_alternative_architecture_control_stays_green():
    """THE CONTROL. Same shape words, a legitimately different architecture
    (zero added latency). It must NOT be answered with the buffered stage."""
    c = rcs.extract_handshake_contract(_F6_ALT_DESC)
    assert c is not None and c.unresolved == [] and c.storage == "passthrough"
    rtl = rcs.emit_rtl(rcs.detect_shape(_F6_ALT_DESC), _F6_ALT_DESC)
    assert "assign dn_valid = up_valid;" in rtl
    assert "assign up_ready = dn_ready;" in rtl
    assert "always" not in rtl and "skid" not in rtl
    assert rtl != rcs.emit_rtl(rcs.detect_shape(_F6_DESC), _F6_DESC)


def test_f6_unstated_storage_is_routed_to_ai_by_name_not_guessed():
    assert rcs.detect_shape(_F6_UNSTATED_DESC) is None
    why = rcs.route_to_ai_reason(_F6_UNSTATED_DESC)
    assert why is not None and why["kind"] == "unstated_contract_fields"
    assert why["contract_kind"] == "elastic_stage"
    assert any("storage under backpressure" in u for u in why["unresolved"])


def test_f7_unit_ratio_consume_and_capture_are_simultaneous():
    """F7's defect is that consume and capture are exclusive, which drops every
    other input at a unit ratio. The composed emitter does both in one cycle."""
    c = rcs.extract_handshake_contract(_F7_DESC)
    assert c is not None and c.kind == "ratio_divider"
    assert c.ratio == 1 and c.unresolved == []
    assert "event_ratio_divider" not in rcs._TEMPLATES
    rtl = rcs.emit_rtl(rcs.detect_shape(_F7_DESC), _F7_DESC)
    assert "module pulse_divider #(" in rtl
    assert "wire consume  = in_valid;" in rtl
    assert "wire emit_now = in_valid && (count == RATIO - 1);" in rtl
    # the two are separate concurrent facts about the same cycle, never an
    # if/else between consuming and capturing
    assert "out_valid <= emit_now;" in rtl
    assert "if (in_valid) out_data <= in_data;" in rtl
    assert "else if" not in rtl.split("end else begin")[1]


def test_generated_scoreboards_come_from_the_same_contract():
    """The queue scoreboard (F6) and the ratio/latency count (F7) that #2035 asks
    for are composed from the contract fields, so a stage and its check cannot
    drift apart."""
    tb6 = rcs.emit_scoreboard_tb(rcs.extract_handshake_contract(_F6_DESC))
    assert "module tb_elastic_stage;" in tb6
    assert "if (up_valid && up_ready) begin q[wr]" in tb6
    assert "accepted transfers lost" in tb6
    tb7 = rcs.emit_scoreboard_tb(rcs.extract_handshake_contract(_F7_DESC))
    assert "module tb_pulse_divider;" in tb7
    assert "if (n_out * 1 != n_in)" in tb7
    for tb in (tb6, tb7):
        assert tb.isascii()


def test_contract_shapes_refuse_to_emit_without_their_input():
    """A composed shape has no fixed answer to fall back on: asked to emit with
    no description, it raises rather than inventing a topology."""
    for shape in rcs._CONTRACT_SHAPES:
        with pytest.raises((ValueError, KeyError)):
            rcs.emit_rtl(shape)


@pytest.mark.parametrize("desc", _INLINE_NEG)
def test_contract_layer_does_not_mis_fire_on_near_misses(desc):
    """Fail-closed is preserved: the contract layer is consulted only when no
    template claimed the input, and it declines everything that states no
    handshake."""
    assert rcs.detect_shape(desc) is None


# ============================================================================
# The second half of the same exposure: a STATED BEHAVIOUR, not a stated
# architecture. An input that matches a shape's words while stating the other
# reset behaviour used to be answered with the template anyway.
#
# Measured on the base, independently of the program (a raw scan of the sixteen
# template texts): 11 templates reset ASYNCHRONOUSLY, 3 SYNCHRONOUSLY, and 2 are
# combinational -- and nothing compared that with what the description said.
# Both sides are decidable here, which is why this dimension is closed and the
# shift-direction one (see the lane's LAND.md) is not: the pole is read out of
# the template's own always-block and reset test, never out of its prose.
# ============================================================================

_ASYNC_TEMPLATES = {
    "async_gray_fifo", "frac_clock_divider_3p5", "mealy_seq_detector_10011",
    "odd_clock_divider", "parallel_to_serial_4", "pipelined_ripple_adder_64",
    "pipelined_unsigned_multiplier_8", "pulse_detect_0to1to0",
    "serial_to_parallel_8", "traffic_light_fsm", "triangle_wave_generator_5",
}
_SYNC_TEMPLATES = {
    "ieee754_single_multiplier", "lfsr4_xnor_left", "radix2_signed_divider",
}
_COMBINATIONAL_TEMPLATES = {
    "barrel_shifter_right_8", "combinational_long_divider",
}


def test_reset_poles_are_derived_from_the_template_code():
    """Compared by MEMBERSHIP against a partition established by reading the
    template texts directly, so a template that is re-authored to reset the
    other way moves its own commitment with it."""
    derived_async = {k for k in rcs._TEMPLATES
                     if "async_reset" in rcs.template_commitments(k)}
    derived_sync = {k for k in rcs._TEMPLATES
                    if "sync_reset" in rcs.template_commitments(k)}
    derived_none = {k for k in rcs._TEMPLATES
                    if not {"async_reset", "sync_reset"}
                    & rcs.template_commitments(k)}
    assert derived_async == _ASYNC_TEMPLATES
    assert derived_sync == _SYNC_TEMPLATES
    assert derived_none == _COMBINATIONAL_TEMPLATES
    assert "active_low_reset" in rcs.template_commitments("odd_clock_divider")
    assert "active_high_reset" in rcs.template_commitments("lfsr4_xnor_left")


def test_no_canonical_description_conflicts_with_its_own_template():
    """Zero false positives on the population that must never move, and NOT
    vacuous: several of these descriptions really do state a pole, and it
    agrees."""
    stated = 0
    for shape, desc in _INLINE_POS.items():
        poles = rcs.extract_stated_reset_poles(desc)
        stated += bool(poles)
        assert rcs.architecture_conflict(desc, shape) is None, shape
        assert rcs.detect_shape(desc) == shape
    assert stated >= 6


def _flip_reset_pole(desc, pole):
    """Rewrite a description to state the OPPOSITE pole of `pole`."""
    if pole == "active_low_reset":
        return re.sub(r"[Aa]ctive[- ]low", "Active high", desc)
    if pole == "active_high_reset":
        flipped = re.sub(r"[Aa]ctive[- ]high", "Active low", desc)
        return flipped if flipped != desc else desc + "rst: Active low reset.\n"
    if pole == "async_reset":
        return desc + "The reset is a synchronous reset.\n"
    return desc + "The reset is an asynchronous reset.\n"


_POLE_CASES = [(shape, pole)
               for shape, desc in _INLINE_POS.items()
               for pole in sorted(p for p in rcs.template_commitments(shape)
                                  if p.endswith("_reset"))
               if _flip_reset_pole(desc, pole) != desc]


@pytest.mark.parametrize("shape,pole", _POLE_CASES)
def test_stating_the_opposite_reset_pole_withdraws_the_template(shape, pole):
    """The other direction, per shape: state the pole the template does NOT
    implement and the template is withdrawn and the pole is NAMED."""
    flipped = _flip_reset_pole(_INLINE_POS[shape], pole)
    conflict = rcs.architecture_conflict(flipped, shape)
    assert conflict is not None and conflict["polarity"] == "stated"
    assert conflict["property"] == rcs._OPPOSITE_POLE[pole]
    assert rcs.detect_shape(flipped) is None
    why = rcs.route_to_ai_reason(flipped)
    assert why is not None and why["property"] == rcs._OPPOSITE_POLE[pole]


def test_a_description_stating_both_poles_records_neither():
    """Contradictory input is not a licence to pick: when both poles of a pair
    are stated the program records no pole and keeps its previous behaviour."""
    both = (_INLINE_POS["odd_clock_divider"]
            + "rst_n: Active high reset.\n")
    assert "active low" in both.lower() and "active high" in both.lower()
    assert rcs.extract_stated_reset_poles(both) == set()
    assert rcs.detect_shape(both) == "odd_clock_divider"


def test_a_pole_said_about_another_signal_is_not_a_reset_statement():
    """`active low` on a non-reset pin must not be read as a reset statement."""
    desc = (_INLINE_POS["odd_clock_divider"]
            + " enable_n: An active high enable that gates the divider.\n")
    assert rcs.extract_stated_reset_poles(desc) == {"active_low_reset"}
    assert rcs.detect_shape(desc) == "odd_clock_divider"


# ============================================================================
# The composed check has to SHIP, or a human has to remember to run it. When the
# runner composes a contract shape it now publishes the scoreboard the same
# contract produced, next to the RTL, under the author guard.
# ============================================================================

def _mk_contract_project(tmp_path, desc_text):
    idoc = tmp_path / "phase1" / "input_doc"
    idoc.mkdir(parents=True)
    (idoc / "design_description.txt").write_text(desc_text)
    return tmp_path


def test_composed_shape_publishes_its_scoreboard(tmp_path):
    R = _load_runner()
    proj = _mk_contract_project(tmp_path / "p", _F6_DESC)
    res = R._try_canonical_primitive_rtl(proj, 0.0)
    assert res is not None and res.status == "PASS"
    assert res.extras["shape"] == "elastic_handshake_stage"
    tb = proj / "phase2" / "stage1" / "tb" / "tb_elastic_stage.v"
    assert tb.is_file()
    assert res.extras["scoreboard_tb"] == str(tb)
    assert str(tb) in res.output_files
    body = tb.read_text()
    assert "module tb_elastic_stage;" in body
    assert "accepted transfers lost" in body


def test_scoreboard_never_overwrites_an_authors_testbench(tmp_path):
    R = _load_runner()
    proj = _mk_contract_project(tmp_path / "p", _F6_DESC)
    tb = proj / "phase2" / "stage1" / "tb" / "tb_elastic_stage.v"
    tb.parent.mkdir(parents=True)
    tb.write_text("// an author's own testbench\n")
    res = R._try_canonical_primitive_rtl(proj, 0.0)
    assert res is not None and res.status == "PASS"
    assert tb.read_text() == "// an author's own testbench\n"
    assert "kept the existing" in res.extras["scoreboard_tb"]
    assert str(tb) not in res.output_files


def test_template_shapes_publish_no_scoreboard(tmp_path):
    """The sixteen fixed templates own no contract, so nothing new appears next
    to them: this wiring is additive for the composed shapes only."""
    R = _load_runner()
    proj = _mk_contract_project(tmp_path / "p",
                                _INLINE_POS["pulse_detect_0to1to0"])
    res = R._try_canonical_primitive_rtl(proj, 0.0)
    assert res is not None and res.status == "PASS"
    assert res.extras["shape"] == "pulse_detect_0to1to0"
    assert res.extras.get("scoreboard_tb") is None
    assert not (proj / "phase2" / "stage1" / "tb").exists()
    assert res.output_files == [
        str(proj / "phase2" / "stage1" / "rtl" / "pulse_detect.v")]


# ============================================================================
# The published scoreboard lands in phase2/stage1/tb/, which `l12_tb_coverage_
# check` READS. Measured on a composed project: that gate goes from rc=2 ("TB
# dir not found" -- it measured nothing) to rc=1 (it measured, and the design is
# genuinely short of the L12 sequences). That is the honest direction, but the
# property that must never rot is that a generic scoreboard is not mistaken for
# coverage of a named behavioural sequence.
# ============================================================================

def _run_l12(project):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "l12_tb_coverage_check.py"), str(project)],
        capture_output=True, text=True)


def _composed_project_with_l12(tmp_path, sequence_ids):
    R = _load_runner()
    proj = _mk_contract_project(tmp_path / "p", _F6_DESC)
    res = R._try_canonical_primitive_rtl(proj, 0.0)
    assert res is not None and res.status == "PASS"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L12_BEHAVIORAL_SEQUENCES.json").write_text(json.dumps(
        {"sequences": [{"id": s, "description": s.lower()} for s in sequence_ids]}))
    return proj


def test_scoreboard_is_not_mistaken_for_l12_sequence_coverage(tmp_path):
    proj = _composed_project_with_l12(
        tmp_path, ["BACKPRESSURE_STALL_RECOVERY", "RESET_MID_TRANSFER"])
    run = _run_l12(proj)
    assert run.returncode == 1, run.stdout + run.stderr
    report = json.loads(
        (proj / "reports" / "phase2" / "gates" / "l12_tb_coverage.json").read_text())
    assert report["tb_dir"].endswith("phase2/stage1/tb")
    assert report["total_sequences"] == 2
    assert report["covered_sequences"] == 0


def test_the_l12_gate_really_can_see_that_directory(tmp_path):
    """The control for the test above: if the gate could not read the published
    scoreboard at all, 'zero coverage' would prove nothing. A sequence whose id
    the scoreboard does contain IS reported covered."""
    proj = _composed_project_with_l12(tmp_path, ["TB_ELASTIC_STAGE"])
    tb = proj / "phase2" / "stage1" / "tb" / "tb_elastic_stage.v"
    assert "tb_elastic_stage" in tb.read_text()
    run = _run_l12(proj)
    report = json.loads(
        (proj / "reports" / "phase2" / "gates" / "l12_tb_coverage.json").read_text())
    assert report["covered_sequences"] == 1, run.stdout + run.stderr
    assert run.returncode == 0


# ============================================================================
# WHAT A DETECTOR NEVER LOOKS AT, IT CANNOT REFUSE.
#
# `barrel_left` -- an input matching the barrel-shifter detector while asking for
# a shift in the other direction -- is still answered with the right-shift
# template, and three attempts to close that measured why it is not free:
#
#   1. prose-derived behavioural poles are unreliable: scanning the sixteen
#      templates' own header comments for six polar pairs, ieee754 reads as
#      "left shift"/"signed" from incidental mantissa wording and two more read
#      as BOTH poles of signedness -- 2 of 16 misleading before any input;
#   2. code-derived shift direction is an IMPLEMENTATION detail, not the block's
#      behaviour: of the five templates that yield an unambiguous pole from
#      their code, three (gray-code FIFO, partial-product multiplier, restoring
#      divider) shift internally for reasons unrelated to what they promise;
#   3. the general table-free rule -- "if the input states a polar dimension the
#      matched detector never examines, DEFER" -- costs exactly one canonical
#      shape: parallel_to_serial_4's description states MSB-first and its
#      detector examines conversion wording, not bit order.
#
# That price is a decision, not a defect, so nothing here changes behaviour. What
# this test DOES do is stop the blindness growing silently: a new shape, or an
# edited detector, that leaves a stated polar dimension unexamined fails here and
# has to be looked at by a person.
# ============================================================================

_POLAR_DIMENSIONS = {
    "shift_direction": ("left", "right"),
    "bit_order": ("msb", "lsb", "most significant", "least significant"),
    "signedness": ("signed", "unsigned"),
    "clock_edge": ("rising edge", "falling edge", "posedge", "negedge",
                   "double-edge"),
}

# The one known blind spot, named rather than tolerated silently. Its template IS
# MSB-first, so today's answer is right; nothing checks that it stays right.
_KNOWN_UNEXAMINED = {("parallel_to_serial_4", "bit_order")}


def _detector_literals(shape):
    """Every string literal the detector for `shape` tests, read from source.

    Introspection, not a hand-maintained list: an edited detector moves this on
    its own."""
    import ast as _ast
    fn_name = dict(rcs._DETECTORS)[shape].__name__
    src = (PROGRAMS / "canonical_primitive_synth.py").read_text()
    for node in _ast.parse(src).body:
        if isinstance(node, _ast.FunctionDef) and node.name == fn_name:
            return {n.value.lower() for n in _ast.walk(node)
                    if isinstance(n, _ast.Constant) and isinstance(n.value, str)}
    raise AssertionError(f"detector source for {shape} not found")


@pytest.mark.parametrize("shape,desc", _INLINE_POS.items())
def test_a_stated_polar_dimension_is_one_the_detector_examines(shape, desc):
    examined = " | ".join(sorted(_detector_literals(shape)))
    low = desc.lower()
    for dim, words in _POLAR_DIMENSIONS.items():
        if not any(w in low for w in words):
            continue                      # the input states nothing here
        if (shape, dim) in _KNOWN_UNEXAMINED:
            continue                      # the recorded exception, above
        assert any(w in examined for w in words), (
            f"{shape} answers a description that states {dim}, but its detector "
            f"never examines that dimension: an input stating the other pole "
            f"would get this template anyway")


def test_the_known_blind_spot_is_still_exactly_one():
    """If this fails, a shape has been added or a detector edited so that the
    blindness above grew. That is the moment to take the decision, not later."""
    blind = set()
    for shape, desc in _INLINE_POS.items():
        examined = " | ".join(sorted(_detector_literals(shape)))
        low = desc.lower()
        for dim, words in _POLAR_DIMENSIONS.items():
            if any(w in low for w in words) and not any(w in examined
                                                        for w in words):
                blind.add((shape, dim))
    assert blind == _KNOWN_UNEXAMINED


# ============================================================================
# A CHECK THAT CANNOT FAIL IS NOT A CHECK. Measured by mutating the composed RTL
# 13 valid ways and running each against the generated scoreboard: the first
# version killed 9 and let three through, of which two were real holes --
#   * a stage that back-pressures when it does not have to passed at reduced
#     throughput (59 transfers instead of 82): correctness was checked, the
#     contract's "stalled only when no slot is free" clause was not;
#   * a stage whose reset never clears passed with ZERO transfers observed --
#     a vacuous pass, the checker reporting success on a run that did nothing.
# (The third, an unconditional capture inside the branch where up_ready is
# already high, survives CORRECTLY -- and the claim is bounded-PROVED rather than
# argued: yosys `miter -equiv` + `sat -seq 24 -set-init-zero -prove-asserts`
# reports SUCCESS on the OBSERVABLE interface {up_ready, dn_valid, dn_data
# qualified by dn_valid}. The unqualified comparison does NOT prove -- dn_data
# genuinely differs while dn_valid is low -- so "equivalent" here means
# observationally equivalent, not bit-identical. The same harness FAILS on the
# m6 stall mutant, so it is not a proof that proves anything.)
# Both holes are closed in the generator, so every composed design gets the
# stronger check; the kill rate is now 12 of 13. Evidence: the lane's killtest/.
# ============================================================================

def test_the_elastic_scoreboard_checks_the_no_needless_stall_clause():
    tb = rcs.emit_scoreboard_tb(rcs.extract_handshake_contract(_F6_DESC))
    assert "stalled at cycle" in tb
    assert "if (!up_ready) begin" in tb


def test_neither_scoreboard_can_pass_vacuously():
    tb6 = rcs.emit_scoreboard_tb(rcs.extract_handshake_contract(_F6_DESC))
    assert "if (rd < 32) begin" in tb6
    assert "only %0d transfers observed" in tb6
    tb7 = rcs.emit_scoreboard_tb(rcs.extract_handshake_contract(_F7_DESC))
    assert "if (n_in == 0) begin" in tb7
    assert "vacuous" in tb7
