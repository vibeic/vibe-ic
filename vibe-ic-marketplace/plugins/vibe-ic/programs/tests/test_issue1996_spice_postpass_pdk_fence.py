"""Regression for the Phase-1 SPICE post-pass half of issue #1996.

The generic input-document walker was fenced at v1.15.49, but the later
``_v1_6_350_post_emit_spice_metadata`` hook still recursively walked all of
``input/``. A real project-staged PDK therefore contributed 129 CDL subcircuits
to L9 as if they were design submodules. The load-bearing negative control
below fails on v1.15.49: ``pdk_library_cell`` appears beside the real design
subcircuit. It passes only when the post-pass shares the canonical
``input/pdk*`` boundary with the document walker.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import phase1_doc_one_shot_runner as p1  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(root: Path) -> Path:
    generated = root / "phase1" / "generated_docs"
    generated.mkdir(parents=True)
    _write(generated / "L1_DATASHEET.json", json.dumps({
        "pin_table": [], "no_pin_table_in_input": True,
    }))
    _write(generated / "L5_ADI_SPEC.json", json.dumps({
        "design_parameters": [],
    }))
    _write(generated / "L9_INTEGRATION_SPEC.json", json.dumps({
        "top_module": "design_top", "ports": [], "submodules": [],
    }))
    return root


def _l9(project: Path) -> dict:
    return json.loads((project / "phase1" / "generated_docs"
                       / "L9_INTEGRATION_SPEC.json").read_text())


def test_spice_postpass_excludes_pdk_cdl_but_keeps_design_spice(tmp_path):
    """NEGATIVE CONTROL: fails before the fix, passes after it.

    A foundry-cell subcircuit under canonical staged-PDK collateral is not a
    design hierarchy declaration. A sibling design netlist under ``input/``
    remains a legitimate source and proves the repair did not delete the
    post-pass or blanket-exclude all SPICE inputs.
    """
    project = _project(tmp_path)
    _write(project / "input" / "netlists" / "design.cir",
           ".subckt design_child a y\n.ends design_child\n")
    _write(project / "input" / "pdk" / "cells" / "library.cdl",
           ".subckt pdk_library_cell a y vdd vss\n"
           ".ends pdk_library_cell\n")

    p1._v1_6_350_post_emit_spice_metadata(project)

    rows = _l9(project)["submodules"]
    assert [row["name"] for row in rows] == ["design_child"]
    assert rows[0]["source"] == "input/netlists/design.cir"


def test_spice_postpass_fences_every_declared_pdk_prefix(tmp_path):
    """The boundary is path structure, never a vendor/cell name literal."""
    project = _project(tmp_path)
    _write(project / "design_data" / "neutral.sp",
           ".subckt neutral_design a y\n.ends neutral_design\n")
    _write(project / "input" / "pdk_candidate" / "models.spice",
           ".subckt arbitrary_process_cell a y\n"
           ".ends arbitrary_process_cell\n")

    p1._v1_6_350_post_emit_spice_metadata(project)

    assert [row["name"] for row in _l9(project)["submodules"]] == [
        "neutral_design"
    ]
