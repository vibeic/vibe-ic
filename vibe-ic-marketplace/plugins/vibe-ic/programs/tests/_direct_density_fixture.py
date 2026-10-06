"""Declare the direct report route used by legacy density reader controls."""
import json


def stage_direct_density(project):
    switch = project / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True, exist_ok=True)
    settings = json.loads(switch.read_text()) if switch.is_file() else {}
    settings.setdefault("steps", {}).update({"34": "direct", "37": "direct"})
    switch.write_text(json.dumps(settings))
