"""Supplied timing constraints survive physical chip preparation."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

import flow_chip_inputs as chip
from flow_config import build_config


@pytest.fixture
def project(tmp_path):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "unit"}))
    (docs / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({"fields": {"pdk_target": "sky130A"}}))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({"clock_domains": [
        {"source_pin": "clk", "domain_kind": "primary", "period_ns": 12},
        {"source_pin": "aux_clk", "domain_kind": "secondary", "period_ns": 24}]}))
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "unit.v").write_text("""module unit(input clk, aux_clk, data,
      output reg main_q, aux_q);
      always @(posedge clk) main_q <= data;
      always @(posedge aux_clk) aux_q <= data;
    endmodule
    """)
    constraints = tmp_path / "input/constraints"
    constraints.mkdir(parents=True)
    (constraints / "constraint.sdc").write_text("""current_design unit
set period 12
create_clock -name main -period $period [get_ports clk]
create_clock -name auxiliary -period 24 [get_ports aux_clk]
set_clock_groups -asynchronous -group main -group auxiliary
set_input_delay 2.4 -clock main [all_inputs -no_clocks]
set_output_delay 2.4 -clock main [all_outputs]
""")
    return tmp_path


def test_supplied_sdc_reaches_native_config_with_secondary_clock(project):
    config = build_config(project, route="ip")
    assert config["CLOCK_PORT"] == ["clk", "aux_clk"]
    assert config["CLOCK_PERIOD"] == 12
    for key in ("PNR_SDC_FILE", "SIGNOFF_SDC_FILE", "FALLBACK_SDC"):
        assert config[key] == str(project / "input/constraints/constraint.sdc")


def test_explicit_native_sdc_selection_precedes_staged_constraints(project):
    selected = project / "selected.sdc"
    selected.write_text("create_clock -name selected -period 6 [get_ports clk]\n")
    declaration = project / "plugin_output/declaration.json"
    declaration.parent.mkdir()
    declaration.write_text(json.dumps({"PNR_SDC_FILE": str(selected)}))
    config = build_config(project, route="ip")
    assert config["PNR_SDC_FILE"] == str(selected)
    assert config["CLOCK_PERIOD"] == 6


def test_native_chip_sdc_keeps_both_clock_domains_and_authored_exceptions(project):
    sta = shutil.which("sta")
    root = os.environ.get("PDK_ROOT")
    library = (Path(root) / "sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
               if root else None)
    if not sta or library is None or not library.is_file():
        pytest.skip("native OpenSTA and SKY130 timing library required")
    config = build_config(project, route="ic")
    config.setdefault("IO_DELAY_CONSTRAINT", 20)
    ports = [{"name": name, "direction": direction, "indexed": False}
             for direction, names in (("input", ("clk", "aux_clk", "data")),
                                      ("output", ("main_q", "aux_q"))) for name in names]
    sdc = project / "chip.sdc"
    sdc.write_text(chip._sdc(project, config, ports))
    netlist = project / "chip.v"
    netlist.write_text("""module unit_chip(inout clk, aux_clk, data, main_q, aux_q);
      sky130_fd_sc_hd__dfxtp_1 main_reg(.CLK(clk), .D(data), .Q(main_q));
      sky130_fd_sc_hd__dfxtp_1 aux_reg(.CLK(aux_clk), .D(data), .Q(aux_q));
    endmodule
    """)
    script = project / "check.tcl"
    script.write_text(f"""read_liberty {{{library}}}
read_verilog {{{netlist}}}
link_design unit_chip
read_sdc {{{sdc}}}
check_setup -verbose -no_clock
foreach clock [all_clocks] {{puts "CLOCK [get_name $clock] [get_property $clock period]"}}
exit
""")
    run = subprocess.run([sta, "-no_init", "-no_splash", "-exit", str(script)],
                         cwd=project, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "Error" not in run.stdout + run.stderr
    assert "unclocked" not in run.stdout
    assert "CLOCK main 12" in run.stdout
    assert "CLOCK auxiliary 24" in run.stdout
    assert "set_clock_groups -asynchronous -group main -group auxiliary" in sdc.read_text()
    assert "set_output_delay 2.4" in sdc.read_text()
