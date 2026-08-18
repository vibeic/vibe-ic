#!/usr/bin/env python3
"""Tests for `_ensure_extracted_docs` helper (BACKLOG-v13 Wave 7).

Wave 7 closes the v0.119.37 fresh-agent gap where binary docs in
`input/docs/` (PDF/xlsx/pptx/doc) were invisible to auto-discovery
because both `phase1_coverage_report_gen.py` and
`extraction_coverage_check.py` only scanned `*.txt`.

The helper auto-invokes `doc_extract.py` on the `input/docs/`
directory when `extracted_docs/` is empty and binary docs are
present, then auto-discovery proceeds against the populated
`extracted_docs/*.txt`. Failures are graceful WARN-only.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent


def _load(module_name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, PROGRAMS / file_name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


report_gen = _load(
    "phase1_coverage_report_gen_w7",
    "phase1_coverage_report_gen.py",
)
ll38 = _load(
    "extraction_coverage_check_w7",
    "extraction_coverage_check.py",
)


# ----------------------------------------------------------------
# 1. Already-populated extracted_docs/ -> noop, no doc_extract call.
# ----------------------------------------------------------------
def test_noop_when_extracted_docs_already_populated(tmp_path):
    out_dir = tmp_path / "phase1" / "input_doc"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "preexisting.txt").write_text("already extracted")
    in_dir = tmp_path / "input" / "docs"
    in_dir.mkdir(parents=True)
    # Even if a binary doc is present, helper must not re-extract.
    (in_dir / "spec.pdf").write_bytes(b"%PDF-1.4 fake")

    s1 = report_gen._ensure_extracted_docs(tmp_path)
    s2 = ll38._ensure_extracted_docs(tmp_path)
    assert s1["action"] == "noop"
    assert s2["action"] == "noop"
    # Pre-existing file untouched.
    assert (out_dir / "preexisting.txt").read_text() == "already extracted"


# ----------------------------------------------------------------
# 2. Binary doc present, no extracted_docs/ -> extraction triggered.
#    We assert action=="extracted" iff helper produced any .txt; if
#    pdftotext is absent, we accept "warn".
# ----------------------------------------------------------------
def test_extraction_triggered_when_binary_present(tmp_path):
    in_dir = tmp_path / "input" / "docs"
    in_dir.mkdir(parents=True)
    # libreoffice/openpyxl tends to be more available than pdftotext.
    # Provide a plain .txt as well so doc_extract has at least one
    # PASS path even if pdftotext is missing.
    (in_dir / "notes.pdf").write_bytes(b"%PDF-1.4 stub")
    (in_dir / "side_text.txt").write_text("plain text source")

    s = report_gen._ensure_extracted_docs(tmp_path)
    # extraction triggered (action "extracted") OR warn (no extractor).
    # noop is NOT acceptable — we have binary input + empty extracted_docs/.
    assert s["action"] in ("extracted", "warn")
    if s["action"] == "extracted":
        assert s["extracted_count"] >= 1
        assert (tmp_path / "phase1" / "input_doc").is_dir()
    else:
        # Graceful: warning surfaced, no crash.
        assert s["warnings"]


# ----------------------------------------------------------------
# 3. Helper missing -> graceful WARN, no crash.
# ----------------------------------------------------------------
def test_graceful_warn_when_doc_extract_helper_missing(tmp_path, monkeypatch):
    # Redirect Path(__file__).resolve().parent.parent / 'programs' to a
    # tmp dir that does NOT contain doc_extract.py. Easiest: force the
    # programs path lookup to fail by stubbing the helper resolver.
    in_dir = tmp_path / "input" / "docs"
    in_dir.mkdir(parents=True)
    (in_dir / "spec.pdf").write_bytes(b"%PDF-1.4 fake")

    # Move doc_extract.py temporarily out of programs/.
    real = PROGRAMS / "doc_extract.py"
    backup = PROGRAMS / "doc_extract.py.bak_test_w7"
    assert real.is_file()
    shutil.move(str(real), str(backup))
    try:
        s = report_gen._ensure_extracted_docs(tmp_path)
        assert s["action"] == "warn"
        assert any("doc_extract.py not found" in w for w in s["warnings"])
        s2 = ll38._ensure_extracted_docs(tmp_path)
        assert s2["action"] == "warn"
        assert any("doc_extract.py not found" in w for w in s2["warnings"])
    finally:
        shutil.move(str(backup), str(real))


# ----------------------------------------------------------------
# 4. No input/docs/ at all -> noop.
# ----------------------------------------------------------------
def test_noop_when_no_input_docs(tmp_path):
    s = report_gen._ensure_extracted_docs(tmp_path)
    assert s["action"] == "noop"


# ----------------------------------------------------------------
# 5. input/docs/ has only .txt files (no binary) -> noop.
# ----------------------------------------------------------------
def test_noop_when_only_text_inputs(tmp_path):
    in_dir = tmp_path / "input" / "docs"
    in_dir.mkdir(parents=True)
    (in_dir / "readme.txt").write_text("plain")
    s = report_gen._ensure_extracted_docs(tmp_path)
    assert s["action"] == "noop"
    s2 = ll38._ensure_extracted_docs(tmp_path)
    assert s2["action"] == "noop"
