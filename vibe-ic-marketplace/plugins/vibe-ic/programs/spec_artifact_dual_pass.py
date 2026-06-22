#!/usr/bin/env python3
"""spec_artifact_dual_pass.py — the DUAL-PASS understanding layer.

DOCTRINE (owner 2026-06-23): interpreting the spec is AI's STRONGEST capability
(and improves with LLM upgrades) — do NOT replace it with a program. Instead make
the understanding layer dual-pass and cross-validated:

    Pass A  PROGRAM  -> json_program  (deterministic BASELINE; always runnable;
                                       zero variance on the structures it covers)
    Pass B  AI       -> json_ai       (the strong interpreter; covers prose / implicit
                                       / cross-referenced structure the parsers miss)
    RECONCILE(A, B)  -> reconciled + disagreements

The PROGRAM output is the BASELINE FLOOR: the result is ALWAYS >= the program
baseline (AI can only ADD breadth; it cannot make us drop what the program caught,
unless it CHALLENGES a specific element with evidence — e.g. a parser bug). The
three disagreement classes drive the compounding loop:

  * program-only  -> AI missed it; baseline keeps it (floor guarantee).
  * ai-only       -> the parser missed this type/format; a NEW-EXTRACTOR candidate
                     to distill into the program layer (so next time it is baseline).
  * conflict      -> AI challenges the baseline; if a real parser bug, fix the parser,
                     else the baseline wins. Either way it is surfaced, not silent.

Output container follows the IC-design-document schema (document_id / document_type
/ structural_elements[] / traceability). Each element:
  {element_type, element_id, title, data, references, metadata{source, ...}}.

`program_baseline()` here runs the LIVE deterministic recognizers via
spec_artifact_registry.detect(); the catalog (spec_artifact_catalog) lists the full
target vocabulary incl. the extractor-exists / to-build types to wire next. The AI
pass is supplied by the caller (the IC Expert Agent) — this module owns the baseline
+ reconcile machinery, not the LLM call.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import spec_artifact_registry as _REG    # noqa: E402
import spec_artifact_catalog as _CAT      # noqa: E402


def _element(etype: str, data, *, eid: Optional[str] = None, title: Optional[str] = None,
             source: str = "program") -> dict:
    cat = _CAT.get(etype)
    return {
        "element_type": etype,
        "element_id": eid or f"{etype}_1",
        "title": title or (cat.title if cat else etype),
        "data": data,
        "references": [],
        "metadata": {"source": source, "tool_generated": source == "program",
                     "l_docs": list(cat.l_docs) if cat else [],
                     "tier": cat.tier if cat else "unknown"},
    }


def _extract_register_map(text: str) -> List[dict]:
    try:
        import regmap_table_extractor as _R
        rows = _R.extract_regmap_table(text, "prompt")
    except Exception:
        rows = []
    return [_element("register_map", {"regs": rows})] if rows else []


def _extract_pinout(text: str) -> List[dict]:
    try:
        import pinout_table_extractor as _P
        rows = _P.extract_pinout(text)
    except Exception:
        rows = []
    return [_element("pinout_table", {"pins": rows})] if rows else []


def _extract_tables(text: str) -> List[dict]:
    """The general table-tier extractor: every pipe table classified to a SPECIFIC
    element_type by its header signature (register/command/encoding/memory/clock/
    power/PVT/test-vector/coverage/...). Generic/unclassified tables are NOT emitted
    here (they are usually the FSM/truth tables the registry already covers, or
    genuinely-unknown tables that belong to the AI pass / convergence signal)."""
    try:
        import structured_table_extractor as _T
        tabs = _T.extract_tables(text)
    except Exception:
        tabs = []
    return [_element(t["element_type"], {"columns": t["columns"], "rows": t["rows"]})
            for t in tabs if t["element_type"] != "structured_table"]


def _extract_parametric(text: str) -> List[dict]:
    """The prose PARAMETRIC tier: arithmetic / memory / counter / shift / boolean /
    sequence / number-format / PDK / timing-constraints / CRC — the key parameters a
    regex can lift with confidence (the AI pass still leads the full understanding)."""
    try:
        import parametric_spec_extractor as _PS
        rows = _PS.extract_all(text)
    except Exception:
        rows = []
    return [_element(d["element_type"], d["data"]) for d in rows]


def _extract_residual(text: str) -> List[dict]:
    """Routing recognizers for the genuinely-prose / vision element types: recognize
    presence + lift partial data, mark lead=ai|vision so the dual-pass AI/vision pass
    completes the extraction. Closes the catalog (every type has a coverage path)."""
    try:
        import residual_recognizer as _RR
        rows = _RR.recognize_all(text)
    except Exception:
        rows = []
    return [_element(d["element_type"], d["data"]) for d in rows]


def _extract_figures(text: str) -> List[dict]:
    """The VISION tier: every figure reference + caption, classified to a vision
    element_type and routed lead=vision for the runtime image model."""
    try:
        import figure_extractor as _F
        rows = _F.extract_figures(text)
    except Exception:
        rows = []
    return [_element(d["element_type"], d["data"]) for d in rows]


# extraction-only baseline contributors (no RTL generator, feed the AI + the gates)
_BASELINE_EXTRACTORS = (_extract_register_map, _extract_pinout, _extract_tables,
                        _extract_parametric, _extract_residual, _extract_figures)


def program_baseline(doc_text: str) -> List[dict]:
    """Deterministic baseline: every LIVE program recognizer that fires + the wired
    extraction-only extractors (register map, pinout, the general table tier). This
    is the floor — guaranteed, zero-variance on what it covers. Deduped by
    element_type (the most-specific source, run first, wins)."""
    els = [_element(a["type"], a["structured"], source="program")
           for a in _REG.detect(doc_text)]
    for ex in _BASELINE_EXTRACTORS:
        els += ex(doc_text)
    seen, out = set(), []
    for e in els:
        if e["element_type"] in seen:
            continue
        seen.add(e["element_type"])
        out.append(e)
    return out


def _key(el: dict):
    # match identity: element_type (+ element_id when the AI distinguishes instances)
    return (el["element_type"], el.get("element_id", f"{el['element_type']}_1"))


def _data_equiv(x, y) -> bool:
    """Structural equivalence of two `data` payloads (the cross-check). Coarse but
    deterministic; a semantic-equivalence AI-judge can be layered on top later."""
    import json
    def norm(v):
        return json.dumps(v, sort_keys=True, default=str)
    return norm(x) == norm(y)


def reconcile(baseline: List[dict], ai: List[dict]) -> Dict:
    """Classify every element into agree / program_only / ai_only / conflict and
    compute the agreement rate. ai_only entries are tagged as new-extractor
    candidates (the compounding-loop work queue)."""
    b = {_key(e): e for e in baseline}
    a = {_key(e): e for e in ai}
    agree, conflict, program_only, ai_only = [], [], [], []
    for k in sorted(set(b) | set(a)):
        if k in b and k in a:
            if _data_equiv(b[k]["data"], a[k]["data"]):
                agree.append(k[0])
            else:
                conflict.append({"element_type": k[0], "element_id": k[1],
                                 "baseline": b[k]["data"], "ai": a[k]["data"],
                                 "resolution": "baseline_wins_unless_ai_challenges_with_evidence"})
        elif k in b:
            program_only.append(k[0])                     # AI missed -> floor keeps it
        else:
            cat = _CAT.get(k[0])
            ai_only.append({"element_type": k[0], "element_id": k[1],
                            "new_extractor_candidate": (cat.program is None) if cat else True,
                            "tier": cat.tier if cat else "unknown"})
    total = len(set(b) | set(a)) or 1
    return {
        "agreement_rate": round(len(agree) / total, 3),
        "agree": agree,
        "program_only_floor_kept": program_only,
        "ai_only_new_extractor_candidates": ai_only,
        "conflicts": conflict,
    }


def extract_dual_pass(doc_text: str, ai_elements: Optional[List[dict]] = None, *,
                      document_id: str = "doc", document_type: str = "Functional_Specification") -> Dict:
    """Run the dual pass. If ai_elements is None, return the baseline-only container
    (the caller's IC Expert Agent then supplies its AI extraction to reconcile)."""
    base = program_baseline(doc_text)
    container = {
        "document_id": document_id,
        "document_type": document_type,
        "structural_elements": base,
        "traceability": {"upstream_references": [], "downstream_references": []},
    }
    if ai_elements is None:
        return {"container": container, "baseline_only": True,
                "note": "supply the AI extraction pass (list of elements) to reconcile"}
    rep = reconcile(base, ai_elements)
    # merged = union; baseline kept on conflict (AI must challenge with evidence to override)
    merged = {_key(e): e for e in base}
    for e in ai_elements:
        if _key(e) not in merged:
            e = dict(e)
            e.setdefault("metadata", {})["source"] = "ai"
            merged[_key(e)] = e
    container["structural_elements"] = list(merged.values())
    return {"container": container, **rep}


def log_disagreements(report: Dict, backlog_path: str, doc_id: str = "doc") -> int:
    """STEP-1 convergence hook: append this run's ai_only finds (program missed it)
    + conflicts to a JSONL backlog. Across many runs this becomes the DATA-DRIVEN
    new-extractor queue — build the type the program misses MOST, not by guessing.
    Returns the number of lines appended."""
    import json
    rows = []
    for c in report.get("ai_only_new_extractor_candidates", []):
        rows.append({"doc": doc_id, "kind": "ai_only", **c})
    for c in report.get("conflicts", []):
        rows.append({"doc": doc_id, "kind": "conflict", "element_type": c["element_type"]})
    if rows:
        with open(backlog_path, "a") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def convergence_summary(reports: List[Dict]) -> Dict:
    """Given many reconcile reports, measure convergence of the DETERMINISTIC layer:
    the mean agreement rate, and the ranked count of ai_only element types (the
    program's blind spots). The deterministic layer has CONVERGED for a type when it
    no longer appears as ai_only (the program baseline now covers it). What remains
    ai_only at the end is the genuine AI/vision residual."""
    from collections import Counter
    miss = Counter()
    rates = []
    for rep in reports:
        rates.append(rep.get("agreement_rate", 0.0))
        for c in rep.get("ai_only_new_extractor_candidates", []):
            miss[c["element_type"]] += 1
    return {
        "runs": len(reports),
        "mean_agreement_rate": round(sum(rates) / len(rates), 3) if rates else 0.0,
        "program_blind_spots_ranked": miss.most_common(),
        "converged": not miss,                 # no program-missed types left
    }


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--doc", required=True, help="extracted document / prompt text")
    ap.add_argument("--ai", default=None, help="optional AI-pass elements JSON file")
    ap.add_argument("--document-type", default="Functional_Specification")
    a = ap.parse_args(argv)
    text = Path(a.doc).read_text(errors="replace")
    ai = json.loads(Path(a.ai).read_text()) if a.ai else None
    print(json.dumps(extract_dual_pass(text, ai, document_type=a.document_type), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
