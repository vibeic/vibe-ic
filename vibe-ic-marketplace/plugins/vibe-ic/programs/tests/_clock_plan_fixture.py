"""Model fixtures use the real Step-7/16 producers, not typed receipts.

Only the author/tool edge is modeled. Consumers, PDK resolution and hashes run
unchanged, including in a fresh subprocess. This is not native EDA evidence.
"""
import json
import re
from pathlib import Path

import _physical_current as current
from _ppa import timing
import phase3_one_shot_runner as runner


def step7_fixture(monkeypatch, project, pdk, sdc, top="neutral"):
    # The model controls its authored text; native acceptance executes the
    # unmocked canonical author on the retained design input separately.
    def author(*_args, **_kwargs):
        return {"text": sdc.read_text(), "design_staged": False,
                "staged_sdc": str(sdc.relative_to(project)),
                "supply_ports": [], "drv_block": None}
    monkeypatch.setattr(timing, "author_asic_sdc", author)
    return timing.emit_step7_asic_sdc(runner, project, top, pdk, "")


def current_fixture(monkeypatch, project, sdc_text, *, publish=True,
                    preserve_plan=True, preserve_provenance=False):
    """Stage explicit clock intent and a project-local PDK, then run owners.

    No receipt is copied from a candidate or made by the fixture itself. A
    representation test may retain its original plan fields; only the current
    binding from the real producer is attached after its tool model executes.
    """
    def put(name, text):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    put("phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
        json.dumps({"fields": {"pdk_target": "auto"}}))
    put("input/pdk/liberty/neutral.lib", "library (neutral) {}\n")
    put("input/pdk/lef/tech.lef",
        "VERSION 5.8 ;\nLAYER M1\n  TYPE ROUTING ;\nEND M1\n")
    put("input/pdk/lef/cells.lef", "MACRO neutral\nEND neutral\n")
    floor = project / "phase3/stage3/pnr/floorplan.def"
    if not floor.exists():
        put(str(floor.relative_to(project)), "DESIGN neutral ;\nEND DESIGN\n")
    source = put("input/constraints/clock_intent.sdc", sdc_text)
    pdk = runner._detect_pdk(project, runner._read_declared_pdk_target(project))
    assert pdk is not None
    rec = step7_fixture(monkeypatch, project, pdk, source)

    def native(_project, tool, args, log):
        recipe = Path(args[-1]).read_text()
        decks = re.findall(r"(?m)^read_sdc \{([^}]+)\}$", recipe)
        lines = [f"CLOCK_PLAN_PDK {pdk.name}"]
        rc = 0
        for deck in decks:
            for line in Path(deck).read_text().splitlines():
                if not line.startswith("create_clock "):
                    continue
                name = re.search(r"-name\s+(\S+)", line)
                period = re.search(r"-period\s+([\d.]+)", line)
                source = re.search(r"\[get_(?:ports|pins)\s+\{?([^}\]\s]+)\}?\]", line)
                if not (name and period and source):
                    lines.append("[ERROR] CLOCK_SOURCE_MISSING")
                    rc = 1
                    continue
                lines.append(f"CLOCK_PLAN_NATIVE {name[1]}|{period[1]}|{source[1]}")
        if not rc:
            lines.append("CLOCK_PLAN_DONE")
        Path(log).write_text("\n".join(lines) + "\n")
        return rc, {"rc": rc, "argv": [tool, *args]}

    monkeypatch.setattr(current, "run_native", native)
    if publish:
        plan = project / "phase3/stage3/cts/clock_plan.json"
        original = json.loads(plan.read_text()) if plan.exists() and preserve_plan else None
        # Drive production, rather than allowing a populated old plan to cache.
        if plan.exists():
            plan.unlink()
        notes = []
        emitted = runner.emit_clock_plan(project, plan, floor, floor.parent, notes)
        assert emitted == str(plan), notes
        produced = json.loads(plan.read_text())
        if original is not None:
            original["current"] = produced["current"]
            if not preserve_provenance:
                original["derived_from"] = produced["derived_from"]
            plan.write_text(json.dumps(original))
    return rec
