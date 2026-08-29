"""A Phase-1 layer must record where it came from, and the gate must ask by prefix.

THE DEFECT, found by driving benchmark IC `subservient` through the canonical
front door on the GF180MCU OPEN PDK, and both GENERIC — measured identically on two
independent designs (subservient and sha256) on two different hosts.

THE WRITER RECORDED PROVENANCE AT ONE OF FOURTEEN SITES.
    `phase1_provenance_presence_check` asks all fourteen layers for a top-level
    `provenance` or `source_documents`. Exactly one emitter wrote one — the L5
    no-analog builder, which hardcodes `source_documents` in its own content dict.
    Every other layer went out without it, so the gate returned 1/14 on every design.
    Measured: 1 of 28 generated docs carried it, both times, and it was L5 both times.

    The data was never missing. `extraction_evidence` is KEYED BY SOURCE:
        {"input/docs/L1_product_metadata.md": [{"literal": "100 MHz", ...}],
         "derived_from_L3": []}
    so a layer's provenance is its own evidence's keys. Recording it at
    `_write_l_doc` — the one chokepoint all twenty emitters pass through, and the
    place six previous fixes in that file already chose for exactly this reason —
    takes the gate from 1/14 to 10/14 on the real artefacts.

THE SECOND DEFECT FOUND IN THE SAME PLACE — the L11 row naming a file no emitter
writes — landed separately as v1.12.61 and is not repeated here. It is what makes L11
report the TRUE reason below instead of a false MISSING_FILE.

WHAT THIS FIX DOES NOT DO: make the gate green. Four layers (L8_TIMING_WAVEFORM, L9, L10,
L11) still have no input-path evidence of their own, so they still report absent, and
the gate still exits 1. That is the honest answer. A layer with no evidence has no
provenance, and manufacturing one would be the fabrication this gate exists to catch.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
_GATE = _PROGRAMS / "phase1_provenance_presence_check.py"

# A REAL evidence dict, copied verbatim from the L1_DATASHEET.json of the
# subservient/gf180mcuD run — nine input documents, the shape the writer sees.
_REAL_EVIDENCE = {
    "input/docs/L1_product_metadata.md": [{"literal": "100 MHz", "label": "frequency"}],
    "input/docs/L2_architecture.md": [{"literal": "UART", "label": "pin name (output)"}],
    "input/docs/L3_external_interface.md": [],
    "input/docs/L4_command_protocol.md": [],
    "input/docs/L5_register_map.md": [],
    "input/docs/L6_calibration.md": [],
    "input/docs/L7_verification_plan.md": [],
    "input/docs/L8_submodule_integration.md": [],
    "input/docs/L9_constraints_floorplan.md": [],
}


def _writer():
    sys.path.insert(0, str(_PROGRAMS))
    return importlib.import_module("phase1_doc_one_shot_runner")._write_l_doc


def _emit(tmp_path, name, content, evidence):
    _writer()(tmp_path, name, content, evidence)
    return json.loads(
        (tmp_path / "phase1" / "generated_docs" / f"{name}.json").read_text())


def _run_gate(gen: Path):
    r = subprocess.run([sys.executable, str(_GATE), str(gen)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_a_layer_records_the_documents_its_own_evidence_names(tmp_path):
    out = _emit(tmp_path, "L1_DATASHEET", {"schema_version": 1}, _REAL_EVIDENCE)
    assert out["source_documents"] == sorted(_REAL_EVIDENCE), (
        "source_documents must be exactly the input paths the evidence is keyed by; "
        "anything else is either a guess or a loss")


def test_no_evidence_means_no_provenance_and_that_is_the_honest_answer(tmp_path):
    """The failure mode this whole gate exists to catch is an invented trail."""
    out = _emit(tmp_path, "L20_DFT_SCAN_TOPOLOGY", {"schema_version": 1}, {})
    assert out["source_documents"] == [], (
        "a layer with no evidence must record an EMPTY provenance, never a "
        "plausible-looking one")
    rc, txt = _run_gate(tmp_path / "phase1" / "generated_docs")
    assert rc == 1, f"expected exit 1, got {rc}"


def test_a_derivation_is_not_a_source_document(tmp_path):
    """`derived_from_L3` is a true statement about provenance and a false filename."""
    out = _emit(tmp_path, "L9_INTEGRATION_SPEC", {"schema_version": 1},
                {"derived_from_L3": []})
    assert out["source_documents"] == []
    assert out["source_documents_derivation"] == ["derived_from_L3"], (
        "the derivation must still be recorded — losing it would trade one silent "
        "gap for another")


def test_an_emitter_that_set_its_own_provenance_is_not_overwritten(tmp_path):
    """L5's no-analog builder hardcodes source_documents. It knows better than we do."""
    mine = ["input/docs/only_this_one.md"]
    out = _emit(tmp_path, "L5_ADI_SPEC",
                {"schema_version": 1, "source_documents": list(mine)},
                _REAL_EVIDENCE)
    assert out["source_documents"] == mine


