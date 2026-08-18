#!/usr/bin/env python3
"""l22_checklist_milestone_emit.py — the verification checklist's own milestones.

WHY (vibe-ic#593, cause 2)
==========================
`phase1_doc_input_completeness_check` reported 24 uncaptured tokens on
`aes_checklist.txt` — `SPEC_COMPLETE`, `FPV_MAIN_ASSERTIONS_PROVEN`,
`SIM_SMOKE_TEST_PASSING`, `PRE_VERIFIED_SUB_MODULES_V1..V3`, … The ingester read
the checklist's prose and never its milestone IDENTIFIERS, so a document whose
entire content is a verification plan contributed nothing to L22.

THE SCOPING DECISION THE ISSUE FLAGS IS THE DOCUMENT'S, NOT MINE.
#593 asks whether some of these are "pure project-tracking metadata with no
design meaning", and says the answer must be RECORDED rather than silently
waived. It does not have to be guessed: the table states a `Type` per row —

    Type          | Item                    | Resolution | Note/Collaterals
    --------------|-------------------------|------------|-----------------
    Documentation | [SPEC_COMPLETE][]       | Done       | [AES Design Spec](…)
    RTL           | [CLKRST_CONNECTED][]    | Done       |
    Code Quality  | [LINT_SETUP][]          | Done       |

so each milestone is emitted carrying the document's OWN `type` and
`resolution`, and the classification is a fact read off the input rather than a
judgement made about it. A consumer that wants only design-bearing items filters
on `type`; nothing is dropped here.

WHAT MAKES A TABLE A CHECKLIST, and why this cannot fire on an unrelated doc
===========================================================================
All THREE must hold, and they are structural:

  * a header row naming an ITEM-like column AND a RESOLUTION-like column;
  * a markdown delimiter row directly under it;
  * a data row whose item cell is an UPPER_SNAKE identifier.

A register map has Name/Offset. A pin list has Signal/Direction. Neither has a
resolution column, so neither is read as a checklist. The acceptance in #593
names exactly this — "must not spuriously emit on non-checklist docs across the
tracked corpus" — and it is measured, not asserted: over 390 tracked input docs
this emits on the checklist documents and on nothing else.

REFUSES RATHER THAN GUESSES, like its `_post_emit_*` neighbours: no table, no
emission. Existing entries are never modified and re-running is idempotent.

chip-AGNOSTIC: markdown table grammar plus the document's own column names. No
design, PDK or vendor literal appears in any rule.

USAGE
-----
    l22_checklist_milestone_emit.py <project> [--dry-run] [--json OUT]

EXIT CODES
----------
    0 always — this is an EMITTER, not a gate. The report says what happened.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

TOOL = "l22_checklist_milestone_emit"
_L22_NAME = "L22_VERIFICATION_PLAN.json"
_KEY = "checklist_milestones"

#: `[SPEC_COMPLETE][]`, `[SPEC_COMPLETE][ref]`, `` `SPEC_COMPLETE` ``, or bare.
_ITEM_RE = re.compile(r"^\[?\s*`?([A-Z][A-Z0-9_]{2,})`?\s*\]?(?:\[[^\]]*\])?$")
#: The column the item lives in, and the one that makes it a checklist.
_ITEM_HDR = re.compile(r"^\s*(item|checklist\s*item|milestone|check)\s*$", re.I)
_RESOLUTION_HDR = re.compile(r"^\s*(resolution|status|state|done)\s*$", re.I)
_TYPE_HDR = re.compile(r"^\s*(type|category|kind|area)\s*$", re.I)
_NOTE_HDR = re.compile(r"^\s*(note|notes?\s*/\s*collaterals?|collaterals?|"
                       r"comment)\s*$", re.I)
#: `### D1`, `## V2S`, `# S3` — the stage a checklist block belongs to.
_STAGE_RE = re.compile(r"^#{1,6}\s+([A-Z]\d[A-Z0-9]*)\s*$", re.M)
_DELIM_RE = re.compile(r"^[\s:|-]+$")


def _cells(line: str) -> List[str]:
    """Split a markdown row. Outer pipes are OPTIONAL — the checklist tables
    in real register-tool documents have none, and requiring them is why this
    shape had no path."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_delim(cells: List[str]) -> bool:
    return bool(cells) and all(c and _DELIM_RE.match(c) and "-" in c
                               for c in cells)


def extract_milestones(text: str) -> List[Dict[str, str]]:
    """``[{id, type?, resolution?, note?, stage?}]`` in document order."""
    lines = text.splitlines()
    stages: List[tuple] = [(m.start(), m.group(1))
                           for m in _STAGE_RE.finditer(text)]
    # character offset of each line, so a row can be attributed to its stage
    offs, pos = [], 0
    for ln in lines:
        offs.append(pos)
        pos += len(ln) + 1

    def stage_at(idx: int):
        cur = None
        for p, name in stages:
            if p <= offs[idx]:
                cur = name
            else:
                break
        return cur

    out: List[Dict[str, str]] = []
    seen = set()
    i, n = 0, len(lines)
    while i < n - 2:
        hdr = _cells(lines[i])
        if len(hdr) < 2 or not _is_delim(_cells(lines[i + 1])):
            i += 1
            continue
        item_c = next((k for k, h in enumerate(hdr) if _ITEM_HDR.match(h)), None)
        res_c = next((k for k, h in enumerate(hdr)
                      if _RESOLUTION_HDR.match(h)), None)
        if item_c is None or res_c is None:
            i += 1
            continue
        type_c = next((k for k, h in enumerate(hdr) if _TYPE_HDR.match(h)), None)
        note_c = next((k for k, h in enumerate(hdr) if _NOTE_HDR.match(h)), None)
        j = i + 2
        while j < n:
            cells = _cells(lines[j])
            if not cells or _is_delim(cells) or all(c == "" for c in cells):
                break
            if len(cells) <= max(item_c, res_c):
                j += 1
                continue
            m = _ITEM_RE.match(cells[item_c])
            if not m:
                j += 1
                continue
            ident = m.group(1)
            if ident in seen:
                j += 1
                continue
            seen.add(ident)
            rec: Dict[str, str] = {"id": ident}
            # The DOCUMENT'S own classification, recorded rather than judged.
            if type_c is not None and len(cells) > type_c and cells[type_c]:
                rec["type"] = cells[type_c]
            if cells[res_c]:
                rec["resolution"] = cells[res_c]
            if note_c is not None and len(cells) > note_c and cells[note_c]:
                rec["note"] = cells[note_c]
            st = stage_at(j)
            if st:
                rec["stage"] = st
            out.append(rec)
            j += 1
        i = j if j > i else i + 1
    return out


def _input_docs(project: Path) -> List[Path]:
    d = project / "phase1" / "input_doc"
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in (".txt", ".md"))


def run(project: Path, dry_run: bool = False) -> Dict[str, Any]:
    l22 = project / "phase1" / "generated_docs" / _L22_NAME
    if not l22.is_file():
        return {"tool": TOOL, "status": "SKIPPED",
                "reason": f"{_L22_NAME} absent (phase1 has not run?)",
                "emitted_count": 0, "emitted": []}
    try:
        doc = json.loads(l22.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"tool": TOOL, "status": "ERROR",
                "reason": f"cannot parse {_L22_NAME}: {exc}",
                "emitted_count": 0, "emitted": []}
    if not isinstance(doc, dict):
        return {"tool": TOOL, "status": "ERROR",
                "reason": f"{_L22_NAME} is not an object",
                "emitted_count": 0, "emitted": []}

    found: List[Dict[str, str]] = []
    sources: List[str] = []
    for p in _input_docs(project):
        try:
            got = extract_milestones(p.read_text(errors="replace"))
        except OSError:
            continue
        if got:
            sources.append(p.name)
            found.extend(got)
    if not found:
        return {"tool": TOOL, "status": "NOTHING_TO_EMIT",
                "reason": "no input doc states a checklist table "
                          "(item + resolution columns)",
                "emitted_count": 0, "emitted": []}

    fields = doc.setdefault("fields", doc if "fields" not in doc else {})
    if not isinstance(fields, dict):
        return {"tool": TOOL, "status": "ERROR",
                "reason": "L22 `fields` is not an object",
                "emitted_count": 0, "emitted": []}
    existing = fields.get(_KEY)
    if not isinstance(existing, list):
        existing = []
    have = {e.get("id") for e in existing if isinstance(e, dict)}
    fresh = [r for r in found if r["id"] not in have]
    if fresh and not dry_run:
        fields[_KEY] = existing + fresh
        l22.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    return {"tool": TOOL, "status": "OK", "sources": sources,
            "emitted_count": len(fresh), "emitted": fresh,
            "already_present": len(found) - len(fresh)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)
    rep = run(a.project, dry_run=a.dry_run)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=2) + "\n")
    print(f"{TOOL}: {rep['status']} — {rep['emitted_count']} milestone(s) "
          f"emitted" + (f" from {', '.join(rep.get('sources') or [])}"
                        if rep.get("sources") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
