"""Native scan replacement, stitching and serial replay on LibreLane State."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from librelane.state import DesignFormat, State
from librelane.steps import Step, StepError, StepException
from librelane.steps.openroad import OpenROADStep


def scan_intent(project):
    from l_doc_consumer_contract import load_l_doc, l_doc_fields

    _, document = load_l_doc(Path(project), "L20")
    if not isinstance(document, dict):
        raise StepException("NOT_MEASURED: L20 scan controls are missing")
    document = l_doc_fields(document)
    chains = document.get("scan_chains") or []
    if len(chains) != 1 or not isinstance(chains[0], dict):
        raise StepException("NOT_MEASURED: serial replay needs one documented scan chain")
    chain = chains[0]
    if any(not chain.get(key) for key in ("scan_in", "scan_out", "scan_enable", "clock")):
        raise StepException("NOT_MEASURED: L20 scan input/output/enable/clock is missing")
    reset = document.get("test_mode", {}).get("reset")
    if not isinstance(reset, dict) or reset.get("shift_value") not in (0, 1) or not reset.get("signal"):
        raise StepException("NOT_MEASURED: L20 reset level during scan shift is missing")
    return chain, reset


def serial_bench(top, ports, chain, reset, bits, period, supplies=None):
    from flow_chip_inputs import _identifier

    supplies = supplies or {}
    groups = {}
    for name, direction in ports.items():
        match = re.fullmatch(r"(.+)\[(\d+)\]", name)
        base, index = (match[1], int(match[2])) if match else (name, None)
        group = groups.setdefault(base, {"direction": direction, "bits": [], "supplied": False})
        group["bits"].append(index)
        group["supplied"] |= name in supplies
    declarations, connections = [], []
    for name, group in groups.items():
        indices = group["bits"]
        width = "" if indices == [None] else f"[{max(indices)}:{min(indices)}] "
        kind = "reg" if group["direction"] == "INPUT" and not group["supplied"] else "wire"
        declarations.append(f"{kind} {width}{_identifier(name)}" + ("=0;" if kind == "reg" else ";"))
        connections.append(f".{_identifier(name)}({_identifier(name)})")

    def expression(name):
        match = re.fullmatch(r"(.+)(\[\d+\])", name)
        return _identifier(match[1]) + match[2] if match else _identifier(name)

    clock, enable, source, output = (expression(chain[key]) for key in
                                     ("clock", "scan_enable", "scan_in", "scan_out"))
    return ("`timescale 1ns/1ps\nmodule tb;\n" + "\n".join(declarations)
        + "\n" + "\n".join(f"assign {expression(name)}=1'b{level};" for name, level in supplies.items())
        + f"\n{_identifier(top)} dut({','.join(connections)});\n"
        + f"reg [{bits-1}:0] expected; integer i,p,errors=0,checked=0;reg bit_in;\n"
        + f"task pulse;begin #{period/2};{clock}=1;#{period/2};{clock}=0;end endtask\n"
        + f"initial begin {enable}=1;{expression(reset['signal'])}={reset['shift_value']};{source}=0;\n"
        + f"for(i=0;i<{bits};i=i+1) pulse; expected=0;\n"
        + f"for(p=0;p<4;p=p+1) for(i=0;i<{2*bits};i=i+1) begin\n"
        + f"if({output} !== expected[{bits-1}]) errors=errors+1;\n"
        + "bit_in=(p==0)?0:(p==1)?1:(p==2)?(i%2):!(i%2);\n"
        + f"{source}=bit_in;pulse;expected=(expected<<1)|bit_in;\n"
        + f"if({output} !== expected[{bits-1}]) errors=errors+1;checked=checked+1;end\n"
        + '$display("SCAN_FLUSH checked=%0d errors=%0d",checked,errors);\n'
        + 'if(errors) $fatal(1,"scan flush mismatch");$finish;end\nendmodule\n')


def replay(step, state, metric):
    import odb
    from testbench_gen import _parse_ports

    chain, reset = scan_intent(step.config["DESIGN_DIR"])
    database = odb.dbDatabase.create()
    odb.read_db(database, str(state[DesignFormat.ODB]))
    block = database.getChip().getBlock()
    dft = block.getDft()
    native_chains = list(dft.getScanChains()) if dft else []
    bits = sum(cell.getBits() for item in native_chains for part in item.getScanPartitions()
               for group in part.getScanLists() for cell in group.getScanInsts())
    declared = {name for _, _, name in _parse_ports(Path(state[DesignFormat.NETLIST]).read_text(),
                                                    step.config["DESIGN_NAME"])}
    supplies = {port.getName(): int(port.getSigType() == "POWER")
                for port in block.getBTerms() if port.getSigType() in ("POWER", "GROUND")
                and re.sub(r"\[\d+\]$", "", port.getName()) in declared}
    ports = {port.getName(): port.getIoType() for port in block.getBTerms()
             if port.getSigType() not in ("POWER", "GROUND") or port.getName() in supplies}
    endpoints = [chain[key] for key in ("scan_in", "scan_out", "scan_enable", "clock")]
    if not bits or any(name not in ports for name in [*endpoints, reset["signal"]]):
        raise StepException("NOT_MEASURED: native scan chain or documented endpoint is missing")
    if any(direction not in ("INPUT", "OUTPUT") and name not in supplies for name, direction in ports.items()):
        raise StepException("NOT_MEASURED: native serial replay has no bidirectional-port stimulus")
    folder = Path(step.step_dir)
    bench = folder / "scan_tb.v"
    bench.write_text(serial_bench(step.config["DESIGN_NAME"], ports, chain, reset,
                                  bits, float(step.config["CLOCK_PERIOD"]), supplies))
    models = [Path(str(path)) for path in step.config.get("CELL_VERILOG_MODELS") or []]
    primitives = [path.parent / "primitives.v" for path in models if (path.parent / "primitives.v").is_file()]
    models = list(dict.fromkeys([*primitives, *models]))
    if not models:
        raise StepException("NOT_MEASURED: native cell simulation models are missing")
    executable = folder / "scan.vvp"
    commands = [("compile", ["iverilog", "-g2012", "-DFUNCTIONAL", "-s", "tb", "-o", str(executable),
                              *map(str, models), str(state[DesignFormat.NETLIST]), str(bench)]),
                ("simulate", ["vvp", str(executable)])]
    for name, command in commands:
        try:
            process = subprocess.run(command, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise StepException(f"NOT_MEASURED: {exc}") from exc
        log = process.stdout + process.stderr
        (folder / ("scan_" + name + ".log")).write_text(log)
        if process.returncode:
            raise StepError(f"Native scan {name} exited {process.returncode}; see scan_{name}.log")
    match = re.search(r"SCAN_FLUSH checked=(\d+) errors=(\d+)", log)
    if not match:
        raise StepException("NOT_MEASURED: Icarus produced no scan-flush result")
    checked, errors = map(int, match.groups())
    report = {"chain_bits": bits, "checked_edges": checked, "errors": errors}
    (folder / "scan_flush.json").write_text(json.dumps(report, indent=2) + "\n")
    return {metric: errors, "dft__scan__bits": bits, "dft__scan__checked_edges": checked}


class ScanTool(OpenROADStep):
    outputs = [DesignFormat.ODB, DesignFormat.NETLIST]
    metric = "scan_test_protocol_integrity"
    physical = False

    def get_script_path(self):
        from flow_chip_inputs import _tcl_word

        chain, _ = scan_intent(self.config["DESIGN_DIR"])
        commands = ['source $::env(SCRIPTS_DIR)/openroad/common/io.tcl']
        commands += (["read_current_odb"] if self.physical else
                     ["read_pnr_libs", "read_lefs", "read_current_netlist", "scan_replace"])
        commands += ["set_dft_config -max_chains 1 -scan_enable_name_pattern " + _tcl_word(chain["scan_enable"])
                     + " -scan_in_name_pattern " + _tcl_word(chain["scan_in"])
                     + " -scan_out_name_pattern " + _tcl_word(chain["scan_out"]),
                     "report_dft_config", "report_dft_plan -verbose", "execute_dft_plan", "write_views"]
        path = Path(self.step_dir) / "scan.tcl"
        path.write_text("\n".join(commands) + "\n")
        return str(path)

    def run(self, state_in, **kwargs):
        views, metrics = super().run(state_in, **kwargs)
        state = State(state_in, overrides=views)
        metrics.update(replay(self, state, self.metric))
        return views, metrics


@Step.factory.register()
class ScanInsertion(ScanTool):
    id = "VibeIC.ScanInsertion"
    name = "Native scan replacement and logical stitching"
    inputs = [DesignFormat.NETLIST, DesignFormat.SDC]


@Step.factory.register()
class PhysicalScan(ScanTool):
    id = "VibeIC.PhysicalScan"
    name = "Native physical scan stitching and replay"
    inputs = [DesignFormat.ODB, DesignFormat.NETLIST, DesignFormat.SDC]
    outputs = [DesignFormat.ODB, DesignFormat.NETLIST, DesignFormat.DEF]
    physical = True
    metric = "scan_flush_errors"


@Step.factory.register()
class ScanPreservation(Step):
    id = "VibeIC.ScanPreservation"
    name = "Native post-resynthesis serial scan replay"
    inputs = [DesignFormat.NETLIST, DesignFormat.ODB]
    outputs = []

    def run(self, state_in, **kwargs):
        return {}, replay(self, state_in, "scan_preservation_errors")
