"""Smoke tests for sdc_gen.py (Wave 72; renamed Wave 73 / v0.128)."""
import json
import os
import sys
import textwrap
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAM = Path(os.environ.get("SDC_GEN_PROGRAM", str(
    Path(__file__).resolve().parent.parent / "sdc_gen.py")))


def _scaffold(tmp_path: Path, with_wrapper: bool = False,
              clock_mhz: int = 50) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)

    l8 = {"clock_mhz": clock_mhz}
    l9 = {
        "top_module": "chip_top",
        "top_module_pins": [
            {"name": "clk",     "mode": "input"},
            {"name": "reset_n", "mode": "input"},
            {"name": "id_bus",  "mode": "inout"},
        ],
    }
    (proj / "phase1" / "generated_docs" / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))
    (proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    (proj / "phase2" / "stage1" / "rtl" / "chip_top.sv").write_text(
        "module chip_top(input wire clk, input wire reset_n, "
        "inout wire id_bus); endmodule\n")
    # These fixtures intend an externally asynchronous reset/shared bus. The
    # design authors the exceptions explicitly; their names are not authority.
    staged = proj / "input" / "constraints"
    staged.mkdir(parents=True)
    (staged / "design.sdc").write_text(
        "set_false_path -from [get_ports {reset_n}] -to [all_clocks]\n"
        "set_false_path -from [get_ports {id_bus}] -to [all_clocks]\n")
    if with_wrapper:
        (proj / "phase2" / "stage1" / "rtl" / "de10lite_top.sv").write_text(textwrap.dedent("""\
            module de10lite_top (
              input  wire CLOCK_50,
              input  wire [1:0] KEY,
              inout  wire [35:0] GPIO_0
            ); endmodule
        """))
        (staged / "design.sdc").write_text(
            "set_false_path -from [get_ports {KEY[*]}] -to [all_clocks]\n"
            "set_false_path -from [get_ports {GPIO_0[*]}] -to [all_clocks]\n"
            "set_false_path -from [all_clocks] -to [get_ports {GPIO_0[*]}]\n")
    return proj


def test_sdc_gen_l9_only(tmp_path):
    proj = _scaffold(tmp_path, with_wrapper=False, clock_mhz=50)
    cp = _pr.run([sys.executable, str(PROGRAM), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    sdc = proj / "phase2" / "stage1" / "fpga" / "chip_top.sdc"
    assert sdc.is_file()
    text = sdc.read_text()
    assert "create_clock" in text
    assert "20" in text  # 1000/50 = 20 ns
    assert "[get_ports {clk}]" in text
    # reset_n + id_bus async → false_path
    assert "false_path" in text
    assert "reset_n" in text or "id_bus" in text


def test_sdc_gen_with_wrapper(tmp_path):
    proj = _scaffold(tmp_path, with_wrapper=True)
    cp = _pr.run([sys.executable, str(PROGRAM), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    sdc = proj / "phase2" / "stage1" / "fpga" / "de10lite_top.sdc"
    assert sdc.is_file()
    text = sdc.read_text()
    assert "[get_ports {CLOCK_50}]" in text
    # KEY[*] and GPIO_0[*] should appear as false_path groups
    assert "KEY[*]" in text
    assert "GPIO_0[*]" in text


def test_sdc_period_from_clock_mhz(tmp_path):
    proj = _scaffold(tmp_path, with_wrapper=False, clock_mhz=100)
    cp = _pr.run([sys.executable, str(PROGRAM), str(proj)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    sdc = proj / "phase2" / "stage1" / "fpga" / "chip_top.sdc"
    text = sdc.read_text()
    # 1000 / 100 = 10
    assert "-period 10" in text


def _timed_project(tmp_path, synchronous=True, polarity="active_high"):
    proj = _scaffold(tmp_path)
    (proj / "input/constraints/design.sdc").unlink()
    gd = proj / "phase1/generated_docs"
    l9 = {"top_module": "chip_top", "top_ports": [
        {"name": "clk", "direction": "input"},
        {"name": "reset_n", "direction": "input"},
        {"name": "gpio_out", "direction": "output"},
        {"name": "switch_data", "direction": "input"},
        {"name": "id_bus", "direction": "inout"}],
        "reset_domains": [{"name": "reset_n", "synchronous": synchronous,
                           "polarity": polarity}]}
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    (proj / "phase2/stage1/rtl/chip_top.sv").write_text(
        "module chip_top(input wire clk, input wire reset_n, "
        "output wire gpio_out, input wire switch_data, "
        "inout wire id_bus); endmodule\n")
    return proj


def _generate(proj):
    cp = _pr.run([sys.executable, str(PROGRAM), str(proj), "--force"],
                 capture_output=True, text=True)
    path = proj / "phase2/stage1/fpga/chip_top.sdc"
    return cp, path.read_text() if path.exists() else ""


def test_sync_reset_and_named_gpio_are_timed_by_direction(tmp_path):
    for polarity in ("active_high", "active_low"):
        p = _timed_project(tmp_path / polarity, polarity=polarity)
        cp, text = _generate(p)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert "set_false_path" not in text, text
        for port in ("reset_n", "switch_data", "id_bus"):
            assert any("set_input_delay" in ln and "{" + port + "}" in ln
                       for ln in text.splitlines()), text
        for port in ("gpio_out", "id_bus"):
            assert any("set_output_delay" in ln and "{" + port + "}" in ln
                       for ln in text.splitlines()), text
        assert "boundary coverage 5/5" in cp.stdout


def test_explicit_async_reset_is_not_authority_for_a_bidirectional_cut(tmp_path):
    p = _timed_project(tmp_path, synchronous=False)
    cp, text = _generate(p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "set_false_path" not in text, text
    assert any("set_input_delay" in ln and "reset_n" in ln
               for ln in text.splitlines()), text


def test_contradictory_typed_reset_contract_is_refused(tmp_path):
    p = _timed_project(tmp_path)
    gd = p / "phase1/generated_docs"
    (gd / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "clock_and_reset_waveform": {"resets": [
            {"name": "reset_n", "sync": "asynchronous"}]}}))
    cp, text = _generate(p)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "SDC_RESET_CONTRACT_CONTRADICTORY" in cp.stderr
    assert not text


def test_missing_reset_semantics_keeps_timing_and_discloses_scope(tmp_path):
    p = _timed_project(tmp_path)
    f = p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    d = json.loads(f.read_text()); d["reset_domains"][0].pop("synchronous")
    f.write_text(json.dumps(d))
    cp, text = _generate(p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "set_false_path" not in text, text
    assert "SDC_RESET_SEMANTICS_NOT_MEASURED" in cp.stdout


def test_source_declared_io_fraction_reaches_both_directions(tmp_path):
    from _hostpaths import require_repo
    p = _timed_project(tmp_path)
    gd = p / "phase1/generated_docs"
    # Existing neutral calibration input supplies the actual 10ns clock;
    # this is not another hand-typed copy of the changed emitter's answer.
    staged = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                          "programs", "calibration", "cal_full.sdc")
    (p / "input/constraints/design.sdc").write_bytes(staged.read_bytes())
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({"clock_mhz": None}))
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({
        "constraints": {"io_delay": {"default_fraction_percent": 20.0,
        "source": "input/docs/timing.md", "line": 1,
        "evidence": "I/O delay defaults to 20% of the selected period."}}}))
    source = p / "input/docs/timing.md"; source.parent.mkdir(parents=True)
    source.write_text("I/O delay defaults to 20% of the selected period.\n")
    cp, text = _generate(p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "set_input_delay  -clock clk_main -max 2.0" in text, text
    assert "set_output_delay -clock clk_main -max 2.0" in text, text


def test_authored_exception_keeps_its_exact_direction(tmp_path):
    p = _timed_project(tmp_path, synchronous=False)
    line = "set_false_path -from [get_ports {reset_n}] -to [all_clocks]"
    (p / "input/constraints/design.sdc").write_text(line + "\n")
    cp, text = _generate(p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert [ln for ln in text.splitlines() if ln.startswith("set_false_path")] == [line], text
    assert "source=input/constraints/design.sdc:1" in text


def test_authored_exception_unknown_port_is_refused(tmp_path):
    p = _timed_project(tmp_path)
    (p / "input/constraints/design.sdc").write_text(
        "set_false_path -from [get_ports {absent_pin}] -to [all_clocks]\n")
    cp, text = _generate(p)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "SDC_EXCEPTION_PORT_UNKNOWN" in cp.stderr
    assert not text


def test_authored_exception_clock_label_maps_by_declared_port(tmp_path):
    p = _timed_project(tmp_path, synchronous=False)
    (p / "input/constraints/design.sdc").write_text(
        "create_clock -name external_clock -period 20 [get_ports {clk}]\n"
        "set_false_path -from [get_ports {reset_n}] -to [get_clocks {external_clock}]\n")
    cp, text = _generate(p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "-to [get_clocks {clk_main}]" in text, text
    assert "external_clock" not in text


def test_authored_exception_unknown_clock_mapping_is_refused(tmp_path):
    p = _timed_project(tmp_path)
    (p / "input/constraints/design.sdc").write_text(
        "set_false_path -from [get_ports {reset_n}] -to [get_clocks {absent_clock}]\n")
    cp, text = _generate(p)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "SDC_EXCEPTION_CLOCK_UNKNOWN" in cp.stderr
    assert not text


def test_required_equivalence_is_not_a_path_or_claimed_pass(tmp_path):
    for fake_proof in (None, {"verdict": "PASS", "path": "L7_TEST_DEBUG.json"}):
        p = _timed_project(tmp_path / str(bool(fake_proof)))
        source = p / "input/docs/timing.md"; source.parent.mkdir(parents=True)
        clause = "Timing exceptions require L7 equivalence proof."
        source.write_text(clause + "\n")
        policy = {"requires_l7_equivalence": True, "allow_automatic": False,
                  "source": "input/docs/timing.md", "evidence": clause}
        if fake_proof:
            policy["proof"] = fake_proof
        (p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").write_text(
            json.dumps({"constraints": {"timing_exceptions": policy}}))
        (p / "input/constraints/design.sdc").write_text(
            "set_false_path -from [get_ports {reset_n}] -to [all_clocks]\n")
        cp, text = _generate(p)
        assert cp.returncode == 1, cp.stdout + cp.stderr
        assert "SDC_EXCEPTION_EQUIVALENCE_NOT_MEASURED" in cp.stderr
        assert not text


def test_stale_or_missing_io_source_is_refused(tmp_path):
    p = _timed_project(tmp_path)
    (p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"constraints": {"io_delay": {
            "default_fraction_percent": 20, "source": "input/docs/absent.md",
            "evidence": "I/O delay 20%."}}}))
    cp, text = _generate(p)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "SDC_IO_DELAY_SOURCE_REFUSED" in cp.stderr
    assert not text


def test_native_reset_producer_feeds_the_timing_consumer(tmp_path):
    from phase1_doc_one_shot_runner import _v1_6_369_emit_reset_domains
    p = _timed_project(tmp_path)
    f = p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    doc = json.loads(f.read_text()); doc.pop("reset_domains")
    _v1_6_369_emit_reset_domains(doc, {
        "ports.md": "| reset_n | synchronous active-low reset |\n"})
    assert doc["reset_domains"][0]["sync"] == "synchronous", doc
    f.write_text(json.dumps(doc))
    cp, text = _generate(p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "set_false_path" not in text, text
    assert "# Reset reset_n: synchronous" in text


def test_authored_multicycle_is_preserved_without_mirroring(tmp_path):
    p = _timed_project(tmp_path)
    line = "set_multicycle_path 2 -from [get_ports {switch_data}] -to [get_ports {gpio_out}]"
    (p / "input/constraints/design.sdc").write_text(line + "\n")
    cp, text = _generate(p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert [ln for ln in text.splitlines() if ln.startswith("set_multicycle_path")] == [line], text
    assert "set_false_path" not in text


def _neutral_exception_project(tmp_path):
    p = _timed_project(tmp_path)
    (p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top", "top_ports": [
            {"name": name, "direction": direction} for name, direction in (
                ("clk", "input"), ("data_in", "input"),
                ("control", "input"), ("data_out", "output"))]}))
    (p / "phase2/stage1/rtl/chip_top.sv").write_text(
        "module chip_top(input clk, input data_in, input control, "
        "output reg data_out); always @(posedge clk) "
        "data_out <= data_in ^ control; endmodule\n")
    return p


@pytest.mark.parametrize("role", ["input", "output"])
@pytest.mark.parametrize("qualifier", ["-setup", "-hold", "-through [get_ports {control}]",
                                       "-rise", "-fall"])
def test_partial_authored_cut_retains_ordinary_delays(tmp_path, role, qualifier):
    p = _neutral_exception_project(tmp_path)
    port = "data_in" if role == "input" else "data_out"
    endpoints = (f"-from [get_ports {{{port}}}] -to [all_clocks]"
                 if role == "input" else
                 f"-from [all_clocks] -to [get_ports {{{port}}}]")
    command = f"set_false_path {qualifier} {endpoints}"
    (p / "input/constraints/design.sdc").write_text(command + "\n")
    cp, text = _generate(p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    delays = [ln for ln in text.splitlines()
              if ln.startswith(f"set_{role}_delay") and "{" + port + "}" in ln]
    assert len(delays) == 2, text
    assert any("-max 4.0" in ln for ln in delays), text
    assert any("-min 0.0" in ln for ln in delays), text
    assert [ln for ln in text.splitlines() if ln.startswith("set_false_path")] == [command]
    assert "boundary coverage 4/4" in cp.stdout


@pytest.mark.parametrize("role", ["input", "output"])
@pytest.mark.parametrize("reordered", [False, True])
def test_full_authored_cut_replaces_only_its_direction(tmp_path, role, reordered):
    p = _neutral_exception_project(tmp_path)
    if role == "input":
        endpoints = ("-from [get_ports {data_in}]", "-to [all_clocks]")
    else:
        endpoints = ("-from [all_clocks]", "-to [get_ports {data_out}]")
    command = "set_false_path " + " ".join(reversed(endpoints) if reordered else endpoints)
    (p / "input/constraints/design.sdc").write_text(command + "\n")
    cp, text = _generate(p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    port = "data_in" if role == "input" else "data_out"
    assert not any(ln.startswith(f"set_{role}_delay") and "{" + port + "}" in ln
                   for ln in text.splitlines()), text
    other = "output" if role == "input" else "input"
    other_port = "data_out" if role == "input" else "data_in"
    assert any(ln.startswith(f"set_{other}_delay") and "{" + other_port + "}" in ln
               for ln in text.splitlines()), text
    assert [ln for ln in text.splitlines() if ln.startswith("set_false_path")] == [command]
    assert "boundary coverage 4/4" in cp.stdout


@pytest.mark.parametrize("layer", ["L9", "L8"])
@pytest.mark.parametrize("key", ["synchronous", "sync", "synchrony", "type"])
def test_reset_fields_alias_is_timed_without_an_inferred_cut(tmp_path, layer, key):
    p = _timed_project(tmp_path)
    gd = p / "phase1/generated_docs"
    l9 = json.loads((gd / "L9_INTEGRATION_SPEC.json").read_text())
    l9.pop("reset_domains")
    path = gd / ("L9_INTEGRATION_SPEC.json" if layer == "L9" else "L8_TIMING_WAVEFORM.json")
    doc = l9 if layer == "L9" else {}
    doc["fields"] = {"reset_domains": [{"name": "reset_n", key: "asynchronous"}]}
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    path.write_text(json.dumps(doc))
    cp, text = _generate(p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "# Reset reset_n: asynchronous" in text, text
    assert "set_false_path" not in text, text
    assert any(ln.startswith("set_input_delay") and "{reset_n}" in ln
               for ln in text.splitlines()), text


@pytest.mark.parametrize("layer", ["L9", "L8"])
@pytest.mark.parametrize("key", ["synchronous", "sync", "synchrony", "type"])
def test_reset_fields_alias_conflict_is_refused(tmp_path, layer, key):
    p = _timed_project(tmp_path)
    gd = p / "phase1/generated_docs"
    path = gd / ("L9_INTEGRATION_SPEC.json" if layer == "L9" else "L8_TIMING_WAVEFORM.json")
    doc = json.loads(path.read_text()) if path.exists() else {}
    doc["fields"] = {"clock_and_reset_waveform": {"resets": [
        {"name": "reset_n", key: "asynchronous"}]}}
    path.write_text(json.dumps(doc))
    cp, text = _generate(p)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "SDC_RESET_CONTRACT_CONTRADICTORY" in cp.stderr
    assert not text


def test_reset_conflict_outside_selected_top_does_not_change_timing(tmp_path):
    p = _timed_project(tmp_path)
    f = p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    doc = json.loads(f.read_text())
    doc["reset_domains"].append({"name": "other_reset", "sync": "synchronous"})
    doc["fields"] = {"resets": [{"name": "other_reset", "synchrony": "asynchronous"}]}
    f.write_text(json.dumps(doc))
    cp, text = _generate(p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "other_reset" not in text, text
    assert "# Reset reset_n: synchronous" in text
    assert "set_false_path" not in text


@pytest.mark.parametrize("value", ["sometimes", 2, {}])
def test_invalid_reset_synchrony_is_refused(tmp_path, value):
    p = _timed_project(tmp_path)
    f = p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    doc = json.loads(f.read_text())
    doc["fields"] = {"resets": [{"name": "reset_n", "synchrony": value}]}
    f.write_text(json.dumps(doc))
    cp, text = _generate(p)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "SDC_RESET_CONTRACT_INVALID" in cp.stderr
    assert not text


def test_existing_l19_producer_feeds_fraction_and_stale_source_is_refused(tmp_path):
    from l9_l19_contract_carrythrough import run
    p = _neutral_exception_project(tmp_path)
    gd = p / "phase1/generated_docs"
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({"clock_mhz": 100}))
    (gd / "L19_CONSTRAINTS_PDK.json").write_text("{}")
    source = p / "input/docs/L9_timing.md"
    source.parent.mkdir(parents=True)
    source.write_text("layer: L9\n# I/O delay\n"
                      "Input and output delay default to 20% of the selected clock period.\n")
    receipt = run(p)
    assert receipt["status"] == "OK", receipt
    l19 = json.loads((gd / "L19_CONSTRAINTS_PDK.json").read_text())
    assert l19["constraints"]["io_delay"]["default_fraction_percent"] == 20.0
    cp, text = _generate(p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "set_input_delay  -clock clk_main -max 2.0 [get_ports {data_in}]" in text
    assert "set_output_delay -clock clk_main -max 2.0 [get_ports {data_out}]" in text
    source.write_text(source.read_text().replace("20%", "30%"))
    old = (p / "phase2/stage1/fpga/chip_top.sdc").read_bytes()
    cp, _text = _generate(p)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "SDC_IO_DELAY_SOURCE_REFUSED" in cp.stderr
    assert (p / "phase2/stage1/fpga/chip_top.sdc").read_bytes() == old


def test_required_equivalence_rejects_multicycle_too(tmp_path):
    p = _neutral_exception_project(tmp_path)
    source = p / "input/docs/L9_timing.md"
    source.parent.mkdir(parents=True)
    clause = "Timing exceptions require L7 equivalence proof."
    source.write_text(clause + "\n")
    (p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").write_text(json.dumps({
        "constraints": {"timing_exceptions": {"requires_l7_equivalence": True,
            "source": "input/docs/L9_timing.md", "evidence": clause}}}))
    (p / "input/constraints/design.sdc").write_text(
        "set_multicycle_path -setup 2 -from [get_ports {data_in}] "
        "-to [get_ports {data_out}]\n")
    cp, text = _generate(p)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "SDC_EXCEPTION_EQUIVALENCE_NOT_MEASURED" in cp.stderr
    assert not text
