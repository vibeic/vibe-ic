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


def _load_from(module_name: str, path: Path):
    """Load *path* under *module_name*. Used for both the shipped modules and
    the private copies the helper-missing case needs."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


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
def test_graceful_warn_when_doc_extract_helper_missing(tmp_path):
    """The helper resolves `doc_extract.py` as a sibling of its OWN file, so a
    tree without it is produced by loading the two consumers from a private
    directory — not by taking the shipped one out of `programs/`.

    IT USED TO MOVE THE REAL FILE. `shutil.move(programs/doc_extract.py,
    programs/doc_extract.py.bak_test_w7)` for the body of the test, restored in
    a `finally`. Serially that is invisible; the landing gate's per-file
    parallel path runs one pytest session per file over ONE shared checkout, so
    for the duration of this test every concurrent session saw a `programs/`
    tree with a shipped program MISSING and an unknown `.py.bak_test_w7`
    present. Any gate that enumerates `programs/` — the INDEX freshness check,
    the every-program-has-a-test audit, the gate inventories — then measured a
    tree that is not the commit's, and reported the difference as a finding
    about the branch. `git status --porcelain` afterwards is empty, because the
    `finally` put it back, so the manufactured red has no trace to follow.
    A test may not mutate the tree its neighbours are reading.

    The subject is unchanged: the same two real modules, the same helper
    lookup, and the same absence — sourced from a directory this test owns.
    """
    in_dir = tmp_path / "input" / "docs"
    in_dir.mkdir(parents=True)
    (in_dir / "spec.pdf").write_bytes(b"%PDF-1.4 fake")

    # A private programs dir carrying the two consumers and NOT doc_extract.py.
    # Their bare sibling imports (`_path_layout`, ...) still resolve through
    # sys.path to the real modules, exactly as they do when loaded in place —
    # what changes is `__file__`, which is what the helper lookup reads.
    private = tmp_path / "programs_without_doc_extract"
    private.mkdir()
    for name in ("phase1_coverage_report_gen.py", "extraction_coverage_check.py"):
        shutil.copy2(PROGRAMS / name, private / name)
    assert not (private / "doc_extract.py").exists()
    assert (PROGRAMS / "doc_extract.py").is_file(), (
        "the shipped helper must still be in place — this test no longer "
        "removes it, and a tree missing it means something else did")

    rg = _load_from("phase1_coverage_report_gen_w7_missing",
                    private / "phase1_coverage_report_gen.py")
    ec = _load_from("extraction_coverage_check_w7_missing",
                    private / "extraction_coverage_check.py")

    s = rg._ensure_extracted_docs(tmp_path)
    assert s["action"] == "warn"
    assert any("doc_extract.py not found" in w for w in s["warnings"])
    s2 = ec._ensure_extracted_docs(tmp_path)
    assert s2["action"] == "warn"
    assert any("doc_extract.py not found" in w for w in s2["warnings"])


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
