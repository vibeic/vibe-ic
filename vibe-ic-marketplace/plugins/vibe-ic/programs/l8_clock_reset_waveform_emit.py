#!/usr/bin/env python3
"""Project typed clock/reset facts into L8's release-document consumer field.

VERDICT SEMANTICS: **REPAIRS** (exit 0 unless an input layer is unreadable).

The Phase-1 runner already emits typed clock records into
``L8_TIMING_WAVEFORM.clocks[]`` / ``clock_domains[]`` and typed reset records
into ``L9_INTEGRATION_SPEC.resets[]`` / ``reset_domains[]``.  Release-document
producers, however, consume the L8 scalar ``clock_and_reset_waveform``.  Before
this adapter a design could therefore carry both typed facts while its release
guide stated ``Clock and reset | NOT_MEASURED``.

This module is a projection, not a second extractor:

* it reads only those two generated input layers;
* it copies stated fields and never supplies a default polarity, edge, period,
  frequency, or synchrony;
* it emits only when at least one clock AND one reset are present;
* it yields to an existing non-empty ``clock_and_reset_waveform`` (protocol
  overlays may carry a more specific waveform);
* it records both layer paths in the projected value, making the join auditable
  from the consuming layer itself.

The runner calls it after protocol overlays have settled and before the final
clock-contract gate.  Missing facts are a named ``SKIPPED`` outcome, never an
empty structure that release documents could misread as measured.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import l_doc_generator_stamp as _stamp  # noqa: E402

#: The L8 key this emitter writes. `l8_timing_schema` reads it from here, so
#: the timing gate's non-protocol allowlist is the emitter's own spelling.
L8_KEY = "clock_and_reset_waveform"
import _atomic_artefact as _aa  # noqa: E402
from _prose_polarity import is_denied, sentence_scope  # noqa: E402

TOOL = "l8_clock_reset_waveform_emit"
L8_REL = "phase1/generated_docs/L8_TIMING_WAVEFORM.json"
L9_REL = "phase1/generated_docs/L9_INTEGRATION_SPEC.json"


def _load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _scopes(doc: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    yield doc
    fields = doc.get("fields")
    if isinstance(fields, dict):
        yield fields


def _records(doc: Dict[str, Any], *keys: str) -> List[Dict[str, Any]]:
    for key in keys:
        for scope in _scopes(doc):
            value = scope.get(key)
            if isinstance(value, list):
                records = [dict(row) for row in value
                           if isinstance(row, dict)]
                if records:
                    return records
    return []


def _nonempty(value: Any) -> bool:
    if isinstance(value, str) and value.strip().lower() in {
            "unknown", "unspecified", "not_measured"}:
        return False
    return value is not None and value != "" and value != [] and value != {}


def _copy_stated(row: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    return {key: row[key] for key in keys if key in row and _nonempty(row[key])}


def _port_descriptions(l9: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in _records(l9, "ports"):
        name, description = row.get("name"), row.get("description")
        if isinstance(name, str) and isinstance(description, str) \
                and description.strip():
            out[name] = description.strip()
    return out


def _clock_edges(l9: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in _records(l9, "clocks", "clock_domains"):
        name, edge = row.get("name"), row.get("edge")
        if isinstance(name, str) and isinstance(edge, str) and edge.strip():
            out[name] = edge.strip()
    return out


def _described_clock_edges(l9: Dict[str, Any]) -> Dict[str, str]:
    """Return only unambiguous, affirmative clock edges from L9 port text."""
    candidates: Dict[str, set[str]] = {}
    for scope in _scopes(l9):
        for key in ("ports", "top_ports", "top_module_pins"):
            rows = scope.get(key, [])
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                name, text = row.get("name"), row.get("description")
                if not isinstance(name, str) or not isinstance(text, str):
                    continue
                low = text.lower()
                tokens = list(re.finditer(r"\b(rising|positive|posedge|falling|negative|negedge)\s+edge\b", low))
                denied = any(is_denied(text[sentence_scope(text, m.start(), m.end())[0]:sentence_scope(text, m.start(), m.end())[1]]) for m in tokens)
                rise = bool(re.search(r"\b(rising|positive|posedge)\s+edge\b", low) or "上升沿" in text)
                fall = bool(re.search(r"\b(falling|negative|negedge)\s+edge\b", low) or "下降沿" in text)
                negated = bool(denied or "非上升沿" in text or "非下降沿" in text)
                if not negated and rise != fall:
                    candidates.setdefault(name, set()).add("posedge" if rise else "negedge")
    return {name: next(iter(edges)) for name, edges in candidates.items()
            if len(edges) == 1}


def _refresh_existing_edges(existing: Dict[str, Any], l9: Dict[str, Any]) -> bool:
    """Fill only absent retained clock edges from unambiguous L9 authority."""
    edges = _clock_edges(l9)
    edge_provenance = {row.get("name"): row.get("semantic_provenance")
                       for row in _records(l9, "clocks", "clock_domains")}
    for name, edge in _described_clock_edges(l9).items():
        edges.setdefault(name, edge)
    changed = False
    clocks = existing.get("clocks")
    if not isinstance(clocks, list):
        return False
    for row in clocks:
        if not isinstance(row, dict) or _nonempty(row.get("edge")):
            continue
        edge = edges.get(row.get("name"))
        if edge:
            row["edge"] = edge
            row["edge_derived_from"] = L9_REL
            if edge_provenance.get(row.get("name")):
                row["semantic_provenance"] = edge_provenance[row["name"]]
            changed = True
    return changed


def _project(l8: Dict[str, Any], l9: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the typed join, or ``None`` when either side is absent."""
    clocks = _records(l8, "clocks", "clock_domains")
    resets = _records(l9, "reset_domains", "resets")
    if not clocks or not resets:
        return None

    edges = _clock_edges(l9)
    edge_provenance = {row.get("name"): row.get("semantic_provenance")
                       for row in _records(l9, "clocks", "clock_domains")}
    for name, edge in _described_clock_edges(l9).items():
        if name not in edges:
            edges[name] = edge
    descriptions = _port_descriptions(l9)
    clock_rows: List[Dict[str, Any]] = []
    for row in clocks:
        rec = _copy_stated(row, (
            "name", "edge", "period_ns", "freq_mhz", "pdk_scoped_target",
            "reset_strategy", "reset_bindings",
            "semantic_provenance",
        ))
        name = rec.get("name")
        if "edge" not in rec and isinstance(name, str) and name in edges:
            rec["edge"] = edges[name]
            rec["edge_derived_from"] = L9_REL
            if edge_provenance.get(name):
                rec["semantic_provenance"] = edge_provenance[name]
        if rec:
            clock_rows.append(rec)

    reset_rows: List[Dict[str, Any]] = []
    for row in resets:
        rec = _copy_stated(row, (
            "name", "polarity", "sync", "synchrony", "edge", "domain_bindings",
            "semantic_provenance",
        ))
        name = rec.get("name")
        if isinstance(name, str) and name in descriptions:
            rec["port_description"] = descriptions[name]
        if rec:
            reset_rows.append(rec)

    if not clock_rows or not reset_rows:
        return None
    return {
        "clocks": clock_rows,
        "resets": reset_rows,
        "derived_from": [L8_REL, L9_REL],
        "extraction_strategy": TOOL,
    }


def run(project: Path) -> Dict[str, Any]:
    l8_path, l9_path = project / L8_REL, project / L9_REL
    absent = [rel for rel, path in ((L8_REL, l8_path), (L9_REL, l9_path))
              if not path.is_file()]
    if absent:
        return {"tool": TOOL, "status": "SKIPPED",
                "reason": f"required layer absent: {', '.join(absent)}",
                "emitted_count": 0}
    l8, l9 = _load(l8_path), _load(l9_path)
    if l8 is None or l9 is None:
        bad = L8_REL if l8 is None else L9_REL
        return {"tool": TOOL, "status": "ERROR",
                "reason": f"{bad} unreadable or not an object",
                "emitted_count": 0}

    for scope in _scopes(l8):
        existing = scope.get(L8_KEY)
        if _nonempty(existing):
            if isinstance(existing, dict) and _refresh_existing_edges(existing, l9):
                _stamp.dump(l8_path, l8)
                return {"tool": TOOL, "status": "OK", "emitted_count": 1,
                        "reason": "existing waveform refreshed from L9 authority"}
            return {"tool": TOOL, "status": "OK", "emitted_count": 0,
                    "reason": "existing clock_and_reset_waveform preserved"}

    value = _project(l8, l9)
    if value is None:
        return {"tool": TOOL, "status": "SKIPPED",
                "reason": "typed clock and reset records are not both present",
                "emitted_count": 0}

    l8[L8_KEY] = value
    sources = l8.get("source_documents")
    sources = list(sources) if isinstance(sources, list) else []
    if L9_REL not in sources:
        sources.append(L9_REL)
    l8["source_documents"] = sources
    _stamp.dump(l8_path, l8)
    return {"tool": TOOL, "status": "OK", "emitted_count": 1,
            "doc_written": str(l8_path)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog=TOOL)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 2
    report = run(args.project_dir.resolve())
    if args.json:
        _aa.write_json(args.json, report)
    print(f"{TOOL}: {report['status']} — "
          f"{report.get('reason') or report.get('emitted_count')}")
    return 1 if report["status"] == "ERROR" else 0


if __name__ == "__main__":
    sys.exit(main())
