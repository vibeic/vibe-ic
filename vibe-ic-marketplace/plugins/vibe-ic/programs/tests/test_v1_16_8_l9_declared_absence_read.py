"""`integration_spec_audit` graded an empty `submodules` list ERROR without
reading the declaration the SAME emitter wrote beside it. Measured on
opentitan_aes: L9 says `no_submodules_in_input: true` and records that all 7
harvested candidates were dropped by its own provenance rule (they were AES
*modes* named in no cited document), and the auditor demanded structure the
design does not have. Bidirectional: a declared absence PASSes; an empty list
with no declaration still ERRORs."""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]

_BASE = {
    "doc_class": "L9_INTEGRATION_SPEC",
    "top_module": "chip_top",
    "ports": [{"name": "clk_i", "direction": "input"}],
    "submodules": [],
    "internal_wires": [],
}


def _run(tmp_path, doc):
    proj = tmp_path / "proj"
    d = proj / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    (d / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(doc))
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "integration_spec_audit.py"), str(proj)],
        capture_output=True, text=True)
    return r


def test_declared_absence_is_not_an_error(tmp_path):
    doc = dict(_BASE, no_submodules_in_input=True)
    r = _run(tmp_path, doc)
    assert "MISSING_SUBMODULES" not in r.stdout + r.stderr, r.stdout
    assert r.returncode == 0, r.stdout + r.stderr


def test_provenance_census_of_total_drops_is_also_a_declaration(tmp_path):
    """The second channel: the list is empty BECAUSE every candidate was
    refused by a stated rule, which is the emitter speaking, not silence."""
    doc = dict(_BASE, submodule_name_provenance={
        "entries_total": 7, "entries_with_document_citation": 7,
        "entries_dropped": 7,
        "rule": "a submodule entry that cites an input document must name a "
                "token that document contains"})
    r = _run(tmp_path, doc)
    assert "MISSING_SUBMODULES" not in r.stdout + r.stderr, r.stdout
    assert r.returncode == 0, r.stdout + r.stderr


def test_silence_still_errors(tmp_path):
    """Over-reach control. An empty list with NO declaration beside it is the
    case this rule exists for and must keep failing."""
    r = _run(tmp_path, dict(_BASE))
    assert "MISSING_SUBMODULES" in r.stdout + r.stderr, r.stdout
    assert r.returncode == 1, r.stdout + r.stderr


def test_a_partial_drop_census_is_not_a_declaration(tmp_path):
    """Narrowness control. `dropped < total` means entries survived and the
    list should not be empty; that is a real defect, not a declared absence."""
    doc = dict(_BASE, submodule_name_provenance={
        "entries_total": 7, "entries_dropped": 3, "rule": "some rule"})
    r = _run(tmp_path, doc)
    assert "MISSING_SUBMODULES" in r.stdout + r.stderr, r.stdout
    assert r.returncode == 1, r.stdout + r.stderr
