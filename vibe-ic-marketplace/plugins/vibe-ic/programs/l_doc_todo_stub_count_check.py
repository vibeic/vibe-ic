#!/usr/bin/env python3
"""l_doc_todo_stub_count_check.py — D3 program-first capture of the
``phase1-output-verify`` skill's "Completeness" checklist (item 1).

Rule (verbatim from the skill)
==============================
"open every L doc, count ``__TODO__`` strings. >0 means incomplete
extraction."

This is a trivial deterministic substring count over the *whole* JSON
serialization of every L*.json the phase1 runner emitted, with a strict
threshold of ``count == 0``. It is broader than
``phase1_structured_field_substance_check.py`` (which only scans a
curated 4-field allow-list with a 30% WARN/FAIL gate) — here ANY
``__TODO__`` left anywhere in ANY L doc is an incomplete extraction the
runner should not have shipped.

Why ``__TODO__`` specifically
=============================
The phase1 L-doc generators emit the literal placeholder ``__TODO__``
for a field they could not parse from input (e.g. an unnamed tester in
phase2, an unresolved pin name). The placeholder is the runner's own
"I could not extract this" sentinel; a finished extraction has zero of
them. The threshold (==0) is taken directly from the skill text ("> 0
means incomplete"), not invented.

Honest missing-data behaviour
=============================
  * generated_docs/ absent           → VACUOUS_PASS (phase1 not run yet),
                                        reported explicitly, never a
                                        silent clean PASS.
  * a malformed / unreadable L doc    → counted as an issue (raw-text
                                        scan still runs; if the bytes are
                                        unreadable it is reported, not
                                        swallowed).

Usage
=====
    python3 l_doc_todo_stub_count_check.py <project_dir|generated_docs_dir>
    python3 l_doc_todo_stub_count_check.py <dir> --json [out.json]

Exit codes
==========
    0  PASS (zero __TODO__ across all L docs) / VACUOUS_PASS
    1  FAIL (>= 1 __TODO__ in some L doc)
    2  argument or I/O error

Wiring
======
BLOCKING (`program_exit_zero`) at flow step D1. Measured over the 16 published
runs tracked under `benchmark-data/ic/**/phase1/generated_docs` before wiring:
0 red, 24-28 L docs scanned each. Blocking is affordable precisely because the
blast radius is empty, and the VACUOUS_PASS branch below is covered by the
sibling `phase1_all_l_docs_present_check`, which blocks the docs-absent case
at the same step.

NOT superseded by `gameable_placeholder_scan` — measured, not assumed
=====================================================================
`gameable_placeholder_scan` scans the same `L*.json` for a strictly larger
token set (`__TODO__` PLUS `<unknown>`, AUTO_ALIAS and VERDICT_PLACEHOLDER),
which invites the conclusion that this program is redundant. It is not, and the
difference is in the ACCEPTED INPUT SHAPE, not the token set:

    target                        this program        gameable_placeholder_scan
    project dir, clean            rc 0 PASS           rc 0 CLEAN
    project dir + one __TODO__    rc 1 FAIL           rc 1 FAIL
    generated_docs DIR, clean     rc 0 PASS (24 docs) rc 1 NO_GENERATED_DOCS
    empty project                 rc 0 VACUOUS_PASS   rc 1 NO_GENERATED_DOCS

`gameable_placeholder_scan._generated_docs_dir` resolves only
`<project>/phase1/generated_docs` and `<project>/generated_docs`, so handed the
generated_docs directory ITSELF — the shape `skills/phase1-output-verify/
SKILL.md` documents and this program accepts — it reports a FABRICATED red on a
corpus containing zero placeholders. Deleting this program in favour of that one
would therefore trade a real check for a false alarm on a documented input
shape. The two are complementary; neither is a superset.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: vibe-ic#1052. This gate reached the right conclusion and shipped it on the
#: wrong channel: it computed `VACUOUS_PASS`, printed it, and returned 0.
#:
#: The printed token is a REAL channel — `flow_compliance_check` promotes the
#: step when `_stdout_signals_vacuous` sees it, rc-independently — which is why
#: I first cleared this gate. That was wrong, and `gate_skip_routing_check` says
#: why in one sentence: "channel B survives only in the last 300 characters of
#: stdout+stderr that _check_program_exit_zero keeps; rc 2 has no such window,
#: which is why _vacuous_exit gives BOTH". `_OUTPUT_SNIPPET_CHARS = 300` is the
#: window. A disclosure that survives only if the gate stays quiet enough is not
#: a disclosure; the repo counts that tier separately and calls it fragile.
#:
#: So: rc 2 AND the sentinel. Same repair as #1002, #1018 and the three L-layer
#: gates in this same change.
import _vacuous_exit as _vx

TODO_TOKEN = "__TODO__"


def _find_gen_dir(target: Path) -> Optional[Path]:
    if any(target.glob("L1_*.json")) or (target / "L1_DATASHEET.json").is_file():
        return target
    for cand in (
        target / "phase1" / "generated_docs",
        target / "generated_docs",
    ):
        if cand.is_dir():
            return cand
    return None


def _count_todo_in_text(text: str) -> int:
    return text.count(TODO_TOKEN)


@dataclass
class DocFinding:
    file: str
    todo_count: int
    readable: bool


def scan(target: Path) -> Tuple[str, List[DocFinding], Dict[str, Any]]:
    gen_dir = _find_gen_dir(target)
    if gen_dir is None:
        return "VACUOUS_PASS", [], {
            "reason": "no generated_docs directory in the project",
            "generated_docs": None,
            "l_docs_scanned": 0,
            "total_todo": 0,
            "docs_with_todo": 0,
            "unreadable_docs": 0,
        }

    l_files = sorted(gen_dir.glob("L*.json"))
    findings: List[DocFinding] = []
    total = 0
    unreadable = 0
    for f in l_files:
        try:
            text = f.read_text(errors="ignore")
            readable = True
        except Exception:
            text = ""
            readable = False
            unreadable += 1
        n = _count_todo_in_text(text)
        total += n
        if n > 0 or not readable:
            findings.append(DocFinding(file=f.name, todo_count=n, readable=readable))

    summary = {
        "generated_docs": str(gen_dir),
        "l_docs_scanned": len(l_files),
        "total_todo": total,
        "docs_with_todo": sum(1 for x in findings if x.todo_count > 0),
        "unreadable_docs": unreadable,
    }
    if not l_files:
        # generated_docs exists but holds no L*.json — nothing extracted.
        summary["reason"] = "generated_docs holds no L*.json — nothing extracted"
        return "VACUOUS_PASS", findings, summary
    if total > 0 or unreadable > 0:
        return "FAIL", findings, summary
    return "PASS", findings, summary


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Count __TODO__ stubs across all phase1 L*.json "
                    "(threshold == 0).")
    ap.add_argument("target", help="project dir, phase1 dir, or generated_docs dir")
    ap.add_argument("--json", nargs="?", const="-", default=None,
                    help="emit JSON report (to path, or stdout if no path)")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    verdict, findings, summary = scan(target)
    report = {
        "gate": "l_doc_todo_stub_count_check",
        "verdict": verdict,
        "summary": summary,
        "findings": [asdict(f) for f in findings],
    }

    if args.json is not None:
        blob = json.dumps(report, indent=2, ensure_ascii=False)
        if args.json == "-":
            print(blob)
        else:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(blob + "\n", encoding="utf-8")
            print(f"{verdict}: l_doc_todo_stub_count_check (report -> {out})")
    else:
        print(f"{verdict}: l_doc_todo_stub_count_check — "
              f"scanned={summary['l_docs_scanned']} "
              f"total___TODO__={summary['total_todo']} "
              f"docs_with_todo={summary['docs_with_todo']} "
              f"unreadable={summary['unreadable_docs']}")
        for f in findings:
            tag = "unreadable" if not f.readable else f"{f.todo_count}x __TODO__"
            print(f"  [{tag}] {f.file}")

    if verdict == "FAIL":
        return _vx.RC_FAIL
    if verdict == "VACUOUS_PASS":
        # the second channel, on stderr so a `--json -` document stays parseable
        _vx.announce_vacuous("l_doc_todo_stub_count_check",
                             _vx.skip_reason(summary, "no L*.json examined"))
        return _vx.RC_VACUOUS
    return _vx.RC_PASS


if __name__ == "__main__":
    sys.exit(main())
