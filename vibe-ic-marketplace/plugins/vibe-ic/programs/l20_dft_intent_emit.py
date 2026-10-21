#!/usr/bin/env python3
"""Project explicit planned/unmeasured DFT intent into L20.

This producer records planning intent only. It never creates a scan chain,
test port, frequency, ATPG result, or completion claim.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from l_doc_consumer_contract import input_doc_texts, project_relative_source
import l_doc_generator_stamp as _stamp

TOOL = "l20_dft_intent_emit"
_L20 = "L20_DFT_SCAN_TOPOLOGY.json"
_DFT = re.compile(r"\b(?:DFT|design[- ]for[- ]test|scan)\b", re.I)
_PLANNED = re.compile(r"\b(?:planned|deferred|future)\b", re.I)
_UNMEASURED = re.compile(
    r"\b(?:unmeasured|not[_ -]measured|not[_ -]yet[_ -]measured|pending)\b",
    re.I,
)
_EXPLICIT_NONE = re.compile(
    r"\b(?:no\s+(?:DFT|scan)|(?:DFT|scan)\s+(?:is\s+)?not\s+planned)\b",
    re.I,
)
_OBLIGATION = re.compile(
    r"\b(?:preserve|retain|reconcile|must\s+not\s+drop|final\s+producer)\b",
    re.I,
)
_ACCESS = re.compile(r"\b(?:scan|test[- ]access|DFT|pad\s+roster)\b", re.I)


def _records(project: Path) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    intents: List[Dict[str, Any]] = []
    obligations: List[Dict[str, Any]] = []
    for path, text in input_doc_texts(project):
        source, outside = project_relative_source(path, project)
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line:
                continue
            base = {"source": source, "line": lineno, "statement": line[:500]}
            if outside:
                base["source_outside_project"] = True
            if (_DFT.search(line) and _PLANNED.search(line)
                    and _UNMEASURED.search(line)):
                row = dict(base)
                row["negated"] = bool(_EXPLICIT_NONE.search(line))
                intents.append(row)
            if _OBLIGATION.search(line) and _ACCESS.search(line):
                obligations.append(dict(base))
    def dedup(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Phase 1 mirrors input/docs into phase1/input_doc. Prefer the original
        # design-input path and do not publish the same sentence twice merely
        # because both canonical readers opened it.
        ranked = sorted(
            rows,
            key=lambda r: (not str(r["source"]).startswith("input/"),
                           str(r["source"]), int(r["line"])),
        )
        out: List[Dict[str, Any]] = []
        seen = set()
        for row in ranked:
            key = (str(row["statement"]).casefold(), row.get("negated"))
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out

    return dedup(intents), dedup(obligations)


def _is_untouched_skeleton(doc: Dict[str, Any], fields: Dict[str, Any]) -> bool:
    return bool(
        doc.get("extraction_status") == "NOT_YET_EXTRACTED"
        and fields.get("dft_present") is False
        and not fields.get("scan_chains")
        and not fields.get("bist_mbist")
        and fields.get("jtag_tap") is None
    )


def run(project: Path, dry_run: bool = False) -> Dict[str, Any]:
    path = project / "phase1" / "generated_docs" / _L20
    if not path.is_file():
        return {"tool": TOOL, "status": "SKIPPED", "reason": "L20 absent",
                "emitted_count": 0}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"tool": TOOL, "status": "ERROR",
                "reason": f"cannot parse L20: {exc}", "emitted_count": 0}
    if not isinstance(doc, dict):
        return {"tool": TOOL, "status": "ERROR",
                "reason": "L20 is not an object", "emitted_count": 0}
    fields = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
    intents, obligations = _records(project)
    positive = [r for r in intents if not r["negated"]]
    negative = [r for r in intents if r["negated"]]
    if not positive:
        return {"tool": TOOL, "status": "SKIPPED",
                "reason": ("only negated planned-DFT text was found"
                           if negative else "no explicit planned+unmeasured DFT sentence"),
                "emitted_count": 0}
    if negative or not _is_untouched_skeleton(doc, fields):
        return {"tool": TOOL, "status": "REFUSED",
                "reason": ("planned/unmeasured intent conflicts with an explicit "
                           "negation or with non-skeleton L20 content"),
                "emitted_count": 0, "intent_records": intents}

    fields["dft_present"] = None
    fields["dft_intent_status"] = "PLANNED_UNMEASURED"
    fields["planned_obligations"] = obligations
    fields["notes"] = (
        "The design input explicitly keeps DFT planned and unmeasured. No scan "
        "topology, ATPG result, test frequency, or completion is claimed."
    )
    doc["extraction_status"] = "PARTIALLY_EXTRACTED"
    sources = sorted({r["source"] for r in positive + obligations})
    doc["source_documents"] = sources
    doc["extraction_evidence"] = {
        "planned_unmeasured_dft": positive,
        "downstream_obligations": obligations,
    }
    if not dry_run:
        _stamp.dump(path, doc)
    return {"tool": TOOL, "status": "OK", "emitted_count": 1,
            "intent_records": positive, "obligation_count": len(obligations),
            "dry_run": dry_run}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    rep = run(args.project.resolve(), dry_run=args.dry_run)
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).write_text(out + "\n")
    print(out)
    return 1 if rep["status"] in {"ERROR", "REFUSED"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
