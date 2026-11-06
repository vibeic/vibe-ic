"""Optional post-map native product, owned by the synthesis handoff.

ENFORCEMENT: blocking when requested. A present child never falls back to its
Yosys parent on a stale/missing observation. Structural/provenance acceptance
is not LEC or timing acceptance; those existing consumers still run.
"""
from __future__ import annotations
import json
from pathlib import Path
import os as _os
import sys as _sys

# This program is also imported directly by file path. Keep sibling imports
# resolvable in that entry mode, as the other flat programs do.
if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import librelane_contract as LC



def mode(project):
    switch = project / "phase3/librelane_switch.json"
    doc = json.loads(switch.read_text()) if switch.is_file() else {}
    if not isinstance(doc, dict):
        raise LC.Refusal("LL_POSTMAP_MODE_INVALID", "switch must be an object")
    value = doc.get("post_map_repair", "off")
    if value not in ("off", "pre_placement"):
        raise LC.Refusal("LL_POSTMAP_MODE_INVALID", repr(value))
    return value


def _inside(project, value):
    rel = Path(value)
    path = project / rel
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise ValueError("post-map path escaped project")
    for part in [path, *path.parents]:
        if part == project.parent:
            break
        if part.is_symlink():
            raise ValueError("post-map path is symlinked")
    if not path.resolve().is_relative_to(project.resolve()):
        raise ValueError("post-map path escaped project")
    return path


def selected(project, binding, parent, parent_folder):
    """Select the requested post-map product and read its native statistics."""
    if mode(project) == "off":
        return parent, None
    child = binding.get("post_map")
    if not isinstance(child, dict) or not child.get("folder"):
        raise ValueError("requested post-map product is absent")
    folder = _inside(project, child["folder"])
    state = json.loads((folder / "state_out.json").read_text())
    output = LC.project_path(project, state["nl"])
    if not output.is_file():
        raise ValueError("post-map native netlist is absent")
    stats = project / "phase2/stage2/synth/stats.json"
    LC.verify_synthesis_stat(folder / "reports/stat.json", {**state, "nl": str(output)},
                             stats, binding["top"], None)
    return output, folder
