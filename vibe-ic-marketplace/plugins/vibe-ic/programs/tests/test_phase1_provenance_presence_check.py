#!/usr/bin/env python3
"""Tests for phase1_provenance_presence_check.py.

Pins the D6-traceability gate: every L*.json (14 layers) must carry a
non-empty `provenance` dict OR a non-empty `source_documents` list at
top level. A layer with neither (the v055 hand-authored regression) →
FAIL. A missing layer file → FAIL. Non-directory target → rc 2.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "phase1_provenance_presence_check.py"

_spec = importlib.util.spec_from_file_location(
    "phase1_provenance_presence_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

_FNAMES = [fname for _, fname in mod.EXPECTED_DOCS]


def _write_all(gen: Path, with_prov: bool = True):
    gen.mkdir(parents=True, exist_ok=True)
    for fname in _FNAMES:
        doc = {"layer": fname}
        if with_prov:
            doc["provenance"] = {"source": "input_doc/readme.md"}
        (gen / fname).write_text(json.dumps(doc))


# main() reads sys.argv, so patch it.
def _invoke(gen: Path, tmp_path: Path):
    out = tmp_path / "prov.json"
    import sys
    old = sys.argv
    sys.argv = ["prog", str(gen), "--json", str(out)]
    try:
        rc = mod.main()
    finally:
        sys.argv = old
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


# ----------------------------------------------------------------------
# PASS — all 14 layers carry provenance
# ----------------------------------------------------------------------
def test_pass_all_layers_have_provenance(tmp_path):
    gen = tmp_path / "generated_docs"
    _write_all(gen, with_prov=True)
    rc, rep = _invoke(gen, tmp_path)
    assert rc == 0
    assert rep["passes"] == rep["total"] == len(mod.EXPECTED_DOCS)


def test_pass_with_source_documents_alt_key(tmp_path):
    gen = tmp_path / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    for fname in _FNAMES:
        (gen / fname).write_text(json.dumps(
            {"source_documents": ["input_doc/spec.pdf"]}))
    rc, rep = _invoke(gen, tmp_path)
    assert rc == 0
    assert rep["passes"] == rep["total"]


# ----------------------------------------------------------------------
# FAIL — a layer present but missing provenance (the v055 defect)
# ----------------------------------------------------------------------
def test_fail_layer_without_provenance(tmp_path):
    gen = tmp_path / "generated_docs"
    _write_all(gen, with_prov=True)
    # Strip provenance from L5 → hand-authored, untraceable.
    (gen / "L5_ADI_SPEC.json").write_text(json.dumps({"foo": "bar"}))
    rc, rep = _invoke(gen, tmp_path)
    assert rc == 1
    assert rep["per_layer"]["L5"]["status"] == "FAIL_NO_PROV"


def test_fail_empty_provenance_is_not_truthy(tmp_path):
    gen = tmp_path / "generated_docs"
    _write_all(gen, with_prov=True)
    # Empty dict is falsy → must FAIL.
    (gen / "L3_CMD_PROTOCOL.json").write_text(json.dumps({"provenance": {}}))
    rc, rep = _invoke(gen, tmp_path)
    assert rc == 1
    assert rep["per_layer"]["L3"]["status"] == "FAIL_NO_PROV"


# ----------------------------------------------------------------------
# FAIL — a layer file missing entirely
# ----------------------------------------------------------------------
def test_fail_missing_layer_file(tmp_path):
    gen = tmp_path / "generated_docs"
    _write_all(gen, with_prov=True)
    (gen / "L13_LAB_CALIBRATION.json").unlink()
    rc, rep = _invoke(gen, tmp_path)
    assert rc == 1
    assert rep["per_layer"]["L13"]["status"] == "MISSING_FILE"


# ----------------------------------------------------------------------
# Edge — target not a directory → rc 2
# ----------------------------------------------------------------------
def test_not_a_directory(tmp_path):
    f = tmp_path / "afile.txt"
    f.write_text("x")
    rc, _ = _invoke(f, tmp_path)
    assert rc == 2


# ----------------------------------------------------------------------
# L11 resolved through a RETIRED filename (regression).
#
# EXPECTED_DOCS resolved L11 to "L11_CALIBRATION.json", a name
# tools/phase1_engine/schema.py records as existing in ZERO Phase-1 runs;
# the emitter writes "L11_OTP_CONTENT.json". The gate therefore reported
# MISSING_FILE for a file that was present, and no tree could make L11 pass:
# the gate had no reachable green.
#
# These cases deliberately do NOT build their input from EXPECTED_DOCS.
# Deriving the tree from the map under test makes the case self-referential
# -- it would write whatever name the map holds and pass either way.
# ----------------------------------------------------------------------

# The filename the Phase-1 emitter actually writes, stated independently of
# the map under test (tools/phase1_engine/schema.py "L11").
L11_EMITTED = "L11_OTP_CONTENT.json"
L11_RETIRED = "L11_CALIBRATION.json"


def _write_tree(gen: Path, l11_name: str | None):
    """Every expected layer except L11, plus L11 under `l11_name` (or absent)."""
    gen.mkdir(parents=True, exist_ok=True)
    for tag, fname in mod.EXPECTED_DOCS:
        if tag == "L11":
            continue
        (gen / fname).write_text(json.dumps(
            {"layer": fname, "provenance": {"source": "input_doc/readme.md"}}))
    if l11_name is not None:
        (gen / l11_name).write_text(json.dumps(
            {"layer": l11_name, "provenance": {"source": "input_doc/readme.md"}}))


def test_l11_resolves_to_the_emitted_filename():
    """L11 must resolve to the name Phase 1 actually writes."""
    assert dict(mod.EXPECTED_DOCS)["L11"] == L11_EMITTED


def test_l11_emitted_name_reaches_green(tmp_path):
    """A tree carrying the EMITTED L11 filename must exit 0.

    Pre-fix this returned 1 with L11 MISSING_FILE, so no input could satisfy
    the gate -- the failure this case pins.
    """
    gen = tmp_path / "generated_docs"
    _write_tree(gen, L11_EMITTED)
    rc, rep = _invoke(gen, tmp_path)
    assert rc == 0
    assert rep["per_layer"]["L11"]["status"] == "PASS"
    assert rep["passes"] == rep["total"] == 14


def test_l11_retired_name_still_accepted(tmp_path):
    """CONTROL: a pre-rename tree keeps its old verdict, not a new red."""
    gen = tmp_path / "generated_docs"
    _write_tree(gen, L11_RETIRED)
    rc, rep = _invoke(gen, tmp_path)
    assert rc == 0
    assert rep["per_layer"]["L11"]["status"] == "PASS"


def test_l11_absent_under_both_names_is_missing(tmp_path):
    """CONTROL: the alias must not invent a file that is genuinely absent."""
    gen = tmp_path / "generated_docs"
    _write_tree(gen, None)
    rc, rep = _invoke(gen, tmp_path)
    assert rc == 1
    assert rep["per_layer"]["L11"]["status"] == "MISSING_FILE"
    assert L11_EMITTED in rep["per_layer"]["L11"]["reason"]
