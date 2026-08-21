"""Shared SYNTHETIC fixture builder for the A1-A3 producer tests.

Every name here is invented (`vreg_alpha`, `blk_alpha`, `keeper_x`,
`widget_q`, `doc_alpha.md`). No chip, PDK SKU, vendor or part number appears
in this file or in anything it writes.

The producers are driven as SUBPROCESSES and every assertion is about the
ARTEFACTS on disk and about the rc of the SHIPPED gates. No test reaches into
a producer's internals, so a test can only fail on a wrong artefact or a wrong
absence — never on a renamed helper.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path

PROGRAMS = Path(_plugin_tree.plugin_path("programs"))

A1 = PROGRAMS / "analog_a1_spec_emit.py"
A2 = PROGRAMS / "analog_a2_topology_emit.py"
A3 = PROGRAMS / "analog_a3_netlist_emit.py"

GATE_A1 = PROGRAMS / "analog_a1_spec_extract_check.py"
GATE_A2 = PROGRAMS / "analog_a2_topology_select_check.py"
GATE_A3 = PROGRAMS / "analog_a3_netlist_gen_check.py"
NETLIST_CHECKERS = (
    PROGRAMS / "analog_netlist_pdk_check.py",
    PROGRAMS / "analog_netlist_connectivity_check.py",
    PROGRAMS / "analog_netlist_include_order_check.py",
    PROGRAMS / "analog_netlist_path_lint.py",
)


def block(name: str, btype: str, specs: Optional[List[Dict[str, Any]]] = None,
          low_confidence: bool = False) -> Dict[str, Any]:
    """One synthetic `analog_blocks[]` entry. `specs=None` models the honest
    Phase-1 outcome this whole round is about: the documents mention the block
    and attribute no number to it."""
    return {
        "name": name,
        "type": btype,
        "low_confidence": low_confidence,
        "evidence": "doc_alpha.md (keyword)",
        "evidence_paragraph": f"The alpha subsystem contains a {btype}.",
        "spec": ({"specs": specs} if specs is not None else None),
    }


def make_project(root: Path, blocks: List[Dict[str, Any]],
                 unattributed_rows: int = 0) -> Path:
    """`unattributed_rows` models the real Phase-1 shape the producers refuse
    to bind: electrical rows that carry NO block key, so deciding which block
    each belongs to is judgment."""
    (root / "phase1/generated_docs").mkdir(parents=True, exist_ok=True)
    (root / "phase3/analog").mkdir(parents=True, exist_ok=True)
    (root / "phase3/analog/analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}, indent=2), encoding="utf-8")
    l5: Dict[str, Any] = {"analog_blocks": blocks}
    if unattributed_rows:
        l5["electrical_specs"] = [
            {"param": f"row_{i}", "value": 1.0 + i, "unit": "V",
             "source": "doc_alpha.md"}
            for i in range(unattributed_rows)]
    (root / "phase1/generated_docs/L5_ADI_SPEC.json").write_text(
        json.dumps(l5, indent=2), encoding="utf-8")
    return root


def run_prog(prog: Path, project: Path, *args: str
             ) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(prog), str(project), *args],
                          capture_output=True, text=True, timeout=60)


def bdir(project: Path, name: str) -> Path:
    return project / "phase3/analog" / name


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def all_sp_files(project: Path) -> List[Path]:
    """Every `.sp` anywhere under the project — the negative control asserts
    on the whole tree, not on one expected path, so a netlist smuggled into a
    different directory would still be caught."""
    return sorted(project.rglob("*.sp"))
