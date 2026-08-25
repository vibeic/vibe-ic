#!/usr/bin/env python3
"""Tests for doc_extract.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "doc_extract.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_empty_dir(tmp_path):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    r = _run(["--in-dir", str(tmp_path), "--out-dir", str(out)])
    assert r.returncode == 1


# ---------------------------------------------------------------------------
# TIER 2 FOR .xlsx — `xlsx_extract`'s stdlib reader, which had no caller.
#
# Before this edge `extract_xlsx` returned `FAIL  openpyxl not installed` on a
# host without openpyxl, so a vendor spreadsheet in `input/docs/` was never read
# — the "plugin ignores the xlsx" gap arriving through the dependency instead of
# through the file type. `programs/xlsx_extract.py` already carried a pure-stdlib
# .xlsx reader and nothing but its own unit test ever ran it.
#
# BOTH ARMS READ THE SAME WORKBOOK. What the failing arm changes is whether
# openpyxl can be imported, which is the exact condition the fallback exists for
# — not whether there is a file to read.
# ---------------------------------------------------------------------------
import builtins as _builtins
import json as _json

_ROWS = [["CMD", "Payload", "Response", "CRC"],
         ["70", "00 00 3D", "71", "0x3D"],
         ["72", "", "71", "0x71"]]


def _workbook(path: Path) -> Path:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CMD"
    for row in _ROWS:
        ws.append(row)
    wb.save(path)
    return path


def _extract(tmp_path: Path, out: Path, hide_openpyxl: bool):
    sys.path.insert(0, str(PROG.parent))
    import doc_extract as D
    tmp_path.mkdir(parents=True, exist_ok=True)
    src = _workbook(tmp_path / "spec.xlsx")
    out.mkdir(parents=True, exist_ok=True)
    if not hide_openpyxl:
        return D.extract_xlsx(src, out)
    real = _builtins.__import__

    def _no_openpyxl(name, *a, **k):
        if name == "openpyxl" or name.startswith("openpyxl."):
            raise ImportError("openpyxl hidden for this test")
        return real(name, *a, **k)

    _builtins.__import__ = _no_openpyxl
    try:
        return D.extract_xlsx(src, out)
    finally:
        _builtins.__import__ = real


def test_xlsx_tier1_openpyxl(tmp_path):
    r = _extract(tmp_path, tmp_path / "o1", hide_openpyxl=False)
    assert r.status == "PASS"
    assert r.extractor_warnings == []
    assert "00 00 3D" in Path(r.output_text).read_text()


def test_xlsx_tier2_stdlib_reader_when_openpyxl_is_absent(tmp_path):
    """Without openpyxl this used to be a FAIL. The stdlib reader now answers."""
    r = _extract(tmp_path, tmp_path / "o2", hide_openpyxl=True)
    assert r.status == "PASS", r.error
    # The tier is a WARNING, never an `error`: the extraction succeeded.
    assert r.error == ""
    assert any("tier2" in w for w in r.extractor_warnings), r.extractor_warnings
    assert "00 00 3D" in Path(r.output_text).read_text()


def test_both_tiers_produce_the_same_rows(tmp_path):
    """The fallback is a second READER of one workbook, not a second answer."""
    a = _extract(tmp_path / "a", tmp_path / "a" / "o", hide_openpyxl=False)
    b = _extract(tmp_path / "b", tmp_path / "b" / "o", hide_openpyxl=True)
    assert _json.loads(Path(a.output_json).read_text()) \
        == _json.loads(Path(b.output_json).read_text())
