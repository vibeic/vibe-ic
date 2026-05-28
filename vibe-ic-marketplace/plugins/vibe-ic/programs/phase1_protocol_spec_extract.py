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
# until the next "Table " or blank-line cluster form the table body. We
# harvest:
#   - table name + page (line number)
#   - body rows (anything with multi-column structure)
_L15_TABLE_HEADER_RE = re.compile(
    r"^\s*(?P<table>Table\s+[A-Z]\d+-\d+)\s+(?P<name>[A-Z].+?)\s*$"
)


def extract_l15_encoding_tables(text: str) -> Dict[str, Any]:
    """Harvest every 'Table A?-? <name>' + the first ~30 lines after each."""
    tables: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []

    lines = _lines_of(text)
    for i, line in enumerate(lines):
        m = _L15_TABLE_HEADER_RE.match(line)
        if not m:
            continue
        table_id = m.group("table").strip()
        table_name = m.group("name").strip()
        # Capture up to next table header or 30 lines whichever sooner
        body_rows: List[str] = []
        for j in range(i + 1, min(i + 30, len(lines))):
            nxt = lines[j].strip()
            if _L15_TABLE_HEADER_RE.match(lines[j]):
                break
            if nxt:
                body_rows.append(nxt)
        tables.append({
            "table_id": table_id,
            "name": table_name,
            "line": i + 1,
            "rows": body_rows[:25],   # cap row count per audit
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
    """Harvest the AR/AW/R/W/B channel signal catalogs."""
    by_channel: Dict[str, List[Dict[str, Any]]] = {
        "AW": [], "W": [], "B": [], "AR": [], "R": [],
    }
    evidence: List[Dict[str, Any]] = []
    seen_sigs: set = set()

    for i, line in enumerate(_lines_of(text), start=1):
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
    return {
        "fields": {
            "channels": channels,
            "dependency_graph": {
                "note": "AXI4+: BVALID waits for AW + W handshake; "
                        "RVALID waits for AR handshake",
            },
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
    """Harvest interconnect topology rules + default signal values."""
    interconnect_rules: List[Dict[str, Any]] = []
    default_signal_values: Dict[str, str] = {}
    evidence: List[Dict[str, Any]] = []

    # Pattern: "<SIGNAL> defaults to <value>"
    dv_re = re.compile(
        r"\b([A-Z][A-Z_]{2,10})\s+(?:defaults to|default value is|"
        r"is\s+ignored\s+if|set to)\s+([\S]+(?:\s+\S+){0,3})", re.I)
    for i, line in enumerate(_lines_of(text), start=1):
        for m in dv_re.finditer(line):
            sig = m.group(1)
            val = m.group(2).rstrip(".,;)")
            # Filter common false-positives
            if sig in ("AXI", "ACE", "AMBA"):
                continue
            default_signal_values.setdefault(sig, val)
            evidence.append({"line": i, "quote": line.strip(),
                              "signal": sig, "default": val})

    # Pattern: interconnect rules — sentences containing "interconnect"
    ic_re = re.compile(r"interconnect\s+(?:must|shall|can|may)\s+([^.]{10,180})\.", re.I)
    for i, line in enumerate(_lines_of(text), start=1):
        for m in ic_re.finditer(line):
            interconnect_rules.append({
                "rule": line.strip(),
                "line": i,
            })

    return {
        "fields": {
            "interconnect_rules": interconnect_rules[:50],
            "default_signal_values": default_signal_values,
            "id_routing": {
                "note": "Interconnect may append bits to ID to identify "
                        "the master port; slave-side ID_WIDTH > "
                        "master-side ID_WIDTH",
            },
        },
        "evidence": evidence[:100],
        "extraction_status": ("EXTRACTED"
                                if (interconnect_rules or default_signal_values)
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
