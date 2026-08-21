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
