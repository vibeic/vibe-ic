"""A2's quoted PDK constants follow the PROJECT's declared target.

WHAT WENT WRONG (measured, u_hawaii_adc / .108 round-2): the analog runner
invokes `analog_a2_topology_emit` with no `--pdk`, whose static default was
`sky130` — so an IHP-target project's ldo topology quoted
`pdk_constants_source.family="sky130A"` (vth_n 0.45 / rail 1.8) while the
registry's own `ihp-sg13g2` entry (vth_n 0.42 / rail 1.2) sat unread, and its
note says in as many words that carrying the sky130 values over mis-biases any
sizing. Two independent halves:

  1. resolution — with no explicit `--pdk`, the selector must come from the
     project's OWN L19-declared `pdk_target` (the same field A3 reads);
     `sky130` remains only the no-declaration fallback, and an explicit
     `--pdk` still wins;
  2. matching — L-docs declare the bare process token (`sg13g2`) while the
     registry entry carries a vendor prefix (`ihp-sg13g2`); exact/prefix
     matching alone returned None for exactly the declared-target case, so
     `pdk_device_params` gains a containment rung.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent))

from _analog_producer_fixture import block, make_project, run_prog  # noqa: E402
import analog_a2_topology_emit as A2  # noqa: E402

PROG = TESTS.parent / "analog_a2_topology_emit.py"

LDO_SPECS = [{"name": "Vout", "target": 1.2, "unit": "V"},
             {"name": "Vin", "target": 1.8, "unit": "V"}]


def _declare_l19(project: Path, target: str) -> None:
    (project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"fields": {"pdk_target": target}}, indent=2),
        encoding="utf-8")


def _family_of(project: Path, name: str) -> str | None:
    ir = json.loads((project / "phase3/analog" / name / "topology.json"
                     ).read_text())
    return (ir["_provenance"]["pdk_constants_source"] or {}).get("family")


def test_bare_process_token_matches_the_vendor_prefixed_entry() -> None:
    fam, params = A2.pdk_device_params("sg13g2")
    assert fam == "ihp-sg13g2", (
        "the L-doc's bare process token must resolve the registry entry")
    assert params.get("nominal_supply_v") == 1.2


def test_no_flag_follows_the_l19_declared_target(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p1",
                           [block("blk_reg", "ldo", specs=LDO_SPECS)])
    _declare_l19(project, "sg13g2")
    cp = run_prog(PROG, project)
    assert cp.returncode == 0, cp.stderr
    assert _family_of(project, "blk_reg") == "ihp-sg13g2", (
        "with no --pdk, the constants must come from the project's own "
        "declared target, not a static sky130 default")


def test_explicit_flag_still_wins(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p2",
                           [block("blk_reg", "ldo", specs=LDO_SPECS)])
    _declare_l19(project, "sg13g2")
    cp = run_prog(PROG, project, "--pdk", "gf180")
    assert cp.returncode == 0, cp.stderr
    assert _family_of(project, "blk_reg") == "gf180mcuD"


def test_no_declaration_keeps_the_sky130_fallback(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p3",
                           [block("blk_reg", "ldo", specs=LDO_SPECS)])
    # no L19 written
    cp = run_prog(PROG, project)
    assert cp.returncode == 0, cp.stderr
    assert _family_of(project, "blk_reg") == "sky130A"
