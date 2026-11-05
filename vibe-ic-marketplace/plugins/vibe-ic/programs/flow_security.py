"""Run supplied security property decks through the existing native formal adapter."""
from pathlib import Path


def requirements(project, directory, tool):
    from flow_native_adapters import Commands, formal

    commands = Commands(directory)
    implemented = tool.get("adapter") == "implemented_security"
    root = "phase3/stage3/formal/security" if implemented else "phase2/stage1/formal/security"
    paths = [Path(path) if Path(path).is_absolute() else project / path
             for path in tool.get("properties", [])]
    if not paths:
        paths = sorted((project / root).glob("*.sby"))
    if not paths:
        return commands.result(detail=f"No produced security property .sby decks in {root}; a generic reset proof does not measure security.")
    result = formal(project, directory, {**tool, "properties": paths}, commands)
    failures = result.get("metrics", {}).get("unproved_required_properties")
    if failures is not None:
        metric = "scan_debug_access_violations" if implemented else "security_counterexample_failures"
        result["metrics"][metric] = failures
    result["detail"] += " Security scope is the supplied property decks; quantitative and physical security targets need their own native measurements."
    return result
