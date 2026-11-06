"""Call the existing power-intent tools without initializing the physical chain."""
from pathlib import Path
import sys


def intent(project, directory, tool):
    from flow_native_adapters import Commands
    from l_doc_consumer_contract import load_l_doc, l_doc_fields

    _, document = load_l_doc(project, "L9")
    top = tool.get("top") or l_doc_fields(document).get("top_module")
    if not top:
        return {"ran": False, "exit_code": None, "detail": "The documented design top is missing."}
    commands = Commands(directory)
    report = directory / "upf_emit.json"
    process = commands.run([sys.executable, Path(__file__).with_name("l21_to_upf_emit.py"),
                            project, "--top", top, "--json", report])
    result = commands.result(reports=[report] if report.is_file() else [],
        detail="UPF emission does not measure illegal power states. Native OpenROAD evaluation needs a linked design.")
    status = "NOT_MEASURED" if process is None or process.returncode == 2 else "FAIL" if process.returncode else "PASS"
    result["native_steps"] = [{"name": "l21_to_upf_emit", "ran": process is not None,
                               "exit_code": process.returncode if process else None, "status": status}]
    return result


def simulation(project, directory, tool):
    from flow_native_adapters import Commands, inputs, simulation_sources, testbenches
    from l_doc_consumer_contract import load_l_doc, l_doc_fields
    from sdf_gate_sim import parse_l10_case_stdout
    from verilator_coverage_measure import _tb_top_module

    commands = Commands(directory)
    try:
        files, top = inputs(project, tool)
    except FileNotFoundError as exc:
        return commands.result(detail=str(exc))
    _, document = load_l_doc(project, "L21")
    upf = project / (l_doc_fields(document).get("upf_path") or f"phase2/stage2/constraints/{top}.upf")
    benches = [path for path in testbenches(project, tool) if path.suffix in {".v", ".sv"}]
    if not upf.is_file() or not benches:
        return commands.result(detail="Power simulation needs UPF and a produced HDL power testbench.")
    files, includes = simulation_sources(project, files, top, benches)
    failures, steps = [], []
    for bench in benches:
        process = commands.run(["xezim", "--simulate", "--no-cache", "--error-exit",
            "-s", _tb_top_module(bench), "--upf", upf,
            *[arg for path in includes for arg in ("-I", path)], *files, bench], cwd=bench.parent)
        parsed = parse_l10_case_stdout(process.stdout + process.stderr) if process else {}
        measured = parsed.get("verdict") is not None and parsed.get("total", 0) > 0
        if measured:
            failures.append(parsed["total"] - parsed["passed"])
        status = ("NOT_MEASURED" if process is None else "FAIL" if process.returncode
                  else "PASS" if measured else "NOT_MEASURED")
        steps.append({"name": "xezim " + bench.name, "ran": process is not None,
                      "exit_code": process.returncode if process else None, "status": status})
    metrics = {"isolation_retention_behavior_errors": sum(failures)} if len(failures) == len(benches) else {}
    result = commands.result(metrics, [upf, *benches],
        "Power-aware RTL simulation covers the assertions in the supplied benches; no implemented supply or timing signoff.")
    result["native_steps"] = steps
    return result


def implemented(project, directory, *, state, config):
    from flow_chip_inputs import _tcl_word
    from flow_native_adapters import Commands
    from l_doc_consumer_contract import load_l_doc, l_doc_fields

    commands = Commands(directory)
    database = (state or {}).get("odb")
    _, document = load_l_doc(project, "L21")
    top = (config or {}).get("DESIGN_NAME")
    upf = project / (l_doc_fields(document).get("upf_path") or f"phase2/stage2/constraints/{top}.upf")
    if not database or not Path(database).is_file() or not upf.is_file():
        return commands.result(detail="Implemented power intent needs the current native ODB and UPF.")
    script, report = directory / "power_intent.tcl", directory / "native.upf"
    script.write_text(f"read_db {_tcl_word(database)}\nread_upf -file {_tcl_word(upf)}\n"
                      f"write_upf {_tcl_word(report)}\n")
    process = commands.run(["openroad", "-no_init", "-exit", script])
    output = process.stdout + process.stderr if process else ""
    unsupported = next((command for command in ("upf_version", "set_design_top", "create_supply_net")
                        if 'invalid command name "' + command + '"' in output), None)
    status = ("NOT_MEASURED" if process is None or unsupported else "FAIL" if process.returncode else "PASS")
    result = commands.result(reports=[script, upf, *([report] if report.is_file() else [])],
        detail=(f"OpenROAD read_upf does not implement {unsupported}. " if unsupported else "")
        + "Native UPF reading does not measure always-on supply errors, power-sequence behavior or multivoltage timing.")
    result["native_steps"] = [{"name": "OpenROAD.read_upf", "ran": process is not None,
                               "exit_code": process.returncode if process else None, "status": status}]
    return result
