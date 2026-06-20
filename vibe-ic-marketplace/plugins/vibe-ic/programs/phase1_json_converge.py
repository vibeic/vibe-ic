#!/usr/bin/env python3
"""phase1_json_converge.py — deterministic comparator for the Phase-1
DIALOGUE dual-track convergence (program-first + AI-backup, ORGANIC #716).

A dialogue (treated as a freestyle document) is ingested by TWO independent
tracks that produce L1-L24 JSON:

  - PROGRAM track : the deterministic DOC->JSON doc-extraction runner.
  - AI track      : the IC-Expert Agent reads the same dialogue and emits
                    L1-L24 JSON itself.

This program is the DETERMINISTIC half of the convergence step: it diffs the
two layer-JSON sets fact-by-fact and reports, per layer:

  - agree         : same leaf path present in both with an equal value
  - disagree      : same leaf path, DIFFERENT value  (IC-Expert must resolve)
  - program_only  : leaf the AI track missed         (coverage gap, AI side)
  - ai_only       : leaf the program track missed     (coverage gap, prog side)

plus a `merged_candidate` (union; every disagreement carried as a
`{"_conflict": {"program": ..., "ai": ...}}` marker for the IC-Expert Agent to
root-cause and resolve). The agent NEVER accepts a lone track — agreement is
auto-accepted; every disagreement / one-sided fact is surfaced for judgment.

chip-AGNOSTIC: structural flatten + value normalization only.

Usage:
    phase1_json_converge.py --program <dir|file> --ai <dir|file> [--json OUT]
    # exit 0 always; verdict ('converged'|'needs_resolution') in the report
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# keys that identify a record inside a list (so port/register/param lists
# compare order-independently by identity, not by array index)
_ID_KEYS = ("name", "signal", "port", "field", "register", "reg",
            "parameter", "param", "state", "opcode", "key", "id")


# Address/offset keys ALSO discriminate a record (two `STATUS` registers at
# different offsets are different records). Combined with _ID_KEYS so a record
# identity is a COMPOSITE of every present discriminator, not just the first.
_ADDR_KEYS = ("addr", "address", "offset", "index", "idx", "bit", "position")


def _id_of(rec: Dict[str, Any]) -> Optional[str]:
    """A COMPOSITE identity over every present, NON-EMPTY id/discriminator key —
    not just the first id key. Keying on only the first key (Step-2.7 §4.05)
    collapsed records distinguished by a later key (two ports with an empty
    `name` but distinct `signal`; two `STATUS` regs at different `addr`) into one
    identity, so _flatten last-wins silently DROPPED a record and manufactured a
    phantom conflict. A blank value cannot discriminate, so it is skipped."""
    parts = []
    for k in _ID_KEYS + _ADDR_KEYS:
        if k in rec and isinstance(rec[k], (str, int)):
            val = str(rec[k]).strip()
            if val:
                parts.append(f"{k}={val}")
    return ";".join(parts) if parts else None


def _flatten(node: Any, prefix: str, out: Dict[str, Any]) -> None:
    if isinstance(node, dict):
        if not node:
            # an EMPTY object is an affirmative fact ("present but empty") — emit
            # a leaf so a present-empty vs present-populated cross-track diff
            # surfaces as a disagreement instead of vanishing (Step-2.7 §4.05).
            out[prefix] = "<empty-object>"
            return
        for k, v in node.items():
            _flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(node, list):
        if not node:
            out[prefix] = "<empty-list>"   # affirmative "none" — see above
            return
        # record-list with UNIQUE identity keys -> index by identity; else by pos
        ids = [(_id_of(x) if isinstance(x, dict) else None) for x in node]
        if node and all(i is not None for i in ids) and len(set(ids)) == len(ids):
            for ident, item in zip(ids, node):
                _flatten(item, f"{prefix}[{ident}]", out)
        else:
            for i, item in enumerate(node):
                _flatten(item, f"{prefix}[{i}]", out)
    else:
        out[prefix] = node


# A CANONICAL plain decimal/integer: optional sign, no leading zeros (except a
# lone 0), no exponent, no underscores. Only these are safe to numeric-FOLD for
# equality; a leading-zero string (`010`), an exponent (`1e3`), or a grouped
# (`1_000`) value carries an author-visible distinction that must NOT be erased
# (Step-2.7 §4.05 — folding it would silently auto-accept a different value).
_CANON_NUM_RE = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")


def _norm(v: Any) -> str:
    """Normalize a leaf value for equality: case-folded + numeric-aware, but the
    numeric fold is restricted to CANONICAL decimals so author-visible forms
    (`010`, `1e3`, `1_000`) stay distinct and surface as disagreements."""
    s = str(v).strip()
    if _CANON_NUM_RE.match(s):
        try:
            f = float(s)
            return str(int(f)) if f == int(f) else str(f)
        except (ValueError, OverflowError):
            pass
    return s.lower()


def _load_layer_json(path: Path) -> Dict[str, Dict[str, Any]]:
    """Return {layer_code: {leaf_path: value}} from a dir of L*.json or a
    single L*.json / structured JSON file."""
    layers: Dict[str, Dict[str, Any]] = {}
    files: List[Path]
    if path.is_dir():
        files = sorted(path.glob("L*.json"))
    elif path.is_file():
        files = [path]
    else:
        return layers
    for f in files:
        code = f.stem.split("_")[0] if f.is_file() else f.stem
        # layer code is the leading "L<NN>" of the filename stem
        stem = f.stem
        code = stem
        for i in range(len(stem), 0, -1):
            head = stem[:i]
            if head and head[0] == "L" and head[1:].rstrip("R").isdigit():
                code = head
                break
        try:
            data = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        flat: Dict[str, Any] = {}
        _flatten(data, "", flat)
        layers.setdefault(code, {}).update(flat)
    return layers


def converge(program: Path, ai: Path) -> Dict[str, Any]:
    prog = _load_layer_json(program)
    aijson = _load_layer_json(ai)
    all_codes = sorted(set(prog) | set(aijson),
                       key=lambda c: (int(''.join(ch for ch in c
                                      if ch.isdigit()) or 0), c))
    per_layer: Dict[str, Any] = {}
    merged: Dict[str, Dict[str, Any]] = {}
    tot = {"agree": 0, "disagree": 0, "program_only": 0, "ai_only": 0}
    for code in all_codes:
        p = prog.get(code, {})
        a = aijson.get(code, {})
        keys = set(p) | set(a)
        agree, disagree, p_only, a_only = 0, [], [], []
        mlayer: Dict[str, Any] = {}
        for k in sorted(keys):
            in_p, in_a = k in p, k in a
            if in_p and in_a:
                if _norm(p[k]) == _norm(a[k]):
                    agree += 1
                    mlayer[k] = p[k]
                else:
                    disagree.append({"path": k, "program": p[k],
                                     "ai": a[k]})
                    mlayer[k] = {"_conflict": {"program": p[k],
                                               "ai": a[k]}}
            elif in_p:
                p_only.append({"path": k, "value": p[k]})
                mlayer[k] = p[k]
            else:
                a_only.append({"path": k, "value": a[k]})
                mlayer[k] = a[k]
        per_layer[code] = {
            "agree": agree, "disagree": disagree,
            "program_only": p_only, "ai_only": a_only,
        }
        tot["agree"] += agree
        tot["disagree"] += len(disagree)
        tot["program_only"] += len(p_only)
        tot["ai_only"] += len(a_only)
        if mlayer:
            merged[code] = mlayer
    verdict = "converged" if tot["disagree"] == 0 else "needs_resolution"
    return {
        "verdict": verdict,
        "totals": tot,
        "layers": per_layer,
        "merged_candidate": merged,
    }


def _fmt(rep: Dict[str, Any]) -> str:
    t = rep["totals"]
    lines = [f"convergence verdict: {rep['verdict']}",
             f"  agree={t['agree']} disagree={t['disagree']} "
             f"program_only={t['program_only']} ai_only={t['ai_only']}"]
    for code, L in rep["layers"].items():
        if L["disagree"] or L["program_only"] or L["ai_only"]:
            lines.append(
                f"  {code}: agree={L['agree']} "
                f"disagree={len(L['disagree'])} "
                f"prog_only={len(L['program_only'])} "
                f"ai_only={len(L['ai_only'])}")
        for d in L["disagree"]:
            lines.append(f"    ! {code}.{d['path']}: "
                         f"program={d['program']!r} ai={d['ai']!r}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--program", type=Path, required=True,
                    help="program-track L*.json dir or file")
    ap.add_argument("--ai", type=Path, required=True,
                    help="AI-track (IC-Expert) L*.json dir or file")
    ap.add_argument("--json", type=Path, default=None,
                    help="write the full convergence report here")
    args = ap.parse_args(argv)
    rep = converge(args.program, args.ai)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    print(_fmt(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
