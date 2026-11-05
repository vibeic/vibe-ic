"""Small native Step-16 fixtures for the current-record contract.

The gate intentionally requires a measured ``current`` record.  These helpers
model only the native-tool edge in a test project; the production checker and
hash validation still run unchanged in a fresh subprocess.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import _physical_current as current
import _path_layout as paths


def _put(project: Path, rel: str, text: str) -> Path:
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _pdk(project: Path):
    tech = _put(project, "input/pdk/lef/tech.lef",
                "VERSION 5.8 ;\nLAYER M1\n  TYPE ROUTING ;\nEND M1\n")
    cell = _put(project, "input/pdk/lef/cells.lef",
                "VERSION 5.8 ;\nMACRO neutral\nEND neutral\n")
    liberty = _put(project, "input/pdk/liberty/neutral.lib",
                   "library (neutral) {}\n")
    # _physical_current.pdk_of() is a consumer-owned identity check.
    _put(project, "reports/phase3/technology_units.json",
         json.dumps({"pdk": "neutral"}) + "\n")
    return SimpleNamespace(name="neutral", liberty=str(liberty),
                           tech_lef=str(tech), cell_lef=str(cell),
                           macro_lefs=[])


def _native_model(monkeypatch, pdk_name: str):
    def native(_project, _tool, args, log):
        recipe = Path(args[-1]).read_text()
        decks = re.findall(r"(?m)^read_sdc \{([^}]+)\}$", recipe)
        lines = [f"CLOCK_PLAN_PDK {pdk_name}"]
        rc = 0
        for deck in decks:
            for line in Path(deck).read_text().splitlines():
                if not re.search(r"\bcreate_(?:generated_)?clock\b", line):
                    continue
                name = re.search(r"-name\s+(\S+)", line)
                period = re.search(r"-period\s+([\d.]+)", line)
                source = re.search(
                    r"\[get_(?:ports|pins|nets)\s+\{?([^}\]\s]+)\}?\]",
                    line)
                if not (name and period and source):
                    lines.append("[ERROR] CLOCK_SOURCE_MISSING")
                    rc = 1
                    continue
                lines.append(
                    f"CLOCK_PLAN_NATIVE {name.group(1)}|{period.group(1)}|"
                    f"{source.group(1)}")
        if not rc:
            # The native recipe closes every clock's sink census (D34).
            names = [l.split(" ", 1)[1].split("|", 1)[0] for l in lines
                     if l.startswith("CLOCK_PLAN_NATIVE ")]
            lines.extend(f"CLOCK_PLAN_SINK_COUNT {n}|0" for n in dict.fromkeys(names))
            lines.append("CLOCK_PLAN_DONE")
        Path(log).write_text("\n".join(lines) + "\n")
        return rc, {"rc": rc, "argv": [_tool, *args]}

    monkeypatch.setattr(current, "run_native", native)


def current_fixture(monkeypatch, project: Path, sdc_text: str, *,
                    publish: bool = True, preserve_plan: bool = True,
                    preserve_provenance: bool = False):
    """Create one measured Step-16 subject without fabricating a receipt.

    Existing SDC files are retained because the canonical producer consumes all
    of them.  If the project has none, one canonical PnR SDC is created.
    """
    project = Path(project)
    project.mkdir(parents=True, exist_ok=True)
    _put(project, "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
         json.dumps({"fields": {"pdk_target": "neutral"}}))
    floor = _put(project, "phase3/stage3/pnr/floorplan.def",
                 "DESIGN top ;\nEND DESIGN\n")
    pdk = _pdk(project)
    sdcs = paths.clock_plan_input_sdcs(project)
    if not sdcs:
        sdcs = [_put(project, "phase3/stage3/pnr/constraint.sdc", sdc_text)]
    else:
        # Caller-created SDCs are authoritative; use the requested text only
        # when this helper had to create the canonical one.
        if len(sdcs) == 1 and not sdcs[0].read_text().strip():
            sdcs[0].write_text(sdc_text)
    _native_model(monkeypatch, pdk.name)

    plan = project / "phase3/stage3/cts/clock_plan.json"
    original = None
    if preserve_plan and plan.is_file():
        original = json.loads(plan.read_text())
    if publish:
        plan.unlink(missing_ok=True)
        emitted = current.clock_plan(project, plan, floor, sdcs, pdk)
        assert emitted == str(plan)
        produced = json.loads(plan.read_text())
        if original is not None:
            original["current"] = produced["current"]
            if not preserve_provenance:
                original["derived_from"] = produced["derived_from"]
            plan.write_text(json.dumps(original))
    return {"path": str(sdcs[0].relative_to(project)),
            "sha256": __import__("hashlib").sha256(
                sdcs[0].read_bytes()).hexdigest()}
