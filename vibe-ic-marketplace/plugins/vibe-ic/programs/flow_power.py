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
