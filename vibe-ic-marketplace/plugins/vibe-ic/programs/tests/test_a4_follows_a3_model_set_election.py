"""A4 follows A3's recorded model-set election within one model tree.

WHAT WENT WRONG (measured, u_hawaii_adc ldo on a two-flavour PDK): A3 elects
the device FLAVOUR for the block's own voltage domain (#903) — the elevated-
voltage MOS corner lib — and records it in `netlist_provenance.json`. A4's own
context resolution answers the FAMILY question and elected the plain-voltage
flavour lib in the same directory. The own-card election (by resolved file
name) then found 0 cards and refused the deck as a model-set mismatch, even
though the deck's binding was A3's correct, recorded election. Flavour-aligned
blocks passed; flavour-split blocks dead-ended — flavour-blind.

THE RULE. The model set is A3's to elect and A4's only to re-stamp corners on.
When the delivered netlist's RECORDED model lib lives in the SAME model tree
(same directory) as A4's resolved one and exists, A4 follows the record and
keeps only the corner choice. A binding outside the resolved tree is still a
cross-family refusal naming both sides, and an absent/unreadable record
changes nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent))

from test_a4_consumes_design_netlist import (  # noqa: E402
    _project, _record, _sweep)

SKY_LIB = "/foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice"
HV_LIB = "/foss/pdks/sky130A/libs.tech/ngspice/sky130_hv.lib.spice"
FOREIGN = "/foss/pdks/other_family/libs.tech/ngspice/other.lib.spice"


def _rebind(project: Path, block: str, lib: str) -> None:
    sp = project / "phase3" / "analog" / block / f"{block}.sp"
    sp.write_text(sp.read_text().replace(SKY_LIB, lib))


def _prov(project: Path, block: str, model_lib: str) -> None:
    (project / "phase3" / "analog" / block / "netlist_provenance.json"
     ).write_text(json.dumps({
         "block": block,
         "pdk": {"model_lib": model_lib},
         "_provenance": {"producer": "synthetic-fixture",
                          "design_content": "structure_and_geometry",
                          "spec_bound_params": ["r1.l"],
                          "library_nominal_params": []},
     }, indent=2))


def test_same_tree_flavour_election_is_followed(tmp_path, monkeypatch) -> None:
    S = _sweep(monkeypatch)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    _rebind(project, "blk_alpha", HV_LIB)
    _prov(project, "blk_alpha", HV_LIB)

    rc = S.run_block(project, "blk_alpha", "fake", "sky130", "auto")
    assert rc == 0, _record(project, "blk_alpha").get(
        "deck_unbuildable_reason") or _record(project, "blk_alpha").get("reason")
    rec = _record(project, "blk_alpha")
    assert rec.get("deck_unbuildable_reason") is None
    assert rec["netlist_declared_model_lib"].endswith("sky130_hv.lib.spice"), (
        "the sweep must simulate against the flavour A3 recorded, not the one "
        "this step re-elected")


def test_cross_tree_binding_is_still_refused_naming_both(
        tmp_path, monkeypatch) -> None:
    """The pre-existing pin, held: a record pointing OUTSIDE the resolved
    model tree is a cross-family binding and never followed."""
    S = _sweep(monkeypatch)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    _rebind(project, "blk_alpha", FOREIGN)
    _prov(project, "blk_alpha", FOREIGN)

    rc = S.run_block(project, "blk_alpha", "fake", "sky130", "auto")
    assert rc == 2
    rec = _record(project, "blk_alpha")
    assert "other.lib.spice" in rec["deck_unbuildable_reason"]
    assert "sky130.lib.spice" in rec["deck_unbuildable_reason"]


def test_absent_record_changes_nothing(tmp_path, monkeypatch) -> None:
    """No provenance record → A4 keeps its own resolution; a deck bound to a
    same-tree OTHER flavour without a record is still the mismatch refusal
    (nothing silently guessed)."""
    S = _sweep(monkeypatch)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    _rebind(project, "blk_alpha", HV_LIB)
    # no _prov written

    rc = S.run_block(project, "blk_alpha", "fake", "sky130", "auto")
    assert rc == 2
    rec = _record(project, "blk_alpha")
    assert "sky130_hv.lib.spice" in rec["deck_unbuildable_reason"]
