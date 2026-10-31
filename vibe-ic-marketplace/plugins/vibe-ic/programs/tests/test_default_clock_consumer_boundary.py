"""Default Step-16 producer/receipt/consumer boundary."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _physical_current as current  # noqa: E402
import phase3_one_shot_runner as runner  # noqa: E402


def _write(project: Path, rel: str, text: str) -> Path:
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_default_clock_consumer_is_same_invocation_and_reuses_current(
        tmp_path, monkeypatch):
    project = tmp_path / "project"
    pnr = project / "phase3/stage3/pnr"
    def_text = "VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n"
    _write(project, "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
           json.dumps({"fields": {"pdk_target": "neutral"}}))
    _write(project, "reports/phase3/technology_units.json",
           json.dumps({"pdk": "neutral"}) + "\n")
    floor = _write(project, "phase3/stage3/pnr/floorplan.def", def_text)
    _write(project, "phase3/stage3/pnr/chip_top.def", def_text)
    _write(project, "phase3/stage3/pnr/routed.def", def_text)
    sdc = _write(
        project, "phase3/stage3/pnr/constraint.sdc",
        "create_clock -name core -period 7 [get_ports clk]\n")

    pdk_root = tmp_path / "pdk"
    tech = _write(pdk_root, "tech.lef", "VERSION 5.8 ;\nEND LIBRARY\n")
    cell = _write(pdk_root, "cells.lef", "MACRO neutral\nEND neutral\n")
    liberty = _write(pdk_root, "neutral.lib", "library (neutral) {}\n")
    pdk = runner.PdkConfig(
        name="neutral", liberty=str(liberty), tech_lef=str(tech),
        cell_lef=str(cell), cell_gds=None, site="unit", drc_deck=None)
    monkeypatch.setattr(runner, "_detect_pdk", lambda *_a, **_k: pdk)

    native_calls = []

    def native(_project, tool, args, log):
        native_calls.append(tuple(args))
        recipe = Path(args[-1]).read_text()
        decks = re.findall(r"(?m)^read_sdc \{([^}]+)\}$", recipe)
        lines = ["CLOCK_PLAN_PDK neutral"]
        for deck in decks:
            for line in Path(deck).read_text().splitlines():
                match = re.search(
                    r"-name\s+(\S+).*?-period\s+([\d.]+).*?"
                    r"\[get_ports\s+([^\]]+)\]", line)
                if match:
                    lines.append(
                        f"CLOCK_PLAN_NATIVE {match[1]}|{match[2]}|{match[3]}")
        names = [l.split(" ", 1)[1].split("|", 1)[0] for l in lines
                 if l.startswith("CLOCK_PLAN_NATIVE ")]
        lines.extend(f"CLOCK_PLAN_SINK_COUNT {n}|0" for n in dict.fromkeys(names))
        lines.append("CLOCK_PLAN_DONE")
        Path(log).write_text("\n".join(lines) + "\n")
        return 0, {"rc": 0, "argv": [tool, *args]}

    monkeypatch.setattr(current, "run_native", native)
    monkeypatch.setattr(runner, "_emit_spef", lambda *_a, **_k: False)

    first = runner._canonicalize_postpnr_prerequisites(
        project, "chip_top", pdk, "")
    basis_path = project / "reports/phase3/postpnr_canonical_basis.json"
    basis = json.loads(basis_path.read_text())
    gate_path = project / "reports/phase2/gates/clock_plan.json"
    gate = json.loads(gate_path.read_text())

    assert gate["verdict"] == "PASS"
    assert basis["outputs"]["clock_plan"]["verdict"] == "PASS"
    assert basis["outputs"]["clock_plan"]["report"] == \
        "reports/phase2/gates/clock_plan.json"
    assert basis["clock_plan_gate_sha256"] == hashlib.sha256(
        gate_path.read_bytes()).hexdigest()
    # Other canonical outputs may be unmeasured in this isolated fixture; the
    # assertion for this test is the Step-16 row itself.
    assert basis["outputs"]["clock_plan"]["status"] == "PASS"
    assert len(native_calls) == 1

    # Same inputs and current receipt: the second invocation consumes the same
    # subject and must not launch another native producer.
    second = runner._canonicalize_postpnr_prerequisites(
        project, "chip_top", pdk, "")
    assert len(native_calls) == 1


def test_clock_waiver_is_not_promoted_to_pass(tmp_path, monkeypatch):
    project = tmp_path / "project"
    pnr = project / "phase3/stage3/pnr"
    def_text = "VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n"
    _write(project, "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
           json.dumps({"fields": {"pdk_target": "neutral"}}))
    _write(project, "reports/phase3/technology_units.json",
           json.dumps({"pdk": "neutral"}) + "\n")
    _write(project, "phase3/stage3/pnr/floorplan.def", def_text)
    _write(project, "phase3/stage3/pnr/chip_top.def", def_text)
    _write(project, "phase3/stage3/pnr/routed.def", def_text)
    _write(project, "waivers.json", json.dumps({
        "waived_steps": [{"id": "clock_plan", "ticket": "WAIVE-16",
                          "reason": "fixture only"}],
    }))
    pdk_root = tmp_path / "pdk"
    tech = _write(pdk_root, "tech.lef", "VERSION 5.8 ;\nEND LIBRARY\n")
    cell = _write(pdk_root, "cells.lef", "MACRO neutral\nEND neutral\n")
    liberty = _write(pdk_root, "neutral.lib", "library (neutral) {}\n")
    pdk = runner.PdkConfig(
        name="neutral", liberty=str(liberty), tech_lef=str(tech),
        cell_lef=str(cell), cell_gds=None, site="unit", drc_deck=None)
    monkeypatch.setattr(runner, "emit_clock_plan", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_emit_spef", lambda *a, **k: False)
    monkeypatch.setattr(runner, "_librelane_signoff_modes",
                        lambda *_a: ("invalid", ""))
    monkeypatch.setattr(runner, "_postpnr_extraction_inputs",
                        lambda *_a: (None, ""))

    result = runner._canonicalize_postpnr_prerequisites(
        project, "chip_top", pdk, "")
    basis = json.loads(
        (project / "reports/phase3/postpnr_canonical_basis.json").read_text())
    clock = basis["outputs"]["clock_plan"]
    assert clock["verdict"] == "WAIVED"
    assert clock["status"] == "WAIVED"
    assert result.status != "PASS"
