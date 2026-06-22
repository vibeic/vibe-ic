#!/usr/bin/env python3
"""structured_table_extractor.py — ONE general extractor for the whole TABLE tier.

Most structured artifacts in an IC spec are a pipe / column-aligned table whose
HEADER identifies the type (register map, command/opcode table, encoding table,
memory map, clock/power domain, PVT corner, test-vector, coverage/traceability
matrix, ...). Rather than a bespoke parser per type, this extracts EVERY table in
the document, classifies each by a header SIGNATURE, and returns structured rows.
This is the deterministic BASELINE for all table-tier element types at once; the
dual-pass AI pass still cross-checks and the ai_only finds drive convergence.

§4.05: a table is classified to a SPECIFIC element_type only when its header
matches that type's signature UNAMBIGUOUSLY (exactly one type matches). A table
that matches none -> "structured_table" (generic, still extracted). A table that
matches several -> generic too (never a wrong-confident label). chip-AGNOSTIC.
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional, Set, Tuple

# element_type -> (anchor_keywords, support_keywords): a header must contain >=1
# anchor AND >=1 support keyword (case-insensitive, per-cell) to classify as it.
SIGNATURES: Dict[str, Tuple[Set[str], Set[str]]] = {
    "register_map":          ({"register", "reg", "address", "offset", "addr"},
                              {"bits", "field", "access", "reset", "rw", "r/w"}),
    "command_opcode_table":  ({"command", "opcode", "instruction", "cmd"},
                              {"operation", "operand", "description", "function", "encoding"}),
    "encoding_table":        ({"encoding", "code", "value", "symbol"},
                              {"meaning", "description", "state", "name", "mapping"}),
    "memory_map":            ({"region", "block", "segment", "memory"},
                              {"address", "range", "start", "end", "base", "size"}),
    "clock_domain_table":    ({"clock", "clk", "domain"},
                              {"frequency", "freq", "source", "crossing", "mhz"}),
    "power_domain_table":    ({"power", "domain", "rail", "island"},
                              {"voltage", "vdd", "isolation", "retention", "level"}),
    "pvt_corner_table":      ({"corner", "pvt"},
                              {"process", "voltage", "temperature", "temp", "slow", "fast"}),
    "test_vector_table":     ({"vector", "stimulus", "test", "input"},
                              {"expected", "output", "result", "golden"}),
    "function_op_table":     ({"select", "mode", "alu", "func"},
                              {"result", "action", "output"}),
    "coverage_matrix":       ({"feature", "coverage", "scenario"},
                              {"test", "covered", "status", "result"}),
    "traceability_matrix":   ({"requirement", "req", "spec"},
                              {"design", "verification", "test", "implements"}),
    "data_conversion_table": ({"conversion", "convert"},
                              {"input", "output", "decimal", "binary", "gray", "bcd"}),
    "channel_signal_catalog": ({"channel", "signal"},
                               {"direction", "width", "description", "role"}),
    "lookup_rom_table":      ({"rom", "lookup", "lut", "memory"},
                              {"data", "value", "contents", "entry"}),
    "behavioral_sequence":   ({"cycle", "step", "time", "clock"},
                              {"state", "action", "transaction", "operation"}),
    "timing_parameter_table": ({"parameter", "timing", "symbol"},
                               {"min", "max", "typ", "ns", "setup", "hold"}),
    "packet_frame_format":   ({"field", "frame", "packet", "byte"},
                              {"offset", "bytes", "length", "bits", "position"}),
}


def _cells(line: str) -> List[str]:
    s = line.strip().strip("|")
    if "|" not in s:
        return []
    return [c.strip() for c in s.split("|")]


def _is_sep(cells: List[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c)


def _classify(header_cells: List[str]) -> Optional[str]:
    # tokenize header cells into WORDS (not substrings: anchor "op" must not match
    # "opcode"/"operation"). "r/w" is kept as a token via the / class.
    words: Set[str] = set()
    for c in header_cells:
        words |= set(re.findall(r"[a-z][a-z/]*", c.lower()))
    matched = []
    for etype, (anchors, supports) in SIGNATURES.items():
        if (anchors & words) and (supports & words):
            matched.append(etype)
    if len(matched) == 1:
        return matched[0]
    return None        # 0 or >1 -> generic (never a wrong-confident label)


def extract_tables(text: str) -> List[Dict]:
    """Every pipe table in the document -> {element_type, columns, rows}. Specific
    element_type when the header signature is unambiguous, else 'structured_table'."""
    lines = text.splitlines()
    out: List[Dict] = []
    i = 0
    n = len(lines)
    while i < n:
        cells = _cells(lines[i])
        if len(cells) >= 2:
            # a table block: a header row, optional separator, then data rows
            header = cells
            j = i + 1
            if j < n and _is_sep(_cells(lines[j])):
                j += 1
            rows = []
            while j < n:
                rc = _cells(lines[j])
                if len(rc) < 2 or _is_sep(rc):
                    break
                rows.append(rc)
                j += 1
            if rows:                       # a real table (header + >=1 data row)
                etype = _classify(header) or "structured_table"
                out.append({
                    "element_type": etype,
                    "columns": header,
                    "rows": [dict(zip(header, r)) for r in rows],
                    "row_count": len(rows),
                })
                i = j
                continue
        i += 1
    return out


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--doc", required=True)
    a = ap.parse_args()
    print(json.dumps(extract_tables(Path(a.doc).read_text(errors="replace")), indent=2))
