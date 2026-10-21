#!/usr/bin/env python3
"""Extract an explicitly tabulated DFT scan topology into L20.

The extractor is deliberately narrow. A source document must place a
Markdown table under a DFT/scan heading and the table must name every field
the existing L20 consumer needs: chain name, length, scan input, scan output
and clock. Prose mentions, examples, partial rows and inferred port names do
not become a topology.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from l_doc_consumer_contract import input_doc_texts  # noqa: E402


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SCOPE = re.compile(
    r"\b(?:dft|design\s+for\s+test|scan(?:[- ]chain)?(?:\s+topology)?)\b", re.I)
_FENCE = re.compile(r"^\s*(\x60{3,}|~{3,})")
_SEP_CELL = re.compile(r"^:?-{3,}:?$")
_ALIASES = {
    "name": {"name", "chain", "chain name", "scan chain"},
    "length": {"length", "chain length", "flop count", "scan length"},
    "scan_in": {"scan in", "scan_in", "scan-in", "si", "input port"},
    "scan_out": {"scan out", "scan_out", "scan-out", "so", "output port"},
    "clock": {"clock", "scan clock", "shift clock", "clock domain"},
    "frequency_mhz": {
        "frequency mhz", "frequency_mhz", "shift frequency mhz",
        "shift_freq_mhz", "mhz",
    },
}
_REQUIRED = ("name", "length", "scan_in", "scan_out", "clock")


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().strip("\x60").lower())


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _column_map(headers: list[str]) -> Optional[dict[str, int]]:
    found: dict[str, int] = {}
    for index, raw in enumerate(headers):
        name = _norm(raw)
        for canonical, aliases in _ALIASES.items():
            if name in aliases:
                if canonical in found:
                    return None
                found[canonical] = index
                break
    return found if all(key in found for key in _REQUIRED) else None


def _positive_int(raw: str) -> Optional[int]:
    token = raw.replace(",", "").strip()
    if not re.fullmatch(r"[0-9]+", token):
        return None
    value = int(token)
    return value if value > 0 else None


def _positive_float(raw: str) -> Optional[float]:
    token = raw.replace(",", "").strip()
    try:
        value = float(token)
    except ValueError:
        return None
    return value if value > 0 else None


def _masked_lines(text: str) -> list[str]:
    """Keep line numbers stable while removing fenced examples."""
    result, fence = [], None
    for line in text.splitlines():
        mark = _FENCE.match(line)
        if mark:
            token = mark.group(1)
            if fence is None:
                fence = token[0]
            elif token[0] == fence:
                fence = None
            result.append("")
        else:
            result.append("" if fence else line)
    return result


def extract_dft_scan_topology(project: Path) -> Optional[Dict[str, Any]]:
    chains: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    source_documents: set[str] = set()
    candidate_tables = 0
    # The docs front door normalises every input/docs file into
    # phase1/input_doc with byte-identical text.  Prefer the pristine source
    # path and skip an exact-content mirror; two independently authored files
    # with different bytes are still both parsed and conflicting chain names
    # remain an error.
    documents = input_doc_texts(project)
    documents.sort(key=lambda item: (
        0 if item[0].relative_to(project).parts[:2] == ("input", "docs") else 1,
        item[0].relative_to(project).as_posix(),
    ))
    seen_content: set[str] = set()
    for path, text in documents:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in seen_content:
            continue
        seen_content.add(digest)
        source = path.relative_to(project).as_posix()
        lines = _masked_lines(text)
        scope_depth: Optional[int] = None
        i = 0
        while i < len(lines):
            heading = _HEADING.match(lines[i])
            if heading:
                depth = len(heading.group(1))
                if _SCOPE.search(heading.group(2)):
                    scope_depth = depth
                elif scope_depth is not None and depth <= scope_depth:
                    scope_depth = None
                i += 1
                continue
            if scope_depth is None or not lines[i].lstrip().startswith("|"):
                i += 1
                continue
            headers = _cells(lines[i])
            if i + 1 >= len(lines):
                i += 1
                continue
            separators = _cells(lines[i + 1])
            if len(separators) != len(headers) or not all(
                    _SEP_CELL.fullmatch(cell.replace(" ", ""))
                    for cell in separators):
                i += 1
                continue
            columns = _column_map(headers)
            if columns is None:
                i += 2
                continue
            candidate_tables += 1
            i += 2
            table_rows = 0
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                values = _cells(lines[i])
                if len(values) != len(headers):
                    raise ValueError(f"{source}:{i + 1}: malformed DFT table row")
                row = {key: values[index] for key, index in columns.items()}
                length = _positive_int(row["length"])
                if (length is None or any(not row[key].strip() for key in
                                          ("name", "scan_in", "scan_out", "clock"))):
                    raise ValueError(
                        f"{source}:{i + 1}: DFT row lacks a positive length "
                        "or typed ports/clock")
                chain: Dict[str, Any] = {
                    "name": row["name"].strip(),
                    "length": length,
                    "scan_in": row["scan_in"].strip(),
                    "scan_out": row["scan_out"].strip(),
                    "clock": row["clock"].strip(),
                }
                if "frequency_mhz" in row and row["frequency_mhz"].strip():
                    frequency = _positive_float(row["frequency_mhz"])
                    if frequency is None:
                        raise ValueError(
                            f"{source}:{i + 1}: invalid positive frequency_mhz")
                    chain["frequency_mhz"] = frequency
                chains.append(chain)
                evidence.append({
                    "source": source,
                    "line": i + 1,
                    "literal": lines[i].strip(),
                    "chain": chain["name"],
                })
                source_documents.add(source)
                table_rows += 1
                i += 1
            if table_rows == 0:
                raise ValueError(
                    f"{source}:{i + 1}: DFT topology table has no data rows")
    if not chains:
        return None
    names = [str(chain["name"]) for chain in chains]
    if len(set(names)) != len(names):
        raise ValueError("DFT topology has duplicate scan-chain names")
    return {
        "fields": {"dft_present": True, "scan_chains": chains},
        "extraction_evidence": {"scan_chains": evidence},
        "source_documents": sorted(source_documents),
        "scan": {
            "candidate_tables": candidate_tables,
            "typed_chain_count": len(chains),
            "documents": sorted(source_documents),
        },
    }


__all__ = ["extract_dft_scan_topology"]
