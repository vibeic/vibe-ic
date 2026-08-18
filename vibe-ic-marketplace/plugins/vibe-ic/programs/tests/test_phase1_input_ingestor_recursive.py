"""tests/test_phase1_input_ingestor_recursive.py — v1.6.55

Closes GitHub issue #3 (ORGANIC-20260509-phase1-input-format-coverage-gap).
Covers:

  * BUG 1 — recursive walk of input/docs/ (subdirs no longer dropped)
  * BUG 2 — extension coverage extension (.odt / .rst / .adoc / .html /
            extension-less plain text)
  * Visibility — extraction_skipped.json emitted for every visited
                 file that produced no text
  * Filename collision — same-basename files in different subdirs
                          produce distinct extracted_docs/ entries
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from programs.phase1_one_shot_runner import (
    extract_text_pipeline, extract_one,
    extract_html, extract_extensionless_text, extract_odt,
)


# ---------------------------------------------------------------------------
# BUG 1 — recursive walk.
# ---------------------------------------------------------------------------

def test_recursive_walk_picks_up_subdir_files(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    docs = p / "input" / "docs"
    spec = docs / "spec"
    spec.mkdir(parents=True)
    (docs / "README.md").write_text("# overview\nsurface content\n")
    (spec / "deep_spec.txt").write_text("inner subdir content here\n")
    (spec / "nested" / "doc.md").parent.mkdir(parents=True, exist_ok=True)
    (spec / "nested" / "doc.md").write_text("# deep\ndeep content\n")

    out = extract_text_pipeline(p)
    # All three files visited and extracted.
    keys = list(out.keys())
    # Top-level README: encoded as `README.md`
    assert any("README" in k for k in keys), keys
    # subdir spec/deep_spec.txt: encoded as `spec__deep_spec.txt`
    assert any("spec__deep_spec" in k for k in keys), keys
    # nested spec/nested/doc.md: encoded as `spec__nested__doc.md`
    assert any("spec__nested__doc" in k for k in keys), keys


def test_subdir_filename_collision_avoided(tmp_path: Path) -> None:
    """Two `spec.md` in different subdirs MUST NOT clobber each other."""
    p = tmp_path / "proj"
    docs = p / "input" / "docs"
    (docs / "a").mkdir(parents=True)
    (docs / "b").mkdir(parents=True)
    (docs / "a" / "spec.md").write_text("alpha content")
    (docs / "b" / "spec.md").write_text("beta content")
    extract_text_pipeline(p)
    extracted = list(
        (p / "phase1" / "input_doc").glob("*.txt"))
    names = [f.name for f in extracted]
    assert "a__spec.txt" in names, names
    assert "b__spec.txt" in names, names
    assert (p / "phase1" / "input_doc" / "a__spec.txt"
            ).read_text() == "alpha content"
    assert (p / "phase1" / "input_doc" / "b__spec.txt"
            ).read_text() == "beta content"


# ---------------------------------------------------------------------------
# BUG 2 — extension coverage.
# ---------------------------------------------------------------------------

def test_rst_file_extracted(tmp_path: Path) -> None:
    f = tmp_path / "spec.rst"
    f.write_text("RST title\n=========\n\nbody text here.\n")
    text = extract_one(f)
    assert "RST title" in text
    assert "body text here" in text


def test_adoc_file_extracted(tmp_path: Path) -> None:
    f = tmp_path / "spec.adoc"
    f.write_text("= AsciiDoc Title\n\nparagraph body\n")
    text = extract_one(f)
    assert "AsciiDoc Title" in text


def test_html_file_strips_tags(tmp_path: Path) -> None:
    f = tmp_path / "page.html"
    f.write_text(
        "<html><head><title>spec</title>"
        "<style>.x{}</style></head>"
        "<body><h1>API</h1><p>command list:</p>"
        "<ul><li>READ</li><li>WRITE</li></ul>"
        "<script>alert(1)</script></body></html>")
    text = extract_html(f)
    assert "API" in text
    assert "command list" in text
    assert "READ" in text
    assert "WRITE" in text
    # Tags themselves must be stripped, scripts dropped.
    assert "<h1>" not in text
    assert "<script>" not in text
    assert "alert(1)" not in text


def test_extensionless_plain_text_accepted(tmp_path: Path) -> None:
    f = tmp_path / "MEMO"
    f.write_text("plain ASCII memo content\nwith multiple lines\n")
    text = extract_one(f)
    assert "plain ASCII memo content" in text


def test_extensionless_binary_rejected(tmp_path: Path) -> None:
    """Binary file with no extension should NOT be extracted."""
    f = tmp_path / "blob"
    f.write_bytes(b"\x00\x01\x02\x03binarydata\xff\xfe\x00x" * 64)
    text = extract_extensionless_text(f)
    assert text == ""


def test_extensionless_short_pure_text_accepted(tmp_path: Path) -> None:
    f = tmp_path / "NOTE"
    f.write_bytes(b"short text note\n")
    text = extract_extensionless_text(f)
    assert "short text note" in text


def test_odt_file_extracted(tmp_path: Path) -> None:
    """Synthesise a minimal ODT (zip + content.xml) and verify
    extraction picks up the visible text."""
    odt = tmp_path / "spec.odt"
    content_xml = (
        '<?xml version="1.0"?>'
        '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        '<text:p>OTP byte 0x05 stores serial number.</text:p>'
        '<text:p>Wake-up sequence: 70 70 70.</text:p>'
        '</office:document-content>')
    with zipfile.ZipFile(odt, "w") as z:
        z.writestr("content.xml", content_xml)
    text = extract_odt(odt)
    assert "OTP byte 0x05" in text
    assert "Wake-up sequence" in text


# ---------------------------------------------------------------------------
# Visibility — extraction_skipped.json.
# ---------------------------------------------------------------------------

def test_skip_log_lists_unconvertible_files(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    docs = p / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "real.md").write_text("real content")
    # Binary archive — should be deliberately skipped.
    (docs / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    # Extension-less binary blob — should also be skipped (sniff fails).
    (docs / "blob").write_bytes(b"\x00\x01\x02\x03" * 200)
    extract_text_pipeline(p)
    log = p / "phase1" / "extraction_skipped.json"
    assert log.exists()
    data = json.loads(log.read_text())
    paths = [s["path"] for s in data["skipped"]]
    assert any("image.png" in s for s in paths)
    assert any("blob" in s for s in paths)
    assert data["total_extracted"] == 1  # real.md


def test_skip_log_empty_when_all_files_render(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    docs = p / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("alpha")
    (docs / "b.txt").write_text("beta")
    extract_text_pipeline(p)
    log = p / "phase1" / "extraction_skipped.json"
    data = json.loads(log.read_text())
    assert data["skipped"] == []
    assert data["total_extracted"] == 2


# ---------------------------------------------------------------------------
# Combined fixture matching issue #3 sub-bug 5 (regression fixture).
# ---------------------------------------------------------------------------

def test_issue_3_full_regression_fixture(tmp_path: Path) -> None:
    """The fixture issue #3 #5 explicitly asks for: every supported
    format ingested, no silent drops."""
    p = tmp_path / "proj"
    docs = p / "input" / "docs"
    spec = docs / "spec"
    spec.mkdir(parents=True)
    (docs / "README.md").write_text("# project README\n")
    (spec / "spec.txt").write_text("plain spec text")
    (spec / "spec.rst").write_text("RST spec\n========\n")
    (spec / "spec.adoc").write_text("= AsciiDoc spec")
    (docs / "MEMO").write_text("memo without extension")
    out = extract_text_pipeline(p)
    # All five present; nothing in skip log.
    log = json.loads((p / "phase1" / "extraction_skipped.json").read_text())
    assert log["skipped"] == [], log
    assert log["total_extracted"] == 5
    keys = list(out.keys())
    assert any("README" in k for k in keys)
    assert any("spec__spec.txt" in k for k in keys)
    assert any("spec__spec.rst" in k for k in keys)
    assert any("spec__spec.adoc" in k for k in keys)
    assert any("MEMO" in k for k in keys)
