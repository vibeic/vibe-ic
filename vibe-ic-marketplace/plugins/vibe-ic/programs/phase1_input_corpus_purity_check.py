#!/usr/bin/env python3
"""phase1_input_corpus_purity_check.py — did Phase-1 specify the DESIGN, or the TOOL?

BLOCKING vs ADVISORY (flow-change-acceptance §5)
===============================================
**ADVISORY.** This check REPORTS and CONTINUES; it does not stop the flow, and
it is not wired into the canonical flow's blocking gate list. That is a
deliberate, stated choice, not an unstated default:

  * The DEFECT it names is already PREVENTED at source by
    ``programs/_input_corpus_scope.py``, applied in the Phase-1 raw-corpus
    ingester. On a fixed tree this check has nothing to find.
  * Its job is the residual one — catching corpus contamination arriving by a
    route the scope rule does not cover (a doc tree a user populated by hand, a
    tooling checkout vendored under a shape neither structural marker
    recognises, a re-run over a pre-fix ``phase1/`` directory).

Promoting it to BLOCKING requires the prove-by-run evidence §3 demands — an
actual stopped flow — and that is deliberately NOT claimed here.

WHAT IT MEASURES, AND WHERE
===========================
flow-change-acceptance warns against measuring "presence somewhere" instead of
"presence where it is CONSUMED". The consumer here is ``ic_class_profile``,
which harvests the string leaves of L1 and L2 to decide the design's class —
and that decision selects the RTL generator, so it steers the whole run. So the
check reads the **L-doc provenance actually recorded in L1/L2**, not merely the
list of files on disk.

Two findings, each with its own evidence:

  ``TOOLING_PROVENANCE_IN_L_DOCS``
      An L-doc cites, as evidence for a design fact, a path inside a tooling
      subtree. Reported with the citing layer, the field and the path.
  ``CORPUS_MAJORITY_IS_TOOLING``
      Tooling documents supply a majority of the ingested corpus BYTES. This is
      the shape that flips ``ic_class``: the design's own request is
      out-voted by the tool's manual.

Exit codes
----------
    0 = PASS (no tooling provenance found) or SKIP (nothing to judge)
    2 = CONTAMINATED — findings present. ADVISORY: callers record and continue.
    3 = usage / io error

chip-AGNOSTIC: no design, PDK, vendor, cell or pin literal. Every decision comes
from the project's own filesystem structure and its own generated L-docs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _input_corpus_scope as ics  # noqa: E402

#: Layers whose string leaves the ic_class detector harvests. Contamination
#: here is what actually changes a run's outcome.
_CONSUMED_LAYERS = ("L1_DATASHEET.json", "L2_FRS.json")

_L_DOC_DIRS = ("phase1/generated_docs", "generated_docs")


def _find_l_docs(project: Path) -> Path | None:
    for rel in _L_DOC_DIRS:
        d = project / rel
        if d.is_dir() and any(d.glob("L*.json")):
            return d
    return None


def _walk_strings(node: Any, path: str, out: List[tuple]) -> None:
    """Yield (json_path, string_value) for every string leaf."""
    if isinstance(node, dict):
        for k, v in node.items():
            _walk_strings(v, f"{path}.{k}" if path else str(k), out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk_strings(v, f"{path}[{i}]", out)
    elif isinstance(node, str):
        out.append((path, node))


def check(project: Path) -> Dict[str, Any]:
    project = Path(project)
    roots = ics.find_tooling_roots(project)
    rec: Dict[str, Any] = {
        "_schema_version": "1",
        "check": "phase1_input_corpus_purity_check",
        "enforcement": "ADVISORY",
        "project": project.name,
        "tooling_roots": roots,
        "findings": [],
        "verdict": "PASS",
    }

    if not roots:
        rec["verdict"] = "SKIP"
        rec["reason"] = (
            "no tooling subtree found under the project — the contamination "
            "route this check covers does not exist here")
        return rec

    l_dir = _find_l_docs(project)
    if l_dir is None:
        rec["verdict"] = "SKIP"
        rec["reason"] = "no generated L-docs to judge (Phase-1 has not run)"
        return rec
    rec["l_doc_dir"] = str(l_dir.relative_to(project))

    # (1) tooling provenance cited as evidence inside the CONSUMED layers
    for layer in _CONSUMED_LAYERS:
        p = l_dir / layer
        if not p.is_file():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        leaves: List[tuple] = []
        _walk_strings(doc, "", leaves)
        for jpath, value in leaves:
            if "/" not in value and os.sep not in value:
                continue
            hit = ics.path_is_tooling(value, roots)
            if hit is not None:
                rec["findings"].append({
                    "name": "TOOLING_PROVENANCE_IN_L_DOCS",
                    "layer": layer,
                    "field": jpath,
                    "path": value,
                    "tooling_root": hit["path"],
                    "marker": hit["marker"],
                    "why": ("ic_class_profile harvests this layer's string "
                            "leaves to choose the design class, which selects "
                            "the RTL generator — so tooling text here steers "
                            "the whole run"),
                })

    # (2) corpus majority by BYTES — the shape that out-votes the real request
    ingested = project / "phase1" / "input_doc"
    if ingested.is_dir():
        tool_bytes = real_bytes = 0
        tool_n = real_n = 0
        for f in sorted(ingested.glob("*.txt")):
            try:
                n = f.stat().st_size
            except OSError:
                continue
            # The ingester flattens provenance into the filename with `__`
            # separators; restore it to path form before matching segments.
            probe = f.stem.replace("__", "/")
            if ics.path_is_tooling(probe, roots) is not None:
                tool_bytes += n
                tool_n += 1
            else:
                real_bytes += n
                real_n += 1
        total = tool_bytes + real_bytes
        rec["corpus"] = {
            "tooling_docs": tool_n, "tooling_bytes": tool_bytes,
            "design_docs": real_n, "design_bytes": real_bytes,
            "tooling_pct": round(100.0 * tool_bytes / total, 1) if total else 0.0,
        }
        if total and tool_bytes > real_bytes:
            rec["findings"].append({
                "name": "CORPUS_MAJORITY_IS_TOOLING",
                "tooling_pct": rec["corpus"]["tooling_pct"],
                "why": ("the tool's own documentation supplies more of the "
                        "input corpus than the design's specification does; "
                        "class detection is decided by the majority text"),
            })

    if rec["findings"]:
        rec["verdict"] = "CONTAMINATED"
    return rec


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", default=None, help="write the verdict JSON here")
    args = ap.parse_args(argv)

    if not args.project.is_dir():
        print(f"phase1_input_corpus_purity_check: ERROR: not a directory: "
              f"{args.project}", file=sys.stderr)
        return 3

    rec = check(args.project)

    if args.json:
        try:
            outp = Path(args.json)
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"phase1_input_corpus_purity_check: ERROR: {exc}",
                  file=sys.stderr)
            return 3

    verdict = rec["verdict"]
    n = len(rec["findings"])
    if verdict == "SKIP":
        print(f"phase1_input_corpus_purity_check: [SKIP] {rec['reason']} "
              f"(ADVISORY)")
        return 0
    if verdict == "PASS":
        print(f"phase1_input_corpus_purity_check: PASS "
              f"({len(rec['tooling_roots'])} tooling subtree(s) present, "
              f"0 cited as design evidence) (ADVISORY)")
        return 0

    print(f"phase1_input_corpus_purity_check: CONTAMINATED: {n} finding(s) "
          f"(ADVISORY — recorded, flow continues)")
    for f in rec["findings"][:20]:
        if f["name"] == "CORPUS_MAJORITY_IS_TOOLING":
            print(f"  [{f['name']}] {f['tooling_pct']}% of corpus bytes are "
                  f"tooling documentation")
        else:
            print(f"  [{f['name']}] {f['layer']}:{f['field']} -> {f['path']}")
    if n > 20:
        print(f"  ... and {n - 20} more")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
