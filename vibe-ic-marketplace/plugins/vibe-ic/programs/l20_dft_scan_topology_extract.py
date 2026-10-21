#!/usr/bin/env python3
"""Extract an explicit, typed scan topology from design-owned input docs.

Only a Markdown table in a DFT/scan-topology section is accepted.  The table
must carry all five fields consumed by Step 11: name, length, scan_in,
scan_out, and clock.  Prose, plans, unknowns, partial rows, duplicate names,
and multiple declarations are deliberately left unextracted.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".adoc", ".asciidoc"}
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_SECTION_RE = re.compile(
    r"\b(?:dft\b.*\bscan|scan\b.*\b(?:topology|chains?))\b", re.I)
_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
_UNRESOLVED_RE = re.compile(
    r"^(?:n/?a|none|unknown|tbd|todo|planned|pending|deferred|unspecified)$",
    re.I,
)
_ALIASES = {
    "name": {"name", "chain", "chain name", "chain_name", "id"},
    "length": {"length", "len", "flop count", "flop_count", "ff count",
               "ff_count", "depth", "num flops", "num_flops", "cells"},
    "scan_in": {"scan in", "scan_in", "scan-in", "scan in port",
                "scan_in_port", "si", "sin", "input port", "input_port"},
    "scan_out": {"scan out", "scan_out", "scan-out", "scan out port",
                 "scan_out_port", "so", "sout", "output port", "output_port"},
    "clock": {"clock", "clk", "scan clock", "scan_clock", "shift clock",
              "shift_clock", "clock domain", "clock_domain"},
    "frequency_mhz": {"frequency mhz", "frequency_mhz",
                      "shift frequency mhz", "shift_frequency_mhz",
                      "shift freq mhz", "shift_freq_mhz"},
}
_REQUIRED_COLUMNS = {"name", "length", "scan_in", "scan_out", "clock"}


def _cells(line: str) -> List[str]:
    stripped = line.strip()
    if "|" not in stripped:
        return []
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _normal(value: str) -> str:
    # Markdown emphasis/backticks are presentation.  Underscore is syntax in
    # canonical headers such as ``scan_in`` and must survive normalisation.
    value = re.sub(r"[`*]", "", value.strip().lower())
    return re.sub(r"\s+", " ", value)


def _column_map(headers: List[str]) -> Optional[Dict[str, int]]:
    found: Dict[str, int] = {}
    for index, raw in enumerate(headers):
        value = _normal(raw)
        for canonical, aliases in _ALIASES.items():
            if value in aliases:
                if canonical in found:
                    return None
                found[canonical] = index
    return found if _REQUIRED_COLUMNS.issubset(found) else None


def _positive_decimal_integer(value: str) -> Optional[int]:
    """Strict positive decimal, optionally with conventional 3-digit groups."""
    if not re.fullmatch(r"(?:[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)",
                        value):
        return None
    return int(value.replace(",", ""))


def _positive_decimal(value: str) -> Optional[float]:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
        return None
    number = float(value)
    return number if number > 0 else None


def _table_at(lines: List[str], index: int, source: str,
              section: str, digest: str) -> Optional[Tuple[List[dict], int]]:
    headers = _cells(lines[index])
    if not headers or index + 1 >= len(lines):
        return None
    separators = _cells(lines[index + 1])
    if len(separators) != len(headers) or not all(
            _SEPARATOR_CELL_RE.fullmatch(cell) for cell in separators):
        return None
    columns = _column_map(headers)
    if columns is None:
        return None

    rows: List[dict] = []
    cursor = index + 2
    while cursor < len(lines):
        values = _cells(lines[cursor])
        if not values:
            break
        if len(values) != len(headers):
            return None
        selected = {key: values[pos].strip() for key, pos in columns.items()}
        if any(not value or _UNRESOLVED_RE.fullmatch(value)
               for value in selected.values()):
            return None
        length = _positive_decimal_integer(selected["length"])
        if length is None:
            return None
        row = {
            "name": selected["name"],
            "length": length,
            "scan_in": selected["scan_in"],
            "scan_out": selected["scan_out"],
            "clock": selected["clock"],
            "source": {
                "document": source,
                "section": section,
                "header_line": index + 1,
                "row_line": cursor + 1,
                "row_sha256": hashlib.sha256(
                    lines[cursor].encode("utf-8")).hexdigest(),
                "document_sha256": digest,
            },
        }
        if "frequency_mhz" in selected:
            frequency = _positive_decimal(selected["frequency_mhz"])
            if frequency is None:
                return None
            row["frequency_mhz"] = frequency
        rows.append(row)
        cursor += 1
    return (rows, cursor) if rows else None


def extract_dft_scan_topology(project: Path) -> Optional[Dict[str, Any]]:
    """Return one unambiguous typed declaration, otherwise ``None``."""
    project = Path(project)
    docs_dir = project / "input" / "docs"
    if not docs_dir.is_dir():
        return None

    declarations: List[List[dict]] = []
    scanned: List[str] = []
    for path in sorted(docs_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="strict")
            source = path.relative_to(project).as_posix()
        except (OSError, UnicodeError, ValueError):
            return None
        scanned.append(source)
        digest = hashlib.sha256(raw).hexdigest()
        lines = text.splitlines()
        headings: List[Tuple[int, str]] = []
        in_fence = False
        index = 0
        while index < len(lines):
            line = lines[index]
            if re.match(r"^\s*(```|~~~)", line):
                in_fence = not in_fence
                index += 1
                continue
            heading = _HEADING_RE.match(line) if not in_fence else None
            if heading:
                level, title = len(heading.group(1)), heading.group(2).strip()
                headings = [(depth, name) for depth, name in headings
                            if depth < level]
                headings.append((level, title))
                index += 1
                continue
            section = " / ".join(name for _depth, name in headings)
            if not in_fence and _SECTION_RE.search(section):
                parsed = _table_at(lines, index, source, section, digest)
                if parsed:
                    rows, index = parsed
                    declarations.append(rows)
                    continue
            index += 1

    # Multiple tables are ambiguous even when they happen to agree: there is
    # no source-owned precedence rule telling Phase 1 which declaration wins.
    if len(declarations) != 1:
        return None
    chains = declarations[0]
    names = [str(chain["name"]).casefold() for chain in chains]
    if len(names) != len(set(names)):
        return None
    return {
        "scan_chains": chains,
        "dft_present": True,
        "scan_topology_sources": [chain["source"] for chain in chains],
        "scan_topology_scan": {
            "documents_scanned": scanned,
            "documents_scanned_count": len(scanned),
            "declarations_found": 1,
            "extracted_by": ("l20_dft_scan_topology_extract"
                             ".extract_dft_scan_topology"),
        },
    }


__all__ = ["extract_dft_scan_topology"]
