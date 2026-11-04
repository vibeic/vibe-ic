"""The selected generator source owns its contract and author handoff."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import ai_signed_judgement as judgement
import design_one_shot_runner as runner
import rtl_provenance


PROSE = "Every primitive in the final netlist has to be a Sheffer stroke.\n"
TABLE = {
    "module": "selected_table",
    "inputs": [{"name": "a"}], "outputs": [{"name": "q"}],
    "rows": [{"in": "0", "out": "1"}, {"in": "1", "out": "0"}],
    "default": "0",
}
KMAP = """Implement a module named TopModule.
 - input a
 - input b
 - output q
The module should implement the function shown in the Karnaugh map below.
       a
  b   0   1
  0 | 0 | 1 |
  1 | 1 | 0 |
"""
CLASSES = (
    "data_converter", "mixed_signal_otp", "aid_class_half_duplex_single_wire",
    "zzz_unregistered", "digital_arithmetic_primitive",
)
RAW_PATHS = ("phase1/input_doc/design.md", "phase1/input_prompt/prompt.txt")
CANONICAL_PULSE = (
    "Module name:\n    pulse_detect\n"
    "Pulse detection: when data_in changes from 0 to 1 to 0 this is a pulse.\n"
    "Input ports:\n clk: Clock.\n rst_n: Reset.\n"
    " data_in: One-bit input.\n"
    "Output ports:\n data_out: pulse indicator.\n")
REVIEWER_YAML = """description: |
  Module name:
      pulse_detect
  Pulse detection: when data_in changes from 0 to 1 to 0 this is a pulse.
  Input ports:
   clk: Clock.
   rst_n: Reset.
   data_in: One-bit input.
  Output ports:
   data_out: pulse indicator.
  Keep the silicon footprint as tiny as you possibly can.
"""
BEHAVIORAL_FSM = (
    PROGRAMS / "tests/fixtures/real_benchmark/directional_bump_fall_moore_prompt.md"
).read_text()
RESET_PULSE = """Implement a module named TopModule.
 - input clk
 - input reset
 - output shift_ena
The reset is synchronous and active-high.
Assert shift_ena for exactly 4 clock cycles, then 0 forever until reset.
"""
HALF_ADDER = """I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  a
 - input  b
 - output sum
 - output cout

The module should implement a half adder. A half adder adds two bits
(with no carry-in) and produces a sum and carry-out.
"""
RESTRICTIONS = (
    ("", "SPEC_SENTENCES_UNACCOUNTED"),
    ("Use only NAND gates.\n", "DECLARED_LOGIC_OBLIGATION_UNSUPPORTED"),
    ("Minimize the number of gates.\n", "DECLARED_LOGIC_OBLIGATION_UNSUPPORTED"),
    (PROSE, "SPEC_SENTENCES_UNACCOUNTED"),
)


def _reset_session():
    if runner._RTL_SESSION_BINDING is not None:
        runner._RTL_SESSION_BINDING.close()
    runner._RTL_SESSION_BINDING = None
    runner._RTL_SESSION_OWNED = False
    runner._RTL_SESSION_PROJECT = None


@pytest.fixture(autouse=True)
def _isolated_session():
    _reset_session()
    yield
    _reset_session()


def _write(project, rel, text):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _json(project, rel, data):
    return _write(project, rel, json.dumps(data))


@pytest.mark.parametrize("rel", [
    "phase2/stage1/rtl_spec.json", "phase2/rtl_spec.json", "input/rtl_spec.json",
    "phase2/stage1/rtl_spec.yaml", "phase2/rtl_spec.yaml", "input/rtl_spec.yaml"])
def test_selected_structured_source_ignores_unconsumed_prose(tmp_path, rel):
    import yaml
    data = yaml.safe_dump(TABLE) if rel.endswith("yaml") else json.dumps(TABLE)
    _write(tmp_path, rel, data)
    _write(tmp_path, "phase1/input_doc/design.md", PROSE)
    result = runner.step_rtl_gen(tmp_path, "__neutral_logic__")
    assert result.status == "PASS", result.detail
    assert result.extras["deterministic_generator"] == "truth-table"
    assert (tmp_path / "phase2/stage1/rtl/selected_table.sv").is_file()
    assert not (tmp_path / "phase2/stage1/fallback_skill.md").exists()


@pytest.mark.parametrize("ic_class", CLASSES)
@pytest.mark.parametrize("include_prose", [False, True], ids=["structured-only", "mixed"])
def test_typed_canonical_description_is_consumed_without_operator_prose(
        tmp_path, ic_class, include_prose):
    description = (
        "Module name: pulse_detect. "
        "Pulse detection: when data_in changes from 0 to 1 to 0 this is a pulse. "
        "clk (input), rst_n (input), data_in (input), data_out (output).")
    _json(tmp_path, "phase1/generated_docs/L2_FRS.json", {"description": description})
    _json(tmp_path, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {
        "top_module": "pulse_detect", "top_ports": [
            {"name": name, "direction": direction, "width": 1}
            for name, direction in (("clk", "input"), ("rst_n", "input"),
                                    ("data_in", "input"), ("data_out", "output"))]})
    if include_prose:
        _write(tmp_path, "phase1/input_doc/design.md", PROSE)
    result = runner.step_rtl_gen(tmp_path, ic_class)
    assert result.status == "PASS", result.detail
    assert result.extras["deterministic_generator"] == "canonical_primitive_synth"
    assert (tmp_path / "phase2/stage1/rtl/pulse_detect.v").is_file()
    assert not (tmp_path / "phase2/stage1/fallback_skill.md").exists()


@pytest.mark.parametrize("ic_class", CLASSES)
@pytest.mark.parametrize("rel", RAW_PATHS)
def test_fully_accounted_raw_kmap_keeps_program_first_pass(tmp_path, ic_class, rel):
    _write(tmp_path, rel, KMAP)
    result = runner.step_rtl_gen(tmp_path, ic_class)
    assert result.status == "PASS", result.detail
    assert result.extras["deterministic_generator"]
    assert (tmp_path / "phase2/stage1/rtl/chip_top.sv").is_file()
    assert not (tmp_path / "phase2/stage1/fallback_skill.md").exists()


@pytest.mark.parametrize("ic_class", CLASSES)
@pytest.mark.parametrize("rel", RAW_PATHS)
@pytest.mark.parametrize("text", [CANONICAL_PULSE, REVIEWER_YAML],
                         ids=["raw-canonical", "reviewer-yaml"])
def test_unaccounted_raw_canonical_source_requires_named_handoff(
        tmp_path, ic_class, rel, text):
    _write(tmp_path, rel, text)
    result = runner.step_rtl_gen(tmp_path, ic_class)
    assert result.status == "PASS", result.detail
    assert result.extras["deterministic_generator"] == "canonical_primitive_synth"
    assert Path(result.output_files[0]).is_file()
    assert not (tmp_path / "phase2/stage1/fallback_skill.md").exists()


@pytest.mark.parametrize("ic_class", CLASSES)
@pytest.mark.parametrize("rel", RAW_PATHS)
@pytest.mark.parametrize("restriction,marker", RESTRICTIONS,
                         ids=["plain", "nand", "minimize", "sheffer"])
def test_unaccounted_raw_behavioral_source_requires_named_handoff(
        tmp_path, ic_class, rel, restriction, marker):
    _write(tmp_path, rel, RESET_PULSE + "\n" + restriction)
    result = runner.step_rtl_gen(tmp_path, ic_class)
    if marker == "DECLARED_LOGIC_OBLIGATION_UNSUPPORTED":
        assert result.status == "PASS_WITH_WAIVERS", result.detail
        assert marker in result.detail
        assert result.extras["fallback_skill"] == "spec-to-rtl"
        assert not result.output_files
    else:
        assert result.status == "PASS", result.detail
        assert result.extras["deterministic_generator"]
        assert Path(result.output_files[0]).is_file()


@pytest.mark.parametrize("ic_class", CLASSES)
@pytest.mark.parametrize("rel", RAW_PATHS)
def test_unaccounted_closed_behavioral_source_requires_named_handoff(
        tmp_path, ic_class, rel):
    _write(tmp_path, rel, BEHAVIORAL_FSM)
    result = runner.step_rtl_gen(tmp_path, ic_class)
    assert result.status == "PASS", result.detail
    assert Path(result.output_files[0]).is_file()


@pytest.mark.parametrize("ic_class", CLASSES)
@pytest.mark.parametrize("rel", RAW_PATHS)
@pytest.mark.parametrize("restriction,marker", RESTRICTIONS,
                         ids=["plain", "nand", "minimize", "sheffer"])
def test_unaccounted_raw_registry_source_requires_named_handoff(
        tmp_path, ic_class, rel, restriction, marker):
    _write(tmp_path, rel, HALF_ADDER + "\n" + restriction)
    result = runner.step_rtl_gen(tmp_path, ic_class)
    if marker == "DECLARED_LOGIC_OBLIGATION_UNSUPPORTED":
        assert result.status == "PASS_WITH_WAIVERS", result.detail
        assert marker in result.detail
        assert result.extras["fallback_skill"] == "spec-to-rtl"
        assert not result.output_files
    else:
        assert result.status == "PASS", result.detail
        assert result.extras["deterministic_generator"] == "arithmetic"
        assert Path(result.output_files[0]).is_file()


@pytest.mark.parametrize("ic_class", CLASSES[:3])
@pytest.mark.parametrize("declaration", ["empty", "foreign"])
def test_typed_prose_uses_l9_logic_field_override(tmp_path, ic_class, declaration):
    clause = "Use only NAND gates."
    declared = [] if declaration == "empty" else [{
        "kind": "logic_basis", "family": ["nand"],
        "source_span": [0, len(clause)], "source_sentence": clause,
        "module": "foreign_module"}]
    _write(tmp_path, "phase1/input_doc/design.md", KMAP + clause + "\n")
    _json(tmp_path, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {
        "top_module": "TopModule", "logic_obligations": declared})
    result = runner.step_rtl_gen(tmp_path, ic_class)
    assert result.status == "PASS", result.detail
    assert result.extras["deterministic_generator"] == "karnaugh_map"
    assert Path(result.output_files[0]).is_file()


@pytest.mark.parametrize("complete", [False, True], ids=["named-fail", "typed-pass"])
def test_emitter_error_is_reported_before_ai_backup(
        tmp_path, monkeypatch, capsys, complete):
    import spec_artifact_registry as registry
    _write(tmp_path, "phase1/input_doc/design.md", PROSE)
    _json(tmp_path, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {
        "top_module": "converter", "top_ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "rst", "direction": "input", "width": 1},
            {"name": "data", "direction": "input", "width": 1},
            {"name": "result", "direction": "output", "width": 16}]})
    specs = [{"name": "osr", "target": 64}]
    if complete:
        specs += [{"name": "decimator_stages", "target": 3},
                  {"name": "decimator_differential_delay", "target": 1},
                  {"name": "bitstream_width", "target": 1}]
    _json(tmp_path, "phase1/generated_docs/L5_ADI_SPEC.json", {
        "analog_blocks": [{"spec": {"specs": specs}}]})

    def unavailable(*args, **kwargs):
        raise RuntimeError("injected pure applicability failure")

    monkeypatch.setattr(registry, "generate", unavailable)
    result = runner.step_rtl_gen(tmp_path, "data_converter")
    assert result.status == "NOT_MEASURED", result.detail
    assert "emitter raised (RuntimeError)" in result.detail
    assert "deferring to the AI backup" in result.detail
    assert not result.output_files


@pytest.mark.parametrize("rel", ["phase1/input_doc/design.md", "phase1/input_prompt/prompt.txt"])
def test_l9_serial_source_precedes_unconsumed_prose(tmp_path, rel):
    _json(tmp_path, "phase1/generated_docs/L2_FRS.json", {
        "ic_name": "serial_product", "frs_sections": [{"content":
            "serial-parallel multiplier: p = (x * y) mod 2^N; synchronous active-high reset"}]})
    _json(tmp_path, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {
        "top_module": "serial_product", "top_ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "rst", "direction": "input", "width": 1},
            {"name": "x", "direction": "input", "width": "size-1:0",
             "width_symbolic": "size-1:0", "msb": "size-1", "lsb": "0"},
            {"name": "y", "direction": "input", "width": 1},
            {"name": "p", "direction": "output", "width": 1}]})
    _write(tmp_path, rel, PROSE)
    result = runner.step_rtl_gen(tmp_path, "digital_arithmetic_primitive")
    assert result.status == "PASS", result.detail
    assert result.extras["deterministic_generator"] == "serial_parallel_mul_synth"
    assert (tmp_path / "phase2/stage1/rtl/serial_product.v").is_file()


def test_malformed_selected_structured_source_keeps_named_fail(tmp_path):
    _write(tmp_path, "input/rtl_spec.json", "{invalid json")
    _write(tmp_path, "phase1/input_doc/design.md", PROSE)
    result = runner.step_rtl_gen(tmp_path, "__neutral_logic__")
    assert result.status == "FAIL", result.detail
    assert "deterministic_rtl_dispatcher rejected rtl_spec.json" in result.detail


def test_author_handoff_stages_existing_inputs_and_requires_signature(tmp_path):
    text = ("A bit-serial arithmetic datapath computes p = (x * y) mod 2^N.\n" + PROSE)
    _write(tmp_path, "phase1/input_doc/design.md", text)
    _write(tmp_path, "phase1/generated_docs/L7_VERIFICATION_PLAN.md", """The Plugin MUST declare `plugin_output/declaration.json` before authoring:
| Field | Required | Example |
|---|---|---|
| `bit_order` | Yes | `"LSB_first"` |
""")
    result = runner.step_rtl_gen(tmp_path, "__neutral_logic__")
    assert result.status == "PASS_WITH_WAIVERS", result.detail
    stage = tmp_path / "phase2/stage1"
    for name in ("fallback_skill.md", "lessons.md", "ic_expert_db.md",
                 "lessons_scoring_record.json", "declaration_contract.json"):
        assert (stage / name).is_file(), name
    assert "READ THE SKILL AT THIS PATH" in result.detail
    assert "MANDATORY before authoring" in result.detail
    _write(tmp_path, "phase2/stage1/rtl/authored.sv", "module authored; endmodule\n")
    accepted, why = judgement.check(tmp_path, "1")
    assert not accepted, why
    assert "awaiting_signed_judgement" in why


def test_escaping_project_link_precedes_prose_handoff(tmp_path):
    project = tmp_path / "project"
    _write(project, "phase1/input_doc/design.md", PROSE)
    (project / "escape").symlink_to(tmp_path)
    result = runner.step_rtl_gen(project, "__neutral_logic__")
    assert result.status == "NOT_MEASURED", result.detail
    assert "PROJECT_SYMLINK_NOT_ISOLATABLE" in result.detail
    assert not (project / "phase2/stage1/fallback_skill.md").exists()


def test_named_adc_generator_refusal_stays_fail_with_prose(tmp_path):
    _write(tmp_path, "phase1/input_doc/design.md", PROSE)
    _json(tmp_path, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {
        "top_module": "converter", "top_ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "rst", "direction": "input", "width": 1},
            {"name": "data", "direction": "input", "width": 1},
            {"name": "result", "direction": "output", "width": 16}]})
    _json(tmp_path, "phase1/generated_docs/L5_ADI_SPEC.json", {
        "analog_blocks": [{"spec": {"specs": [{"name": "osr", "target": 64}]}}]})
    result = runner.step_rtl_gen(tmp_path, "data_converter")
    assert result.status == "FAIL", result.detail
    assert "does not state the number of decimator stages" in result.detail
    assert not (tmp_path / "phase2/stage1/fallback_skill.md").exists()


def test_typed_adc_generator_still_emits_with_unconsumed_prose(tmp_path):
    _write(tmp_path, "phase1/input_doc/design.md", PROSE)
    _json(tmp_path, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {
        "top_module": "converter", "top_ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "rst", "direction": "input", "width": 1},
            {"name": "data", "direction": "input", "width": 1},
            {"name": "result", "direction": "output", "width": 16}]})
    _json(tmp_path, "phase1/generated_docs/L5_ADI_SPEC.json", {
        "analog_blocks": [{"spec": {"specs": [
            {"name": "osr", "target": 64},
            {"name": "decimator_stages", "target": 3},
            {"name": "decimator_differential_delay", "target": 1},
            {"name": "bitstream_width", "target": 1}]}}]})
    result = runner.step_rtl_gen(tmp_path, "data_converter")
    assert result.status == "PASS", result.detail
    assert "data_converter_rtl_gen.py" in result.detail
    assert (tmp_path / "phase2/stage1/rtl/cic_decimator.sv").is_file()
    assert not (tmp_path / "phase2/stage1/fallback_skill.md").exists()


def test_changed_prose_keeps_old_rtl_and_requires_signature_after_authorship(tmp_path):
    source = _write(tmp_path, "phase1/input_doc/design.md", KMAP)
    initial = runner.step_rtl_gen(tmp_path, "__neutral_logic__")
    assert initial.status == "PASS", initial.detail
    rtl = tmp_path / "phase2/stage1/rtl/chip_top.sv"
    old = rtl.read_bytes()
    rtl_provenance.stamp(tmp_path, "deterministic_emit_chain")
    _reset_session()
    source.write_text(KMAP + PROSE)
    result = runner.step_rtl_gen(tmp_path, "__neutral_logic__")
    assert result.status == "PASS", result.detail
    assert rtl.read_bytes() == old
    assert result.extras["deterministic_generator"]
    assert not result.extras.get("fallback_skill")


@pytest.mark.parametrize("ic_class", CLASSES[:3])
@pytest.mark.parametrize("rel", RAW_PATHS)
@pytest.mark.parametrize("restriction", ["", PROSE], ids=["original", "sheffer"])
def test_typed_non_registry_chain_source_requires_named_handoff(
        tmp_path, ic_class, rel, restriction):
    import bit_mapping_synth
    import spec_numeric_pack_extract
    from test_issue2215_bit_mapping_synth import CONDITIONAL
    text = "Module name: mapper.\n" + CONDITIONAL + "\n" + restriction
    plan = bit_mapping_synth.plan(spec_numeric_pack_extract.extract(text), module="chip_top")
    assert plan["status"] == "READY", plan["reasons"]
    _write(tmp_path, rel, text)
    result = runner.step_rtl_gen(tmp_path, ic_class, force_regen=True)
    assert result.status == "PASS", result.detail
    assert result.extras["deterministic_generator"] == "bit_mapping_synth"
    assert Path(result.output_files[0]).read_text() == bit_mapping_synth.emit_rtl(plan)


@pytest.mark.parametrize("ic_class", CLASSES[:3])
@pytest.mark.parametrize("rel", RAW_PATHS)
@pytest.mark.parametrize("body", [
    "Convert a 4-bit width to a larger width of 8-bit. "
    "Bits result[3:0] always equal sample[3:0].",
    "Convert a 4-bit width to a larger width of 8-bit. "
    "Do not invert any source bit. "
    "Bits result[3:0] are the inverse of sample[3:0]. "
    "Bits result[7:4] are zero.",
], ids=["uncovered-bits", "prohibited-transform"])
def test_typed_nonapplicable_mapping_keeps_named_class_refusal(
        tmp_path, ic_class, rel, body):
    import bit_mapping_synth
    import spec_numeric_pack_extract

    text = "Module name: mapper.\n" + body
    plan = bit_mapping_synth.plan(spec_numeric_pack_extract.extract(text), module="chip_top")
    assert plan["status"] == "REFUSED", plan
    _write(tmp_path, rel, text)
    result = runner.step_rtl_gen(tmp_path, ic_class, force_regen=True)
    assert result.status == "FAIL", result.detail
    expected = "L5_ADI_SPEC" if ic_class == "data_converter" else "EXAMPLE_PROTOCOL-class only"
    assert expected in result.detail
    assert "SPEC_SENTENCES_UNACCOUNTED" not in result.detail
    assert "unaccounted_source_spans" not in result.extras
    assert not any(path.suffix in (".v", ".sv")
                   for path in (tmp_path / "phase2/stage1/rtl").rglob("*"))


@pytest.mark.parametrize('source', ['original', 'structured'])
def test_boilerplate_reaches_the_program_in_each_input_view(tmp_path, source):
    rel = 'input/phase1_prompt.md' if source == 'original' else 'phase1/input_prompt/prompt.txt'
    _write(tmp_path, rel, HALF_ADDER)
    with runner._pl.rtl_input_view(tmp_path, source):
        result = runner.step_rtl_gen(tmp_path, '__neutral_logic__')
    assert result.status == 'PASS', result.detail
    assert result.extras['deterministic_generator'] == 'arithmetic'
    emitted = Path(result.output_files[0]).read_text()
    assert ('module TopModule' if source == 'original' else 'module chip_top') in emitted


def test_unrecognized_prose_reaches_ai_backup(tmp_path):
    _write(tmp_path, 'phase1/input_prompt/prompt.txt',
           'Implement a module named StreamTransform. A custom stream operation will be supplied later.')
    result = runner.step_rtl_gen(tmp_path, '__neutral_logic__')
    assert result.status == 'PASS_WITH_WAIVERS', result.detail
    assert result.extras['fallback_skill'] == 'spec-to-rtl'
    assert not result.output_files


@pytest.mark.parametrize('reset', ['reset_n', 'resetn', 'rst_n'])
def test_sequence_emitter_preserves_the_declared_reset_spelling(reset):
    import behavioral_fsm_synth

    prompt = ('Module name:\n pattern_unit\nInput ports:\n clk: Clock.\n'
              f' {reset}: Active-low reset.\n sample: One-bit serial input.\n'
              'Output ports:\n found: One-bit flag.\n'
              'Detect the sequence 10110 and assert found on a match.')
    rtl = behavioral_fsm_synth.synth(prompt, 'pattern_unit')
    assert rtl
    assert f'input {reset}' in rtl
    assert f'if (!{reset})' in rtl
    assert f'negedge {reset}' in rtl
