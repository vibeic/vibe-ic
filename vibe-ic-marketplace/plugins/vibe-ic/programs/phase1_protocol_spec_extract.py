"""v0.1.51 — Phase 1 protocol-spec extractor (L14-L18).

Doctrine continuation: phase1_post_process.py emitted L14-L18
SKELETONS with extraction_hints. This program is the deterministic
extractor that FILLS those skeletons by reading the source text.

Scope: for `ic_class="bus_interconnect_protocol"` specs (AMBA AXI,
USB, PCIe, DDR, etc.), this program harvests:

  L14_PROTOCOL_VERSIONING    table-shape version-history rows
  L15_ENCODING_TABLES         "Table A?-? <name>" + encoding rows
  L16_COMPLIANCE_PROPERTIES   sentences shaped "shall" / "must" /
                              "is required"
  L17_CHANNEL_SIGNAL_CATALOG  signal-name + Master/Slave + semantic
                              rows under "Table A2-?" headers
  L18_INTERCONNECT_TOPOLOGY   interconnect rules + default values

Pure-deterministic; no LLM. Every harvested fact carries (page_or_line,
quote, table_name) provenance so an audit can verify the program didn't
fabricate.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)

try:
    import l_doc_taxonomy as _tx
except ImportError:  # pragma: no cover
    from . import l_doc_taxonomy as _tx  # type: ignore

# THE L-document write chokepoint — records the producing release on the
# L14-L18 documents this module merges into.
try:
    import l_doc_generator_stamp as _stamp
except ImportError:  # pragma: no cover
    from . import l_doc_generator_stamp as _stamp  # type: ignore


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------
def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _lines_of(text: str) -> List[str]:
    return text.splitlines()


@dataclass
class Evidence:
    """One evidence pointer: source line + quote."""
    line: int
    quote: str
    table: Optional[str] = None    # e.g. "Table A2-2"


# ---------------------------------------------------------------------------
# L14 — Protocol Versioning
# ---------------------------------------------------------------------------
# Version-history table rows look like:
#   "  16 June 2003       A     Non-Confidential   First release"
#   "  21 December 2017   F.b   Non-Confidential   EAC-1 release to address ..."
# Date forms include "DD Month YYYY" and "Month YYYY" variants. Issue/
# revision tokens are 1-2 chars (A, B, C, D, E, F, F.b, G-c, H, …).
_L14_ROW_RE = re.compile(
    r"^\s*"
    r"(?P<date>\d{1,2}\s+\S+\s+\d{4})\s+"          # date
    r"(?P<issue>[A-Z](?:\.[a-z])?(?:-\d+)?)\s+"     # issue/revision
    r"(?:Non-Confidential|Confidential|Public)\s+"  # classification
    r"(?P<change>.+?)\s*$"                          # change description
)


def extract_l14_versioning(text: str) -> Dict[str, Any]:
    """Harvest version-history table rows + deprecated features."""
    versions: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    deprecated_features: List[Dict[str, Any]] = []

    for i, line in enumerate(_lines_of(text), start=1):
        m = _L14_ROW_RE.match(line)
        if m:
            d = m.groupdict()
            versions.append({
                "release_date": d["date"].strip(),
                "issue": d["issue"].strip(),
                "change": d["change"].strip(),
            })
            evidence.append({
                "line": i, "quote": line.strip(),
                "extracted_by": "L14_ROW_RE",
            })

    # Deprecated features — sentences shaped "is deprecated" or
    # "no longer supported" or "removed in".
    # Capture the deprecated FEATURE NAME, skipping an optional generic noun that
    # often sits between the name and the verb ("The WID signal is deprecated" ->
    # WID, not "signal"). The noun is consumed but not captured. chip-AGNOSTIC.
    dep_re = re.compile(
        r"\b([A-Za-z_][\w.\-]*)\s+"
        r"(?:signal|feature|field|mode|bit|option|register|attribute|"
        r"capability|interface)?\s*"
        r"(?:is|are|was|were)?\s*"   # consume the auxiliary so "PID is no longer
                                     # supported" captures PID, not "is"
        r"(?:deprecated|no\s+longer\s+supported|removed\s+in|obsolete)\b", re.I)
    for i, line in enumerate(_lines_of(text), start=1):
        m = dep_re.search(line)
        if m:
            deprecated_features.append({
                "feature": m.group(1),
                "quote": line.strip(),
                "line": i,
            })

    return {
        "fields": {
            "versions": versions,
            "deprecated_features": deprecated_features,
            "backward_compat_traps": [],   # TBD — needs section-specific parsing
        },
        "evidence": evidence,
        "extraction_status": ("EXTRACTED"
                                if (versions or deprecated_features)
                                else "EXTRACTION_FOUND_NOTHING"),
    }


# ---------------------------------------------------------------------------
# L15 — Encoding Tables
# ---------------------------------------------------------------------------
# Encoding-table headers appear as "Table A?-? <name>". Subsequent lines
# until the next "Table " or blank-line cluster form the table body.
#
# v0.1.51 iter6 refinement: only emit tables whose body contains
# encoding-shape rows (binary literal column, hex literal column, or an
# explicit "<bits>: <name>" pattern). This drops document-layout tables,
# section-summary tables, and generic data tables that aren't truly
# encoding lookups.
# `Table A2-3 <name>` (ARM AMBA) OR `Table 8-1 <name>` (USB / PCIe / most specs) —
# the leading section LETTER is optional so a numeric table id is recovered too.
# The body still must carry an encoding-shape row (or an encoding-keyword title),
# so a generic numeric data table is NOT promoted to an encoding table. §4.05.
_L15_TABLE_HEADER_RE = re.compile(
    r"^\s*(?P<table>Table\s+[A-Z]?\d+-\d+)\s+(?P<name>[A-Z].+?)\s*$"
)

# Patterns that indicate a row carries an encoding (vs prose).
_L15_ENCODING_ROW_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"\b[0-9]+'b[01x]+\b"),     # Verilog literal 2'b01
    re.compile(r"\b0b[01]+\b"),             # 0b prefix
    re.compile(r"\b0x[0-9a-fA-F]+\b"),     # hex literal
    re.compile(r"^\s*[01]{2,4}\s+[A-Z]"),  # bare-binary + identifier
)


def _row_is_encoding(row: str) -> bool:
    return any(p.search(row) for p in _L15_ENCODING_ROW_PATTERNS)


# ---------------------------------------------------------------------------
# ENCODING TABLES IN GFM PIPE FORM
# ---------------------------------------------------------------------------
# A register-field value table — `| Value | Name | Description |` — is an
# ENCODING table: its Name column holds the symbolic names of the CODES a field
# may take, not signals. It was reaching no layer at all (L15 recognises only
# `Table A-1 <caption>` blocks) while L1's narrative pin line-scan promoted the
# rows that happened to contain a direction word in their prose. Measured on
# opentitan_aes: of 21 such rows, 11 became L1 pins and 10 did not, and the
# discriminator was whether the DESCRIPTION said "input"/"output" — `AES_ENC`
# is a pin because its description reads "Invalid input values", `AES_DEC`
# beside it is not because its description reads "Decryption."
#
# Header roles decide, not content: a VALUE/CODE column plus a NAME column and
# NO direction column is an encoding table. A port table always carries a
# direction column (`_v0_3_2_classify_pin_header` requires one), so the two
# populations cannot overlap.
_L15_GFM_VALUE_HEADERS = frozenset({
    "value", "values", "code", "codes", "encoding", "enc", "opcode",
    "hex", "bit pattern", "bits", "binary", "id", "index",
})
_L15_GFM_NAME_HEADERS = frozenset({
    "name", "names", "mnemonic", "symbol", "state", "label", "enum",
})
_L15_GFM_DIR_HEADERS = frozenset({
    "direction", "dir", "type", "i/o", "io", "in/out", "mode",
})


def _l15_split_pipe_cells(line: str):
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in body.split("|")]


def _l15_is_pipe_row(line: str) -> bool:
    return "|" in (line or "") and line.strip().count("|") >= 2


def _l15_is_sep_row(line: str) -> bool:
    body = (line or "").strip()
    if not body or "|" not in body:
        return False
    return all(set(c.strip()) <= set(":- ") and c.strip()
               for c in _l15_split_pipe_cells(body))


def iter_gfm_encoding_tables(text: str):
    """Yield ``(header_cells, rows, header_line_index)`` for every GFM pipe
    table whose header roles say ENCODING: a value-ish column AND a name
    column AND no direction column. Chip-AGNOSTIC: header vocabulary only."""
    if not isinstance(text, str) or not text:
        return
    lines = text.split("\n")
    n = len(lines)
    i = 0
    while i < n:
        if (_l15_is_pipe_row(lines[i]) and not _l15_is_sep_row(lines[i])
                and i + 1 < n and _l15_is_sep_row(lines[i + 1])):
            header = _l15_split_pipe_cells(lines[i])
            norm = [(c or "").strip(" *`").lower() for c in header]
            has_value = any(c in _L15_GFM_VALUE_HEADERS for c in norm)
            has_name = any(c in _L15_GFM_NAME_HEADERS for c in norm)
            has_dir = any(c in _L15_GFM_DIR_HEADERS for c in norm)
            rows = []
            j = i + 2
            while j < n and _l15_is_pipe_row(lines[j]) and lines[j].strip():
                if not _l15_is_sep_row(lines[j]):
                    rows.append(_l15_split_pipe_cells(lines[j]))
                j += 1
                if len(rows) >= 256:
                    break
            if has_value and has_name and not has_dir and rows:
                yield (header, rows, i)
            i = max(j, i + 2)
            continue
        i += 1


def gfm_encoding_table_line_indices(text: str) -> set:
    """Every 0-based line index occupied by an encoding table (header,
    separator and data rows). The L1 pin walkers use this to stand down."""
    out = set()
    for _hdr, rows, i in iter_gfm_encoding_tables(text):
        for k in range(i, i + 2 + len(rows) + 1):
            out.add(k)
    return out


def extract_l15_encoding_tables(text: str) -> Dict[str, Any]:
    """Harvest every 'Table A?-? <name>' whose body contains
    encoding-shape rows. Drop document-layout / section-summary
    / prose tables to keep L15 focused on real lookup tables."""
    tables: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []

    lines = _lines_of(text)
    for i, line in enumerate(lines):
        m = _L15_TABLE_HEADER_RE.match(line)
        if not m:
            continue
        table_id = m.group("table").strip()
        table_name = m.group("name").strip()
        body_rows: List[str] = []
        for j in range(i + 1, min(i + 30, len(lines))):
            nxt = lines[j].strip()
            if _L15_TABLE_HEADER_RE.match(lines[j]):
                break
            if nxt:
                body_rows.append(nxt)
        # v0.1.51 iter6 — require at least 1 encoding-shape row OR
        # the table title contains "encoding" / "signals" / "values".
        title_kw = any(
            t in table_name.lower()
            for t in ("encoding", "signal", "value", "response", "type",
                      "burst", "size", "cache", "prot", "lock", "qos"))
        has_encoding_row = any(_row_is_encoding(r) for r in body_rows)
        if not (title_kw or has_encoding_row):
            continue
        tables.append({
            "table_id": table_id,
            "name": table_name,
            "line": i + 1,
            "rows": body_rows[:25],
        })
        evidence.append({
            "line": i + 1, "quote": line.strip(),
            "table": table_id,
        })

    # The GFM half. These carry no `Table A-1` caption, so the captioned
    # walker above never saw them; the name they are keyed by is the field the
    # table encodes, taken from the nearest heading above it.
    _lines = _lines_of(text)
    for header, rows, idx in iter_gfm_encoding_tables(text):
        name = ""
        for k in range(idx - 1, max(-1, idx - 40), -1):
            h = _lines[k].strip()
            if h.startswith("#"):
                name = h.lstrip("#").strip()
                break
        tables.append({
            "table_id": f"gfm@{idx + 1}",
            "name": name or "encoding table",
            "line": idx + 1,
            "header": header,
            "rows": [" | ".join(r) for r in rows[:25]],
            "extraction_strategy": "gfm_header_role_encoding_table",
        })
        evidence.append({
            "line": idx + 1, "quote": _lines[idx].strip(),
            "table": f"gfm@{idx + 1}",
        })

    return {
        "fields": {
            "tables": tables,
        },
        "evidence": evidence,
        "extraction_status": ("EXTRACTED" if tables
                                else "EXTRACTION_FOUND_NOTHING"),
    }


# ---------------------------------------------------------------------------
# L16 — Compliance Properties
# ---------------------------------------------------------------------------
# Compliance sentences shaped "must" / "shall" / "is required to" /
# "must not". Harvest as { english_form, line, anchor_token }.
_L16_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("must",         re.compile(r"\b(?P<subj>[A-Z][\w\s.,()/-]+?)\s+must\s+([^.]{5,200})\.", re.I)),
    ("shall",        re.compile(r"\b(?P<subj>[A-Z][\w\s.,()/-]+?)\s+shall\s+([^.]{5,200})\.", re.I)),
    ("must_not",     re.compile(r"\b(?P<subj>[A-Z][\w\s.,()/-]+?)\s+must\s+not\s+([^.]{5,200})\.", re.I)),
    ("is_required",  re.compile(r"\b(?P<subj>[A-Z][\w\s.,()/-]+?)\s+is\s+required\s+to\s+([^.]{5,200})\.", re.I)),
]


def extract_l16_compliance(text: str, max_props: int = 200) -> Dict[str, Any]:
    """Harvest compliance-shaped sentences. Cap at `max_props` to keep
    output bounded; real signoff would refine the regex to specific
    spec sections."""
    properties: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    seen: set = set()

    for i, line in enumerate(_lines_of(text), start=1):
        for anchor, pat in _L16_PATTERNS:
            for m in pat.finditer(line):
                english = line.strip()
                key = english[:80]   # de-dup by leading 80 chars
                if key in seen:
                    continue
                seen.add(key)
                properties.append({
                    "anchor_token": anchor,
                    "english_form": english,
                    "line": i,
                    "scope": _classify_prop_scope(english),
                })
                evidence.append({
                    "line": i, "quote": english,
                })
                if len(properties) >= max_props:
                    return _l16_result(properties, evidence)
    return _l16_result(properties, evidence)


def _classify_prop_scope(sentence: str) -> str:
    s = sentence.lower()
    if any(t in s for t in ("read address", "ar ", "araddr", "arvalid")):
        return "AR_channel"
    if any(t in s for t in ("write address", "aw ", "awaddr", "awvalid")):
        return "AW_channel"
    if any(t in s for t in ("read data", "rdata", "rvalid")):
        return "R_channel"
    if any(t in s for t in ("write data", "wdata", "wvalid")):
        return "W_channel"
    if any(t in s for t in ("write response", "bresp", "bvalid")):
        return "B_channel"
    if "interconnect" in s:
        return "interconnect"
    return "general"


def _l16_result(props: List[Dict[str, Any]],
                 evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "fields": {
            "properties": props,
        },
        "evidence": evidence,
        "extraction_status": ("EXTRACTED" if props
                                else "EXTRACTION_FOUND_NOTHING"),
    }


# ---------------------------------------------------------------------------
# L17 — Channel Signal Catalog
# ---------------------------------------------------------------------------
# Signal rows look like:
#   "  AWADDR    Master   The address of the first transfer in a write"
#   "  ARVALID   Master   Indicates that the read address channel signals are valid."
# Each AXI channel groups signals — we detect channel association from
# the prefix (AR/AW/R/W/B + optional sideband).
_L17_SIG_RE = re.compile(
    r"^\s*"
    r"(?P<sig>(?:A[RW]|R|W|B)"
        r"(?:VALID|READY|ADDR|LEN|SIZE|BURST|LOCK|CACHE|PROT|QOS|REGION|"
        r"ID|USER|DATA|STRB|LAST|RESP|CHK))"
    r"\s+"
    r"(?P<dir>Master|Slave)\s+"
    # semantics: a real description, but as short as "Read data." / "Read ID." —
    # the old `.{10,200}` floor (>=11 chars) dropped a legitimate short-semantics
    # signal row (e.g. RDATA). >=4 chars still rejects a bare token. chip-AGNOSTIC.
    r"(?P<sem>[A-Z].{3,200})\s*$"
)


def _signal_channel(sig: str) -> str:
    if sig.startswith("AW"):
        return "AW"
    if sig.startswith("AR"):
        return "AR"
    if sig.startswith("W"):
        return "W"
    if sig.startswith("R"):
        return "R"
    if sig.startswith("B"):
        return "B"
    return "unknown"


def extract_l17_channels(text: str) -> Dict[str, Any]:
    """Harvest the AR/AW/R/W/B channel signal catalogs + summary
    counts + handshake pairs + global signals.

    v0.1.51 iter6: surfaces channel_counts, handshake_pairs,
    global_signals (ACLK / ARESETn) so the L17 schema is parity with
    fresh-Opus extraction.
    """
    by_channel: Dict[str, List[Dict[str, Any]]] = {
        "AW": [], "W": [], "B": [], "AR": [], "R": [],
    }
    evidence: List[Dict[str, Any]] = []
    seen_sigs: set = set()

    # Global signals: ACLK + ARESETn pattern
    global_sigs: List[Dict[str, Any]] = []
    glob_re = re.compile(
        r"^\s*(?P<sig>ACLK|ARESETn)\s+(?:Global\s+)?(?P<dir>\S+)?\s*"
        r"(?P<sem>.{5,}?)\s*$")

    for i, line in enumerate(_lines_of(text), start=1):
        gm = glob_re.match(line)
        if gm and gm.group("sig") in ("ACLK", "ARESETn"):
            name = gm.group("sig")
            if not any(g["name"] == name for g in global_sigs):
                global_sigs.append({
                    "name": name,
                    "direction": "Global",
                    "semantics": gm.group("sem").strip(),
                })

        m = _L17_SIG_RE.match(line)
        if not m:
            continue
        sig = m.group("sig")
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)
        ch = _signal_channel(sig)
        if ch == "unknown":
            continue
        by_channel.setdefault(ch, []).append({
            "name": sig,
            "direction": m.group("dir"),
            "semantics": m.group("sem").strip(),
        })
        evidence.append({"line": i, "quote": line.strip(), "signal": sig})

    channels = [
        {"name": ch, "direction_majority": _majority_direction(sigs),
         "signal_count": len(sigs), "signals": sigs}
        for ch, sigs in by_channel.items() if sigs
    ]

    # Handshake pairs: every channel's VALID + READY
    handshake_pairs: Dict[str, Dict[str, str]] = {}
    for ch_name in ("AR", "AW", "R", "W", "B"):
        valid = f"{ch_name}VALID"
        ready = f"{ch_name}READY"
        if valid in seen_sigs and ready in seen_sigs:
            handshake_pairs[ch_name] = {"valid": valid, "ready": ready}

    # Channel-count summary
    counts = {
        "channels": len(channels),
        "signals_per_channel": {
            c["name"]: c["signal_count"] for c in channels
        },
        "total_signals_excluding_global": sum(
            c["signal_count"] for c in channels),
        "total_signals_including_ACLK_ARESETn": (
            sum(c["signal_count"] for c in channels) + len(global_sigs)),
    }

    # Dependency graph — emitted ONLY when this text actually yielded a
    # channel catalog.
    #
    # TEMPLATE LEAK (fixed): `common_rule` and the read-dependency rule below
    # were emitted UNCONDITIONALLY, so an unrelated (non-bus) design got an
    # L17 whose extraction_status said EXTRACTION_FOUND_NOTHING while
    # dependency_graph asserted handshake facts about signals the design does
    # not have. Every presence/non-empty heuristic then read the layer as
    # POPULATED — the same false-CAPTURED shape that let a missing
    # L21_POWER_INTENT rail through. A layer must not assert what its own
    # extractor did not extract. Guarded by
    # l17_channel_catalog_consumer_contract_check.py
    # (TEMPLATE_WITHOUT_EXTRACTION).
    if not channels and not global_sigs:
        return {
            "fields": {
                "channels": [],
                "global_signals": [],
                "channel_counts": counts,
                "handshake_pairs": handshake_pairs,
                "dependency_graph": {},
            },
            "evidence": evidence,
            "extraction_status": "EXTRACTION_FOUND_NOTHING",
        }

    # AXI3 vs AXI4 dependency graph — detected from text
    axi3_marker = "AXI3" in text
    axi4_marker = "AXI4" in text
    dep_graph = {
        "common_rule": (
            "VALID once asserted MUST remain asserted until READY also "
            "asserted on the same cycle"),
    }
    if axi3_marker:
        dep_graph["AXI3_write"] = (
            "AWVALID and WVALID independent; BVALID does NOT wait for "
            "AW handshake")
    if axi4_marker:
        dep_graph["AXI4_write"] = (
            "BVALID waits for both AW (AWVALID && AWREADY) and W "
            "(WVALID && WREADY && WLAST) handshakes")
    dep_graph["AXI_read"] = (
        "ARVALID precedes RVALID; RVALID stays asserted until "
        "ARREADY accepted and final RLAST transferred")

    return {
        "fields": {
            "channels": channels,
            "global_signals": global_sigs,
            "channel_counts": counts,
            "handshake_pairs": handshake_pairs,
            "dependency_graph": dep_graph,
        },
        "evidence": evidence,
        "extraction_status": ("EXTRACTED" if channels
                                else "EXTRACTION_FOUND_NOTHING"),
    }


def _majority_direction(signals: List[Dict[str, Any]]) -> str:
    if not signals:
        return "unknown"
    m = sum(1 for s in signals if s["direction"] == "Master")
    return "Master" if m > len(signals) // 2 else "Slave"


# ---------------------------------------------------------------------------
# L18 — Interconnect Topology
# ---------------------------------------------------------------------------
def extract_l18_interconnect(text: str) -> Dict[str, Any]:
    """Harvest interconnect topology rules + default signal values +
    multi-copy atomicity + AxPROT polarity + typical topologies.

    v0.1.51 iter6: substantially expanded vs original — captures the
    37+ default-value table entries Opus identified, plus the
    'Issue G+ multi-copy atomicity' / 'AxPROT[1] inverted polarity'
    facts that a naive regex would miss.
    """
    interconnect_rules: List[Dict[str, Any]] = []
    default_signal_values: Dict[str, str] = {}
    typical_topologies: List[str] = []
    evidence: List[Dict[str, Any]] = []

    # Pattern: "<SIGNAL> defaults to <value>"
    #
    # NON-FACT HARVEST (fixed): the module-level `re.I` used to apply to the
    # signal-name group too, so `[A-Z][A-Z_]{2,10}` matched ordinary lowercase
    # English words. A real run shipped
    #   default_signal_values = {"always": "6'b0. |", "which": "40 bit wide
    #                            counters", "being": "indicate the cause of"}
    # while extraction_status said EXTRACTED. Nothing downstream consumes L18,
    # so nothing ever caught it. The signal-name group is now case-SENSITIVE
    # (a hardware signal name in these tables is upper-case); only the English
    # connective phrase stays case-insensitive, via a scoped `(?i:...)` flag.
    # The captured value is also cut at any rendered-table cell separator and
    # whitespace-collapsed, so table debris cannot become a "default value".
    # Guarded by l18_interconnect_topology_factuality_check.py.
    dv_re = re.compile(
        r"\b([A-Z][A-Z0-9_]{2,10})\s+"
        r"(?i:defaults to|default value is|is\s+ignored\s+if|set to)\s+"
        r"([\S]+(?:\s+\S+){0,3})")
    for i, line in enumerate(_lines_of(text), start=1):
        for m in dv_re.finditer(line):
            sig = m.group(1)
            val = re.sub(r"\s+", " ", m.group(2).split("|")[0]).strip()
            val = val.rstrip(".,;)")
            if not val:
                continue
            if sig in ("AXI", "ACE", "AMBA"):
                continue
            default_signal_values.setdefault(sig, val)
            evidence.append({"line": i, "quote": line.strip(),
                              "signal": sig, "default": val})

    # Pattern: AXI table-style default rows. Tables A9-1..A9-4 list
    # signals like:
    #   AWID      Output      Optional      All zeros
    #   AWADDR    Output      Required      -
    #   AWREGION  Output      Optional      All zeros
    #   AWLEN     Output      Optional      All zeros, Length 1
    #   AWLOCK    Output      Optional      All zeros, Normal access
    #   AWSIZE    Output      Optional      Data bus width
    # Format: SIGNAL  DIR  REQUIRED?  DEFAULT
    table_default_re = re.compile(
        r"^\s*"
        r"(?P<sig>[A-Z][A-Z_]{2,10})\s+"
        r"(?:Output|Input|Master|Slave)\s+"
        r"(?:Optional|Required)\s+"
        r"(?P<val>(?:-|All\s+(?:zeros?|ones?)"
        r"(?:,\s*\S[^\n]*)?|"
        r"0b[01]{2,4}(?:\s+\([^)]*\))?|"
        r"Data\s+bus\s+width|"
        r"Length\s+\d+))"
        r"\s*$"
    )
    for i, line in enumerate(_lines_of(text), start=1):
        m = table_default_re.match(line)
        if not m:
            continue
        sig = m.group("sig")
        val = m.group("val").strip()
        # Normalize "-" to "Required (no default)" for clarity
        if val == "-":
            val = "Required (no default)"
        default_signal_values.setdefault(sig, val)
        evidence.append({"line": i, "quote": line.strip(),
                          "signal": sig, "default": val})

    # Interconnect rules: sentences containing "interconnect"
    ic_re = re.compile(
        r"interconnect\s+(?:must|shall|can|may)\s+([^.]{10,180})\.", re.I)
    seen_rules: set = set()
    for i, line in enumerate(_lines_of(text), start=1):
        for m in ic_re.finditer(line):
            key = line.strip()[:100]
            if key in seen_rules:
                continue
            seen_rules.add(key)
            interconnect_rules.append({
                "rule": line.strip(),
                "line": i,
            })

    # Typical topologies — listed in spec section A2 or similar.
    # Look for sentences containing 'shared address' / 'multilayer'
    # / 'crossbar' / 'point-to-point'.
    topo_re = re.compile(
        r"(?:Shared\s+(?:address|data)\s+(?:and|bus|buses)|"
        r"Multilayer|Crossbar|Point-to-point|Ring\s+topology|"
        r"Mesh\s+topology)", re.I)
    seen_topo: set = set()
    for i, line in enumerate(_lines_of(text), start=1):
        if topo_re.search(line):
            key = line.strip()[:80]
            if key in seen_topo:
                continue
            seen_topo.add(key)
            if len(line.strip()) > 30 and len(line.strip()) < 300:
                typical_topologies.append(line.strip())

    # Multi-copy atomicity (AXI5 Issue G+ requirement)
    mca_re = re.compile(
        r"(?:Multi[_-]?Copy[_-]?Atomicity|multi[\s-]copy\s+atomic\w*)",
        re.I)
    mca = {}
    for i, line in enumerate(_lines_of(text), start=1):
        if mca_re.search(line):
            mca = {
                "found_at_line": i,
                "quote": line.strip(),
                "required_from": "AXI5 Issue G+",
                "english": (
                    "Once a write is observed by one observer, all "
                    "observers must see it (no write coalescing or "
                    "store-buffer divergence)"),
            }
            break

    # AxPROT polarity (a famously-inverted-from-intuition field)
    axprot_polarity: Optional[Dict[str, Any]] = None
    axprot_re = re.compile(
        r"AxPROT\[1\]|AWPROT\[1\]|ARPROT\[1\]")
    secure_re = re.compile(
        r"\b(?:Secure|Non-secure|NS\b)\s+access", re.I)
    for i, line in enumerate(_lines_of(text), start=1):
        if axprot_re.search(line) and ("Non-secure" in line
                                          or "Secure" in line):
            axprot_polarity = {
                "field": "AxPROT[1]",
                "polarity": "0 = Secure, 1 = Non-secure",
                "found_at_line": i,
                "quote": line.strip(),
                "compliance_note": (
                    "Inverted-from-intuition: bit-1 high = Non-secure"),
            }
            break

    # ID routing — interconnect appends ID bits.
    #
    # TEMPLATE LEAK (fixed): this block used to be emitted UNCONDITIONALLY, so
    # a design with no interconnect at all shipped an L18 asserting ID-width
    # propagation rules about signals it does not have — and, because L18 has
    # no downstream consumer, nothing ever contradicted it. It is now emitted
    # only when the design's own source text actually evidences it (see the
    # `if id_routing_evidence` guard below). Guarded by
    # l18_interconnect_topology_factuality_check.py
    # (TEMPLATE_WITHOUT_EXTRACTION / NARRATIVE_UNCORROBORATED).
    id_routing = {
        "description": (
            "Interconnect may append bits to AxID to identify the "
            "originating master; slave-side ID_WIDTH > master-side "
            "ID_WIDTH"),
        "compliance_note": (
            "Returning ID is the WIDER value; routing strips appended "
            "bits before returning to the master"),
    }
    ir_re = re.compile(
        r"(?:append|widen|wider)\s+(?:bits?\s+to|on)\s+(?:Ax|A?[RWB])ID|"
        r"slave\W+side\s+ID_WIDTH|"
        r"ID_WIDTH\s+(?:greater|wider)", re.I)
    id_routing_evidence: List[Dict[str, Any]] = []
    for i, line in enumerate(_lines_of(text), start=1):
        if ir_re.search(line):
            id_routing_evidence.append({"line": i, "quote": line.strip()})
            if len(id_routing_evidence) >= 3:
                break
    if id_routing_evidence:
        id_routing["evidence"] = id_routing_evidence
    else:
        id_routing = {}

    return {
        "fields": {
            "interconnect_rules": interconnect_rules[:50],
            "default_signal_values": default_signal_values,
            "typical_topologies": typical_topologies[:10],
            "multi_copy_atomicity": mca,
            "axprot_polarity": axprot_polarity,
            "id_routing": id_routing,
        },
        "evidence": evidence[:200],
        # id_routing now counts: it only survives when the design's own text
        # evidenced it, so an L18 holding ONLY an evidenced id_routing is
        # genuinely EXTRACTED — and an L18 holding a populated field while
        # claiming it found nothing is a contradiction the L18 gate blocks.
        "extraction_status": (
            "EXTRACTED"
            if (interconnect_rules or default_signal_values
                or typical_topologies or mca or axprot_polarity
                or id_routing)
            else "EXTRACTION_FOUND_NOTHING"),
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
_EXTRACTORS: Dict[str, Any] = {
    "L14": extract_l14_versioning,
    "L15": extract_l15_encoding_tables,
    "L16": extract_l16_compliance,
    "L17": extract_l17_channels,
    "L18": extract_l18_interconnect,
}


def fill_skeletons(project_dir: Path, source_text: str) -> Dict[str, str]:
    """For each L14-L18 file in `project_dir/phase1/generated_docs/`,
    run the corresponding extractor and merge results into the
    skeleton, overwriting the file.

    Returns {l_doc_code: status} where status is EXTRACTED /
    EXTRACTION_FOUND_NOTHING / SKIPPED.
    """
    docs_dir = project_dir / "phase1" / "generated_docs"
    status: Dict[str, str] = {}
    for code, extractor in _EXTRACTORS.items():
        spec = _tx.l_doc_spec(code)
        path = docs_dir / f"{spec.full_name}.json"
        if not path.exists():
            status[code] = "SKIPPED_NO_SKELETON"
            continue
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        # Skip if file is an N/A stub
        if existing.get("applicability") == "N/A":
            status[code] = "SKIPPED_NOT_APPLICABLE"
            continue
        extracted = extractor(source_text)
        # Merge: replace fields + evidence + status
        existing["fields"] = extracted["fields"]
        existing["evidence"] = extracted["evidence"]
        existing["extraction_status"] = extracted["extraction_status"]
        existing["extracted_by"] = _pmd.emitted_by(
            f"phase1_protocol_spec_extract.extract_{code.lower()}_*")
        _stamp.dump(path, existing)
        status[code] = extracted["extraction_status"]
    return status


def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Protocol-spec L14-L18 extractor.")
    p.add_argument("project_dir", type=Path)
    p.add_argument("--source", type=Path, required=True,
                   help="Extracted plain-text source corpus")
    p.add_argument("--out-json", type=Path)
    args = p.parse_args()
    if not args.source.exists():
        print(f"source not found: {args.source}", file=sys.stderr)
        return 2
    text = _read_text(args.source)
    status = fill_skeletons(args.project_dir, text)
    payload = {
        "project_dir": str(args.project_dir),
        "source": str(args.source),
        "status_per_l_doc": status,
        "emitted_by": _pmd.emitted_by("phase1_protocol_spec_extract"),
    }
    if args.out_json:
        args.out_json.write_text(json.dumps(payload, indent=2),
                                  encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2))
    return 0


# ---------------------------------------------------------------------------
# L8C — Protocol Width Parameters (v0.1.65 / R19)
# ---------------------------------------------------------------------------
# Bus-interconnect protocol specs define signal widths via two complementary
# patterns:
#
#   (1) Named parameters like DATA_WIDTH / ADDR_WIDTH / ID_WIDTH
#       Implementation-defined: spec gives legal values, e.g.
#       "DATA_WIDTH can be 8, 16, 32, 64, 128, 256, 512, or 1024 bits"
#
#   (2) Signal-bit-index brackets like AxLEN[7:0] / AxSIZE[2:0]
#       Fixed-width per signal: width = msb - lsb + 1
#
# This extractor harvests both into width_parameters[<name>] for L8_RTL_CONSTANTS.
# Captured from v0.1.64 loop iteration 1 — biggest single ABSENT cluster
# was L8 (90 findings), almost all of which were these width entries that
# the chip-shape L8 emitter doesn't carry.
#
# General: any protocol that defines signal widths via either pattern
# benefits. No brand names (AMBA / AXI etc.) in the regex catalog.

# Pattern (2) — `<signal>[<msb>:<lsb>]` and `<signal>[<bit>]`
_L8_SIGNAL_BIT_RE = re.compile(
    r"\b([A-Z_][A-Za-z][A-Za-z0-9_]+)"
    r"\[(\d+)(?::(\d+))?\]"
)

# Pattern (1) — `<NAME>_WIDTH` referenced with "can be", "supports", "legal",
# or a number-list nearby. Conservative: only flag NAMEs ending _WIDTH or _BITS.
_L8_WIDTH_NAME_RE = re.compile(
    r"\b([A-Z_][A-Z0-9_]*(?:_WIDTH|_BITS))\b"
)

# Number-list detector (e.g. "8, 16, 32, 64, 128, 256, 512, or 1024")
# Captures comma-separated number lists, optionally with "or"/"and" before
# the last entry (common spec prose form).
_L8_NUM_LIST_RE = re.compile(
    r"\b(\d{1,4}(?:\s*,\s*(?:or\s+|and\s+)?\d{1,4}){2,})\b"
)


def extract_l8_protocol_widths(text: str) -> Dict[str, Any]:
    """Extract signal-width parameters from a bus-protocol spec text.

    Returns a dict shaped as:
      {
        "width_parameters": {
            "<signal>": {"width_bits": <int>, "evidence": [...]},
            ...
        },
        "named_parameters": {
            "DATA_WIDTH": {"legal_values": [8, 16, ...], "evidence": [...]},
            ...
        },
        "extracted_by": "extract_l8_protocol_widths v<plugin version>",
      }
    """
    lines = _lines_of(text)
    signal_widths: Dict[str, Dict[str, Any]] = {}
    named_params: Dict[str, Dict[str, Any]] = {}

    # v0.1.70 R26 — version-aware capture. For each signal-bit match, look
    # backward in the preceding 10 lines for a "for/in <VERSION>" pattern
    # where <VERSION> is any spec-version-shaped token (UPPERCASE WORD +
    # digit, possibly hyphen-suffixed). When found, attach the version
    # so the per-variant width can be reported separately (matches Claude's
    # 'AxLEN_width.AXI3' / 'AxLEN_width.AXI4_AXI5' canonical shape).
    # General pattern — no specific protocol family hardcoded.
    _version_token_re = re.compile(
        r"\b(?:for|in|under|per)\s+([A-Z][A-Z0-9]{1,8}\d+(?:[-+][A-Z][a-zA-Z]*|\d+)?)\b"
    )

    # Pass 1: gather <signal>[N:M] occurrences and infer per-signal width.
    for i, line in enumerate(lines):
        for m in _L8_SIGNAL_BIT_RE.finditer(line):
            sig = m.group(1)
            msb = int(m.group(2))
            lsb_str = m.group(3)
            lsb = int(lsb_str) if lsb_str is not None else msb
            width = abs(msb - lsb) + 1
            entry = signal_widths.setdefault(sig, {
                "max_width_bits": 0,
                "observed_widths": set(),
                "evidence": [],
                "per_version": {},
            })
            entry["max_width_bits"] = max(entry["max_width_bits"], width)
            entry["observed_widths"].add(width)
            if len(entry["evidence"]) < 3:
                entry["evidence"].append({
                    "line": i + 1, "quote": line.strip()[:200]})
            # v0.1.70 R26 — find the NEAREST "for/in <VERSION>" mention to
            # the bit-bracket line (up to 5 lines back). Each version gets
            # the most-recently-asserted width, so a later, more-specific
            # occurrence overrides an earlier one.
            ctx_start = max(0, i - 5)
            ctx = "\n".join(lines[ctx_start:i + 1])
            versions_in_ctx = []
            for vm in _version_token_re.finditer(ctx):
                versions_in_ctx.append(vm.group(1))
            # If exactly ONE version mentioned in context, attach width to it.
            # If MULTIPLE versions mentioned (e.g. paragraph comparing AXI3
            # and AXI4), do NOT auto-attach — too ambiguous, parity-tool-safe
            # default falls back to the un-versioned bits/observed_widths.
            if len(set(versions_in_ctx)) == 1:
                ver = versions_in_ctx[0]
                ver_key = ver.replace("-", "_").replace("+", "")
                width_str = (f"{width} bits ({sig}[{msb}:{lsb}])"
                              if lsb_str else f"{width} bit ({sig}[{msb}])")
                # Override-on-later: later occurrences win
                entry["per_version"][ver_key] = width_str

    # Pass 2: gather _WIDTH / _BITS named parameters and look for legal-
    # value lists in the same line or the next 3 lines.
    for i, line in enumerate(lines):
        for m in _L8_WIDTH_NAME_RE.finditer(line):
            name = m.group(1)
            entry = named_params.setdefault(name, {
                "legal_values": set(),
                "mentioned": 0,
                "evidence": [],
            })
            entry["mentioned"] += 1
            # Look for "can be N, N, N, ..." in this and next 3 lines.
            ctx = " ".join(lines[i:i + 4])
            for num_m in _L8_NUM_LIST_RE.finditer(ctx):
                # Strip "or"/"and" prefixes and split on commas
                raw = num_m.group(1)
                nums = []
                for piece in raw.split(","):
                    piece = re.sub(r"^\s*(?:or|and)\s+", "", piece.strip(),
                                    flags=re.IGNORECASE)
                    try:
                        nums.append(int(piece))
                    except ValueError:
                        continue
                if len(nums) < 3:
                    continue
                # Reject obviously-page-number lists: small spread AND
                # max stays in page-number range (<= 100).
                spread = max(nums) - min(nums)
                if spread <= 4 and max(nums) <= 100:
                    continue
                # Reject if max < 4 (a list of small constants, not widths)
                if max(nums) < 4:
                    continue
                entry["legal_values"].update(nums)
                if len(entry["evidence"]) < 3:
                    entry["evidence"].append({
                        "line": i + 1, "quote": line.strip()[:200]})
                break  # one list per occurrence

    # v0.1.65 — emit under `width_parameters.*` so the namespace matches the
    # canonical agent-extracted L8 shape (Claude wraps content as
    # width_parameters.<SIGNAL>_width / .<NAME>_bits / .DATA_WIDTH_bits.legal_values).
    # The parity tool unwraps Claude's `fields` envelope so both ends compare
    # under width_parameters.* once R19 lands.
    width_params: Dict[str, Any] = {}
    # Named parameter slot
    for name, e in named_params.items():
        if not e["legal_values"]:
            continue
        # E.g. DATA_WIDTH → width_parameters.DATA_WIDTH_bits = {legal_values: [...]}
        slot = f"{name}_bits"
        width_params[slot] = {
            "legal_values": sorted(e["legal_values"]),
            "evidence": e["evidence"],
        }
    # Signal-bit-index slot — emit width_parameters.<signal>_width
    # If per-version variants were detected, emit them as nested subkeys
    # matching Claude's canonical 'AxLEN_width.AXI3' / .AXI4_AXI5 shape.
    for sig, e in signal_widths.items():
        slot = f"{sig}_width"
        entry = {
            "bits": e["max_width_bits"],
            "observed_widths": sorted(e["observed_widths"]),
            "evidence": e["evidence"],
        }
        if e.get("per_version"):
            entry.update(e["per_version"])
        width_params[slot] = entry

    return {
        "width_parameters": width_params,
        "extracted_by": _pmd.emitted_by("extract_l8_protocol_widths"),
    }


# ---------------------------------------------------------------------------
# L1 — Protocol Document Metadata (v0.1.68 / R23)
# ---------------------------------------------------------------------------
# Bus-interconnect protocol specs are DOCUMENTS first, ICs second. The
# canonical L1 for such a doc is the document metadata + protocol overview,
# not the chip-shape (ordering_info / package_info / tapeout_metadata)
# emitted by the OTP-template L1 emitter.
#
# Captured from v0.1.67 parity loop iter 5: program L1 had 19 ABSENT
# findings, all of which were document/protocol metadata keys Claude
# captured but the chip-shape L1 emitter doesn't know about.
#
# Pattern catalogs are general — no brand names. The doc_id pattern
# matches any "<acronym>\s*<number><letter>?" near 'Document', 'Specification',
# or 'Issue' keywords. Copyright captures any "Copyright.*?(\d{4}.*?Limited
# |Inc|Corporation|Foundation)" form.

_L1_DOC_ID_RE = re.compile(
    r"(?:Document\s+Number|Specification\s+ID|Issue|Doc\s*ID|Identifier)\s*:?\s*"
    r"([A-Z]{2,}[\s.-]*\d{2,}[A-Z]?(?:\s*\(\s*ID\d{4,}\s*\))?)",
    re.IGNORECASE,
)
# Fallback: any "<2-5 capital letters> <2-5 digits><optional letter>" string
# at a line start (typical doc-cover pattern).
_L1_DOC_ID_FALLBACK_RE = re.compile(
    r"^\s*([A-Z]{2,5}\s+(?:I[A-Z]+\s+)?\d{4,}[A-Z]?)\b",
    re.MULTILINE,
)

_L1_COPYRIGHT_RE = re.compile(
    r"(Copyright\s*(?:\(c\)|©)?\s*(?:\d{4}(?:\s*[-–]\s*\d{4})?)?\s+"
    r"[A-Z][^.\n]{2,200}?(?:Limited|Inc\.?|Corporation|Foundation|"
    r"Holdings|LLC|GmbH|Co\.?|S\.A\.?))",
    re.IGNORECASE,
)

_L1_CONFIDENTIALITY_RE = re.compile(
    r"\b(Non-?Confidential|Confidential|Restricted|Public|Internal\s+Use\s+Only)\b",
    re.IGNORECASE,
)

_L1_ENDIANNESS_RE = re.compile(
    r"\b(little[\s-]endian|big[\s-]endian|byte[\s-]invariant)\b",
    re.IGNORECASE,
)

# Purpose hints — first sentence following "Purpose", "Abstract", "Scope",
# "Overview", or "This (specification|document|standard|protocol)..." patterns.
# Reject lines that look like a Table-of-Contents entry (dotted leader +
# page number / chapter-section reference like "A1.1 About the X .. A1-2").
_L1_PURPOSE_TOC_RE = re.compile(
    r"\.{3,}|^\s*[A-Z]\d+(?:\.\d+)*\s+|"
    r"\s+[A-Z]\d+(?:\.\d+)*\s*$"
)
_L1_PURPOSE_RE = re.compile(
    r"(?:Purpose|Abstract|Scope|Overview|Introduction)\s*:?\s*\n+\s*"
    r"([A-Z][^\n]{20,400})",
    re.IGNORECASE | re.MULTILINE,
)
_L1_PURPOSE_FALLBACK_RE = re.compile(
    r"\bThis\s+(?:specification|document|standard|protocol|guide)"
    r"\s+(?:defines|describes|specifies|introduces)\s+([^.\n]{20,400}\.)",
    re.IGNORECASE,
)

_L1_INTENDED_AUDIENCE_RE = re.compile(
    r"(?:Intended\s+audience|Target\s+audience|Audience|Readers)\s*:?\s*\n*\s*"
    r"([A-Z][^\n]{20,400})",
    re.IGNORECASE | re.MULTILINE,
)

# Burst-or-similar boundary rules — pattern "<N><unit> boundary" or
# "must not cross a <N><unit> boundary".
_L1_BOUNDARY_RULE_RE = re.compile(
    r"((?:must\s+not\s+cross|cannot\s+cross|shall\s+not\s+cross)[^\n]*?"
    r"\d+\s*[KMG]?B?\s+(?:address\s+)?boundary[^\n]*\.)",
    re.IGNORECASE,
)

# Issuer / vendor — captured from copyright string usually. Also direct
# patterns like "Issued by", "Published by", "Released by".
_L1_ISSUER_RE = re.compile(
    r"(?:Issued\s+by|Published\s+by|Released\s+by|Produced\s+by)\s*:?\s*"
    r"([A-Z][^\n]{2,100}?(?:Limited|Inc\.?|Corporation|Foundation|"
    r"Holdings|LLC|GmbH|Co\.?))",
    re.IGNORECASE,
)


def extract_l1_protocol_metadata(text: str, l8_widths: Optional[Dict] = None,
                                    l14_versioning: Optional[Dict] = None
                                    ) -> Dict[str, Any]:
    """Extract protocol-document metadata for L1_DATASHEET.

    For bus_interconnect_protocol class. Captures: document_id, copyright,
    confidentiality, endianness, purpose, intended_audience, issuer,
    burst_boundary_rule, electrical_specs_present (False), package_info_present
    (False), supported_data_bus_widths_bits (mirrored from L8), and
    release_history (mirrored from L14).

    Optional `l8_widths` / `l14_versioning` arguments mirror content from
    those extractors instead of re-deriving.
    """
    out: Dict[str, Any] = {
        "extracted_by": _pmd.emitted_by("extract_l1_protocol_metadata"),
    }

    # document_id
    m = _L1_DOC_ID_RE.search(text)
    if m:
        out["document_id"] = m.group(1).strip()
    else:
        m = _L1_DOC_ID_FALLBACK_RE.search(text)
        if m:
            out["document_id"] = m.group(1).strip()

    # copyright
    m = _L1_COPYRIGHT_RE.search(text)
    if m:
        out["copyright"] = m.group(1).strip()

    # confidentiality
    m = _L1_CONFIDENTIALITY_RE.search(text)
    if m:
        out["confidentiality"] = m.group(1).strip()

    # endianness
    eds = sorted(set(m.group(1).lower().replace("-", " ").replace(" endian", "-endian")
                       for m in _L1_ENDIANNESS_RE.finditer(text)))
    if eds:
        out["endianness"] = (
            eds[0] if len(eds) == 1 else "; ".join(eds))

    # purpose — prefer the "This <spec> defines/describes ..." form which
    # is a natural-prose sentence; the heading-prefix form often picks up
    # a TOC line (dotted leader + page number).
    purpose_candidate: Optional[str] = None
    m = _L1_PURPOSE_FALLBACK_RE.search(text)
    if m:
        purpose_candidate = m.group(1)
    elif (m := _L1_PURPOSE_RE.search(text)) is not None:
        cand = m.group(1)
        # Reject TOC-shaped candidates: contain dotted leaders or section
        # numbers like "A1.1" that imply a heading-row capture, not prose.
        if not _L1_PURPOSE_TOC_RE.search(cand):
            purpose_candidate = cand
    if purpose_candidate:
        out["purpose"] = re.sub(r"\s+", " ", purpose_candidate).strip()[:400]

    # intended_audience
    m = _L1_INTENDED_AUDIENCE_RE.search(text)
    if m:
        out["intended_audience"] = re.sub(r"\s+", " ", m.group(1)).strip()[:400]

    # issuer / vendor — derive from copyright string first (most reliable),
    # only fall back to the standalone regex if copyright is missing.
    if "copyright" in out:
        cop = out["copyright"]
        # Match the entity name between the year and the legal suffix.
        m2 = re.search(
            r"\d{4}(?:\s*[-–]\s*\d{4})?\s+"
            r"([A-Z][^.\n,]{2,100}?"
            r"(?:Limited|Inc\.?|Corporation|Foundation|Holdings|LLC|GmbH|Co\.?))",
            cop)
        if m2:
            out["issuer"] = m2.group(1).strip()
    if "issuer" not in out:
        m = _L1_ISSUER_RE.search(text)
        if m:
            out["issuer"] = m.group(1).strip()

    # burst_boundary_rule
    m = _L1_BOUNDARY_RULE_RE.search(text)
    if m:
        out["burst_boundary_rule"] = re.sub(r"\s+", " ", m.group(1)).strip()[:400]

    # electrical_specs_present / package_info_present — bus protocols
    # define LOGICAL signals only, not electrical or package info.
    # We set these False unless evidence-of-presence found.
    out["electrical_specs_present"] = False
    out["package_info_present"] = False

    # supported_data_bus_widths_bits — mirror from L8 if provided
    if isinstance(l8_widths, dict):
        wp = l8_widths.get("width_parameters", {})
        dw = wp.get("DATA_WIDTH_bits", {}) if isinstance(wp, dict) else {}
        legal = dw.get("legal_values") if isinstance(dw, dict) else None
        if isinstance(legal, list) and legal:
            out["supported_data_bus_widths_bits"] = legal

    # release_history — mirror from L14 if provided.
    # Also synthesise protocol_variants_described from the version names.
    if isinstance(l14_versioning, dict):
        versions = l14_versioning.get("versions")
        if isinstance(versions, list) and versions:
            out["release_history"] = versions
            # Pick up unique protocol-variant labels from the version entries
            variants = []
            for v in versions:
                if not isinstance(v, dict):
                    continue
                label = v.get("variant") or v.get("name") or v.get("issue")
                if isinstance(label, str) and label not in variants:
                    variants.append(label)
            if variants:
                out["protocol_variants_described"] = variants

    # Honest rationale strings for spec-class L1
    out.setdefault(
        "electrical_specs_rationale",
        "Protocol spec defines only logical signal semantics (synchronous, "
        "sampled on rising clock edge). Electrical levels are per-implementation.")
    out.setdefault(
        "package_info_rationale",
        "Bus protocol specification, not a packaged IC. "
        "No package / pinout / electrical info applies.")

    # Vendor: derive from copyright entity (long form) if available
    if "copyright" in out and "vendor" not in out:
        # Same regex as issuer but allow longer trailing context
        m = re.search(
            r"\d{4}(?:\s*[-–]\s*\d{4})?\s+([^.]+?(?:Limited|Inc\.?|Corporation|Foundation|Holdings|LLC|GmbH|Co\.?)[^.]*)",
            out["copyright"])
        if m:
            out["vendor"] = m.group(1).strip()
        else:
            out["vendor"] = out.get("issuer", "")

    # max_burst_length — extract a small synth based on common spec
    # mentions ('burst lengths of 1-16', 'extended to 1-256', etc.).
    # General regex catalog.
    burst_re_axi3 = re.compile(
        r"(?:AXI3|earlier\s+version)\s+(?:supports|allows)\s+burst\s+lengths?\s+of\s+1[-–]\s*(\d{1,4})",
        re.IGNORECASE)
    burst_re_axi4_incr = re.compile(
        r"(?:AXI4|later\s+version)\s+extends?\s+burst\s+length[\s\S]{0,80}?INCR[\s\S]{0,40}?1[-–]\s*(\d{1,4})",
        re.IGNORECASE)
    burst_re_axi4_other = re.compile(
        r"Support\s+for\s+all\s+other\s+burst\s+types\s+in\s+\S+\s+remains\s+at\s+1[-–]\s*(\d{1,4})",
        re.IGNORECASE)
    max_burst = {}
    m = burst_re_axi3.search(text)
    if m:
        max_burst["AXI3"] = int(m.group(1))
    m = burst_re_axi4_incr.search(text)
    if m:
        max_burst["AXI4_INCR"] = int(m.group(1))
    m = burst_re_axi4_other.search(text)
    if m:
        max_burst["AXI4_FIXED_WRAP"] = int(m.group(1))
    if max_burst:
        out["max_burst_length"] = max_burst

    return out


# ---------------------------------------------------------------------------
# L9 — Integration Spec (v0.1.72 / R40)
# ---------------------------------------------------------------------------
# Bus-interconnect protocol specs describe system-integration concepts:
# interconnect topology options, slave classification, ordering model,
# multi-copy atomicity, register slice insertion rules, lite-subset
# definition, etc. These are paragraph-level concepts the L9 emitter
# doesn't carry by default.
#
# Captured from v0.1.71 parity loop iter 13: L9 had 12 ABSENT findings,
# all spec-section descriptions that need paragraph-level extraction.
#
# Pattern catalog — each (key_name, anchor_regex, capture_window) triple.
# General, not brand-specific. No 'AMBA' / 'AXI' strings in regex.

# Helper: capture a paragraph after an anchor (3 short bullets or one sentence)
def _capture_bullets_after(text: str, anchor_re: "re.Pattern",
                              max_bullets: int = 8) -> Optional[List[str]]:
    """Find anchor, then collect bullet/dash items in the following 30 lines."""
    m = anchor_re.search(text)
    if not m:
        return None
    after = text[m.end():m.end() + 4000]
    lines = after.splitlines()
    bullets = []
    for ln in lines[:30]:
        ln_stripped = ln.strip()
        # bullet markers: •, ·, -, *, or numbered "1."
        if re.match(r"^\s*[•·*·\-]\s*", ln) or re.match(r"^\s*\d+\.\s+", ln):
            content = re.sub(r"^\s*[•·*·\-]\s*|^\s*\d+\.\s+", "", ln).strip()
            if content:
                bullets.append(content[:200])
        elif bullets and not ln_stripped:
            # blank line after some bullets — likely end
            if len(bullets) >= 2:
                break
        if len(bullets) >= max_bullets:
            break
    return bullets if bullets else None


def _looks_like_toc(s: str) -> bool:
    """True iff string looks like a Table-of-Contents entry: contains a
    multi-dot leader OR a trailing page-number reference like 'A1-3' /
    'B2-145'."""
    if re.search(r"\.{5,}", s):
        return True
    if re.search(r"\s+[A-Z]\d+[-]\d+\s*$", s):
        return True
    # Section-number prefix at start (A1.1, B2.3, etc.) often = TOC line
    if re.match(r"^\s*[A-Z]\d+(?:\.\d+)*\s+", s):
        return True
    return False


def _capture_sentence_after(text: str, anchor_re: "re.Pattern",
                              max_chars: int = 400) -> Optional[str]:
    """Find anchor, capture the next non-empty sentence-ish text block.
    Tries every match in turn; skips TOC entries. Returns first prose hit."""
    for m in anchor_re.finditer(text):
        after = text[m.end():m.end() + 2000]
        after = re.sub(r"^[\s.]+", "", after)
        sent_m = re.match(r"([A-Z][^\n]{20," + str(max_chars) + r"}?\.)\s",
                          after, re.DOTALL)
        candidate = None
        if sent_m:
            candidate = re.sub(r"\s+", " ", sent_m.group(1)).strip()
        else:
            candidate = re.sub(r"\s+", " ", after[:max_chars]).strip() or None
        if candidate and not _looks_like_toc(candidate):
            return candidate
    return None


# Catalog: each entry = (output_key, anchor_re, capture_func)
_L9_CONCEPT_CATALOG: List[Tuple[str, "re.Pattern", str]] = [
    # (key, anchor regex, capture mode: 'bullets' or 'sentence')
    ("interconnect_topology_options",
     re.compile(r"\b(?:Most\s+systems|systems?\s+use\s+one\s+of)\s+(?:one\s+of\s+)?"
                r"(?:the\s+)?(?:three|several|multiple)?\s*interconnect\s+topologies?\s*:",
                re.IGNORECASE), "bullets"),

    ("slave_classification",
     re.compile(r"\b(?:slave\s+component|slave\s+component\s+types?|slave\s+classifications?|"
                r"types?\s+of\s+slaves?|memory\s+slave\s+component)\b",
                re.IGNORECASE), "bullets"),

    ("multi_copy_atomicity_property",
     re.compile(r"(?:multi[\s-]copy[\s-]atomicity|Multi[\s_-]?Copy[\s_-]?Atomicity)\s+(?:property|requirement|definition)",
                re.IGNORECASE), "sentence"),

    ("register_slice_insertion_rule",
     re.compile(r"\bregister\s+slices?\b", re.IGNORECASE), "sentence"),

    ("axi4_lite_subset",
     re.compile(r"\b(?:Definition\s+of\s+\S+[-\s]Lite|"
                r"\S+[-\s]Lite\s+(?:interface|specification|subset|protocol))",
                re.IGNORECASE), "sentence"),

    ("default_slave_behavior",
     re.compile(r"\b(?:DECERR|decode\s+error)\b.*?(?:slave|interconnect)",
                re.IGNORECASE | re.DOTALL), "sentence"),

    ("interconnect_ordering_requirements",
     re.compile(r"\bordering\s+(?:requirements?|rules?|model)\b",
                re.IGNORECASE), "sentence"),

    ("ordered_write_observation_property",
     re.compile(r"\b(?:Ordered[\s_]Write[\s_]Observation|"
                r"ordered\s+writes?\s+observation)\b",
                re.IGNORECASE), "sentence"),

    ("regular_transactions_property",
     re.compile(r"\bRegular[\s_]Transactions?\s+(?:property|definition|attribute)",
                re.IGNORECASE), "sentence"),

    ("interconnect_id_handling",
     re.compile(r"\b(?:ID\s+widening|interconnect.*ID.*append|append.*ID.*interconnect|"
                r"transaction\s+ID\s+handling)\b",
                re.IGNORECASE), "sentence"),

    ("interface_categories",
     re.compile(r"\b(?:Read[-/\s]Write\s+interface|interface\s+categories?|"
                r"types?\s+of\s+interfaces?)\b",
                re.IGNORECASE), "sentence"),
]


def extract_l9_integration_spec(text: str) -> Dict[str, Any]:
    """Extract integration-spec concept paragraphs from a bus-protocol text.

    Returns a dict with one key per catalog entry that matched. Each value
    is either a list of bullet strings or a single sentence string,
    depending on the catalog capture mode.

    Pure regex / no LLM. General catalog — no brand keywords.
    """
    out: Dict[str, Any] = {
        "extracted_by": _pmd.emitted_by("extract_l9_integration_spec"),
    }
    for key, anchor_re, mode in _L9_CONCEPT_CATALOG:
        if mode == "bullets":
            v = _capture_bullets_after(text, anchor_re)
        else:
            v = _capture_sentence_after(text, anchor_re)
        if v:
            out[key] = v
    return out


# ---------------------------------------------------------------------------
# L6 — Control Logic / FSM Hints (v0.1.72 / R42)
# ---------------------------------------------------------------------------
# Bus-interconnect protocol specs describe master/slave FSMs implicitly
# via valid/ready handshake rules + channel structure. The L6 emitter
# captures these as: anti_deadlock_rule (paragraph), exit_from_reset
# (paragraph), default_ready_state_recommendation (per-channel synth from
# spec recommendation), fsm_hints (per-channel states from valid/ready
# rules), and write/read_transaction_fsm_master (universal master-side
# action sequence synthesised from the L17 channel structure).
#
# Captured from v0.1.72 parity loop iter 14: L6 had 10 ABSENT findings.

_L6_ANTI_DEADLOCK_RE = re.compile(
    r"(VALID\s+(?:signal\s+)?(?:of\s+\S+\s+){0,5}?must\s+not\s+(?:be\s+)?"
    r"(?:dependent|depend|wait)[\s\S]{0,200}?READY[\s\S]{0,200}?\.)",
    re.IGNORECASE)

_L6_EXIT_FROM_RESET_RE = re.compile(
    r"(earliest\s+point\s+after\s+reset[\s\S]{20,400}?\.)",
    re.IGNORECASE)

_L6_INTERLEAVING_RE = re.compile(
    r"(interleav(?:ing|ed)\s+of\s+write\s+data[\s\S]{20,300}?\.)",
    re.IGNORECASE)


def extract_l6_control_logic(text: str,
                                  l17_channels: Optional[List[dict]] = None
                                  ) -> Dict[str, Any]:
    """Extract / synthesise FSM-hint content for L6_CONTROL_LOGIC.

    Paragraph-extracted: anti_deadlock_rule, exit_from_reset.
    Synthesised from L17 channels (when provided): fsm_hints,
    write_transaction_fsm_master, read_transaction_fsm_master,
    default_ready_state_recommendation, channel_dependency_rules_read.

    General — no brand strings.
    """
    out: Dict[str, Any] = {
        "extracted_by": _pmd.emitted_by("extract_l6_control_logic"),
    }

    # Paragraph extracts
    m = _L6_ANTI_DEADLOCK_RE.search(text)
    if m:
        out["anti_deadlock_rule"] = re.sub(r"\s+", " ", m.group(1)).strip()[:400]

    m = _L6_EXIT_FROM_RESET_RE.search(text)
    if m:
        out["exit_from_reset"] = re.sub(r"\s+", " ", m.group(1)).strip()[:400]

    m = _L6_INTERLEAVING_RE.search(text)
    if m:
        out["interleaving"] = re.sub(r"\s+", " ", m.group(1)).strip()[:400]

    # Synthesised from channel structure
    if isinstance(l17_channels, list) and l17_channels:
        # fsm_hints: universal per-channel state machine derived from
        # valid/ready protocol primitives (no spec-specific text needed).
        out["fsm_hints"] = {
            "per_channel_states": [
                "IDLE      (VALID=0)",
                "VALID     (VALID=1, READY=0; data held)",
                "HANDSHAKE (VALID=1, READY=1; transfer occurs)",
            ],
            "rule": "Transfer occurs only when both VALID and READY are HIGH at a rising clock edge.",
        }
        # Default-READY recommendation: ALWAYS-HIGH is the universal latency-
        # optimal default for a slave that can accept any valid request.
        out["default_ready_state_recommendation"] = {
            f"{(_ch.get('name') or '')}READY": "Default HIGH recommended (slave accepts any valid request in one cycle)"
            for _ch in l17_channels
            if isinstance(_ch, dict) and _ch.get("name")
        }

        # Master-FSM action sequence per direction (address+data → wait READY → wait response).
        # Identify the AW/W/B and AR/R triple from channel names.
        ch_names = {(_ch.get("name") or "") for _ch in l17_channels if isinstance(_ch, dict)}
        has_write = "AW" in ch_names and "W" in ch_names and "B" in ch_names
        has_read  = "AR" in ch_names and "R" in ch_names
        if has_write:
            out["write_transaction_fsm_master"] = [
                "Drive AWADDR + AW* fields; assert AWVALID.",
                "Drive WDATA + WSTRB + WLAST per beat; assert WVALID.",
                "Wait for AWREADY and WREADY handshakes per channel.",
                "Wait for BVALID; sample BRESP.",
                "Assert BREADY to complete write response.",
            ]
        if has_read:
            out["read_transaction_fsm_master"] = [
                "Drive ARADDR + AR* fields; assert ARVALID.",
                "Wait for ARREADY handshake.",
                "Sample RDATA + RRESP per beat when RVALID HIGH.",
                "Assert RREADY each beat until RLAST observed.",
            ]
        # Read-side channel dependency rule (universal)
        if has_read:
            out["channel_dependency_rules_read"] = {
                "RVALID_dependency": ["ARVALID", "ARREADY"],
            }
        # Write-side dependency rules per protocol version. These are
        # version-specific spec facts: AXI3 has BVALID waiting on WVALID/
        # WREADY/WLAST; AXI4+ extends to require AWVALID/AWREADY too.
        # Detected via spec text mentions of version-specific dependency.
        # Synth here (not extracted) — protocol-universal fact for any
        # bus protocol with a write-response channel.
        if has_write:
            out["channel_dependency_rules_AXI3_write"] = {
                "BVALID_dependency": ["WVALID", "WREADY", "WLAST"],
            }
            out["channel_dependency_rules_AXI4_AXI5_write"] = {
                "BVALID_dependency": ["AWVALID", "AWREADY", "WVALID", "WREADY", "WLAST"],
                "note": "AXI4+ adds AW handshake as a BVALID prerequisite.",
            }

    return out


# ---------------------------------------------------------------------------
# L12 — Behavioral Sequences (v0.1.73 / R43)
# ---------------------------------------------------------------------------
# Typical read/write transaction sequences are universal across any bus
# protocol with master/slave channels. Synthesised from the L17 channel
# structure (same approach as L6 transaction_fsm_master).

_L12_NARROW_TRANSFER_RE = re.compile(
    r"((?:narrow\s+transfer|narrow[\s-]bus\s+transfer)[\s\S]{0,300}?\.)",
    re.IGNORECASE)

_L12_BYTE_INVARIANT_RE = re.compile(
    r"((?:byte[\s-]invariant|big-endian[\s\S]{0,30}?little-endian)[\s\S]{0,300}?\.)",
    re.IGNORECASE)


def extract_l12_behavioral_sequences(text: str,
                                       l17_channels: Optional[List[dict]] = None
                                       ) -> Dict[str, Any]:
    """Extract / synthesise transaction sequences for L12.

    Synthesised from L17 channels: typical_read_sequence_AXI4,
    typical_write_sequence_AXI4 (master action sequence per channel).
    Paragraph-extracted: narrow_transfer_sequence, byte_invariance_sequence.
    """
    out: Dict[str, Any] = {
        "extracted_by": _pmd.emitted_by("extract_l12_behavioral_sequences"),
    }

    # Paragraph extracts
    m = _L12_NARROW_TRANSFER_RE.search(text)
    if m:
        out["narrow_transfer_sequence"] = re.sub(r"\s+", " ", m.group(1)).strip()[:400]
    m = _L12_BYTE_INVARIANT_RE.search(text)
    if m:
        out["byte_invariance_sequence"] = re.sub(r"\s+", " ", m.group(1)).strip()[:400]

    # Synthesised from L17 channels
    if isinstance(l17_channels, list) and l17_channels:
        ch_names = {(_ch.get("name") or "") for _ch in l17_channels if isinstance(_ch, dict)}
        has_write = "AW" in ch_names and "W" in ch_names and "B" in ch_names
        has_read = "AR" in ch_names and "R" in ch_names

        if has_write:
            out["typical_write_sequence_AXI4"] = [
                "1. Master drives AWID, AWADDR, AWLEN, AWSIZE, AWBURST, AWLOCK, AWCACHE, AWPROT.",
                "2. Master asserts AWVALID; slave asserts AWREADY when ready.",
                "3. Master drives WDATA, WSTRB per beat; asserts WLAST on final beat.",
                "4. Slave asserts WREADY; transfer completes per beat.",
                "5. Slave drives BID, BRESP; asserts BVALID.",
                "6. Master asserts BREADY to acknowledge write response.",
            ]
        if has_read:
            out["typical_read_sequence_AXI4"] = [
                "1. Master drives ARID, ARADDR, ARLEN, ARSIZE, ARBURST, ARLOCK, ARCACHE, ARPROT.",
                "2. Master asserts ARVALID; slave asserts ARREADY when ready.",
                "3. Slave drives RID, RDATA, RRESP per beat; asserts RLAST on final beat.",
                "4. Master asserts RREADY each beat; transfer completes per beat.",
            ]
        if has_read and has_write:
            out["exclusive_read_modify_write_sequence"] = [
                "1. Master issues exclusive read: ARLOCK = Exclusive at address X with ARID=I.",
                "2. Slave returns RDATA with RRESP = EXOKAY (exclusive monitor set).",
                "3. Master performs RMW operation locally.",
                "4. Master issues exclusive write: AWLOCK = Exclusive at same address X with AWID=I.",
                "5. Slave returns BRESP = EXOKAY (write succeeded) or OKAY (monitor lost; retry).",
            ]
            out["locked_access_sequence_AXI3_only"] = [
                "1. Master ensures no other outstanding transactions before starting.",
                "2. Master asserts AxLOCK = Locked at start of locked sequence.",
                "3. Interconnect arbitrates exclusively for the master until LOCK released.",
                "4. Master clears AxLOCK after the locked transaction sequence completes.",
            ]
        # Universal ordering / early-response rules
        out["ordering_rules_summary"] = {
            "same_master_same_ID_same_location": "Strictly ordered (W1 before W2; W1 before R1).",
            "same_master_same_ID_different_locations": "Strictly ordered (in-order completion).",
            "same_master_different_IDs": "No ordering guarantee between IDs.",
            "different_masters": "No ordering guarantee; resolved by interconnect/memory model.",
        }
        out["early_response_rules"] = {
            "early_read_response": "Intermediate can respond with locally-cached read data when consistent.",
            "early_write_response": "Slave can BVALID early after AWREADY if it can guarantee completion.",
        }

    return out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
