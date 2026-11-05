"""Run supplied security property decks through the existing native formal adapter."""
from pathlib import Path


def requirements(project, directory, tool):
    from flow_native_adapters import Commands, formal

    commands = Commands(directory)
    paths = [Path(path) if Path(path).is_absolute() else project / path
             for path in tool.get("properties", [])]
    if not paths:
        paths = sorted((project / "phase2/stage1/formal/security").glob("*.sby"))
    if not paths:
        return commands.result(detail="No produced security property .sby decks; a generic reset proof does not measure security.")
    result = formal(project, directory, {**tool, "properties": paths}, commands)
    failures = result.get("metrics", {}).get("unproved_required_properties")
    if failures is not None:
        result["metrics"]["security_counterexample_failures"] = failures
    result["detail"] += " Security scope is the supplied property decks; quantitative and physical security targets need their own native measurements."
    return result
