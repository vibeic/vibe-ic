"""tests/test_phase1_xml_diagram_extraction.py — v1.6.93

Closes GitHub issue #26 (phase1-skip-ext-silent-drop-svg-dia).

Reject + accept pair for the new Tier-1 extractors that route .svg /
.dia through stdlib XML parsing instead of letting _SKIP_EXT silently
drop them.

Accept tests:
  * test_extract_svg_collects_text_labels_in_order
  * test_extract_svg_handles_svg_namespace
  * test_extract_dia_decompresses_gzip_and_extracts_strings
  * test_extract_dia_strips_hash_padding

Reject tests:
  * test_extract_svg_returns_empty_on_no_text_elements
  * test_extract_dia_raises_clean_error_on_corrupt_gzip
  * test_skip_ext_no_longer_contains_svg_or_dia
"""
from __future__ import annotations

import gzip
import inspect
from pathlib import Path

from programs.phase1_one_shot_runner import (
    _extract_svg,
    _extract_dia,
    extract_text_pipeline,
)


# ---------------------------------------------------------------------------
# Accept — SVG label collection
# ---------------------------------------------------------------------------

def test_extract_svg_collects_text_labels_in_order(tmp_path: Path) -> None:
    """5 labels, no namespace — all extracted in document order."""
    svg = (
        "<svg>"
        "<text>PHY</text>"
        "<text>DRAM_CTRL</text>"
        "<text>FIFO</text>"
        "<title>Top-Level Diagram</title>"
        "<text>UART_TX</text>"
        "</svg>"
    )
    p = tmp_path / "architecture.svg"
    p.write_text(svg, encoding="utf-8")
    out = _extract_svg(p)
    lines = out.splitlines()
    assert lines == [
        "PHY", "DRAM_CTRL", "FIFO", "Top-Level Diagram", "UART_TX",
    ], f"expected 5 labels in order, got {lines!r}"


def test_extract_svg_handles_svg_namespace(tmp_path: Path) -> None:
    """SVG with the default xmlns declared — namespaced <svg:text>
    elements still match because we strip the namespace before
    comparing tag names."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        "<text>core</text>"
        "<text>scan_chain</text>"
        "</svg>"
    )
    p = tmp_path / "ns.svg"
    p.write_text(svg, encoding="utf-8")
    out = _extract_svg(p)
    assert "core" in out
    assert "scan_chain" in out


# ---------------------------------------------------------------------------
# Accept — Dia (.dia) gzip + <dia:string>
# ---------------------------------------------------------------------------

def test_extract_dia_decompresses_gzip_and_extracts_strings(
        tmp_path: Path) -> None:
    """A real .dia file is gzip-compressed XML with namespaced
    <dia:string> elements. Confirm we decompress + walk both."""
    xml = (
        '<?xml version="1.0"?>'
        '<dia:diagram xmlns:dia="http://www.lysator.liu.se/~alla/dia/">'
        '<dia:string>#PHY#</dia:string>'
        '<dia:string>#DRAM#</dia:string>'
        '</dia:diagram>'
    )
    p = tmp_path / "architecture.dia"
    p.write_bytes(gzip.compress(xml.encode("utf-8")))
    out = _extract_dia(p)
    assert "PHY" in out, f"PHY missing from {out!r}"
    assert "DRAM" in out, f"DRAM missing from {out!r}"
    # No '#' padding survives.
    assert "#PHY#" not in out
    assert "#DRAM#" not in out


def test_extract_dia_strips_hash_padding(tmp_path: Path) -> None:
    """Each <dia:string> body has its leading/trailing '#' chars
    stripped (the Dia literal-string convention)."""
    xml = (
        '<dia:diagram xmlns:dia="x">'
        '<dia:string>###hello###</dia:string>'
        '<dia:string>#world#</dia:string>'
        '<dia:string>plain</dia:string>'
        '</dia:diagram>'
    )
    p = tmp_path / "padding.dia"
    p.write_bytes(gzip.compress(xml.encode("utf-8")))
    out = _extract_dia(p)
    lines = out.splitlines()
    assert lines == ["hello", "world", "plain"], (
        f"expected hash-stripped labels, got {lines!r}"
    )


# ---------------------------------------------------------------------------
# Reject — empty / corrupt inputs handled cleanly
# ---------------------------------------------------------------------------

def test_extract_svg_returns_empty_on_no_text_elements(
        tmp_path: Path) -> None:
    """An SVG that draws shapes but has no <text>/<title>/etc. yields
    no labels and so returns the empty string. The caller's
    extraction_skipped.json branch then records the file with reason
    'converter returned empty'."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<rect x="0" y="0" width="10" height="10"/>'
        '<circle cx="5" cy="5" r="3"/>'
        '</svg>'
    )
    p = tmp_path / "shapes_only.svg"
    p.write_text(svg, encoding="utf-8")
    out = _extract_svg(p)
    assert out == "", f"expected empty string, got {out!r}"


def test_extract_dia_raises_clean_error_on_corrupt_gzip(
        tmp_path: Path) -> None:
    """A file claiming to be .dia but containing arbitrary non-gzip,
    non-XML bytes must NOT crash the ingestor — _extract_dia returns
    "" and the surrounding pipeline records it under
    extraction_skipped.json."""
    p = tmp_path / "corrupt.dia"
    p.write_bytes(b"this is not gzip and not xml \x00\x01\x02")
    # Must not raise.
    out = _extract_dia(p)
    assert out == "", f"expected empty string on corrupt input, got {out!r}"


def test_skip_ext_no_longer_contains_svg_or_dia() -> None:
    """Structural assertion: the inline _SKIP_EXT tuple inside
    extract_text_pipeline must no longer name .svg or .dia (which are
    now routed to _extract_svg / _extract_dia), but raster-image
    extensions stay quarantined behind the WARN path."""
    src = inspect.getsource(extract_text_pipeline)
    # Locate the _SKIP_EXT literal block.
    assert "_SKIP_EXT" in src, "_SKIP_EXT not found in source"
    # Crude-but-effective: look at the literal tuple text.
    skip_block_start = src.find("_SKIP_EXT")
    skip_block = src[skip_block_start:skip_block_start + 600]
    assert "'.svg'" not in skip_block and '".svg"' not in skip_block, (
        ".svg must be removed from _SKIP_EXT (now extracted as XML)"
    )
    assert "'.dia'" not in skip_block and '".dia"' not in skip_block, (
        ".dia must be removed from _SKIP_EXT (now extracted as XML)"
    )
    # Raster extensions must still be skipped.
    assert ".png" in skip_block, ".png must remain in _SKIP_EXT"
    assert ".jpg" in skip_block, ".jpg must remain in _SKIP_EXT"


# ---------------------------------------------------------------------------
# End-to-end smoke — pipeline integrates the two extractors
# ---------------------------------------------------------------------------

def test_pipeline_extracts_svg_and_dia_into_extracted_docs(
        tmp_path: Path) -> None:
    """An .svg and a .dia in input/docs/ both produce non-empty
    extracted_docs/ files (not silently dropped)."""
    proj = tmp_path / "proj"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "arch_svg.svg").write_text(
        "<svg><text>PHY</text><text>CORE</text></svg>",
        encoding="utf-8",
    )
    xml = (
        '<dia:diagram xmlns:dia="x">'
        '<dia:string>#FIFO#</dia:string>'
        '</dia:diagram>'
    )
    (docs / "arch_dia.dia").write_bytes(gzip.compress(xml.encode("utf-8")))
    out = extract_text_pipeline(proj)
    # Map keys carry the original suffix per existing convention.
    keys = list(out.keys())
    assert any(k.endswith(".svg") for k in keys), (
        f"no .svg key in pipeline output: {keys!r}"
    )
    assert any(k.endswith(".dia") for k in keys), (
        f"no .dia key in pipeline output: {keys!r}"
    )
    svg_text = next(v for k, v in out.items() if k.endswith(".svg"))
    dia_text = next(v for k, v in out.items() if k.endswith(".dia"))
    assert "PHY" in svg_text and "CORE" in svg_text
    assert "FIFO" in dia_text
