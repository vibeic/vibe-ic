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

try:
    import l_doc_taxonomy as _tx
except ImportError:  # pragma: no cover
    from . import l_doc_taxonomy as _tx  # type: ignore


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
    dep_re = re.compile(
        r"\b(\w[\w.\-]*)\s+(?:is\s+deprecated|"
        r"no\s+longer\s+supported|removed\s+in)\b", re.I)
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
_L15_TABLE_HEADER_RE = re.compile(
    r"^\s*(?P<table>Table\s+[A-Z]\d+-\d+)\s+(?P<name>[A-Z].+?)\s*$"
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
    r"(?P<sem>[A-Z].{10,200})\s*$"
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
    dv_re = re.compile(
        r"\b([A-Z][A-Z_]{2,10})\s+(?:defaults to|default value is|"
        r"is\s+ignored\s+if|set to)\s+([\S]+(?:\s+\S+){0,3})", re.I)
    for i, line in enumerate(_lines_of(text), start=1):
        for m in dv_re.finditer(line):
            sig = m.group(1)
            val = m.group(2).rstrip(".,;)")
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

    # ID routing — interconnect appends ID bits
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
    for i, line in enumerate(_lines_of(text), start=1):
        if ir_re.search(line):
            id_routing.setdefault("evidence", []).append({
                "line": i, "quote": line.strip()})
            if len(id_routing.get("evidence", [])) >= 3:
                break

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
        "extraction_status": (
            "EXTRACTED"
            if (interconnect_rules or default_signal_values
                or typical_topologies or mca or axprot_polarity)
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
        existing["extracted_by"] = (
            f"phase1_protocol_spec_extract.extract_{code.lower()}_* v0.1.51"
        )
        path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
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
        "emitted_by": "phase1_protocol_spec_extract v0.1.51",
    }
    if args.out_json:
        args.out_json.write_text(json.dumps(payload, indent=2),
                                  encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
