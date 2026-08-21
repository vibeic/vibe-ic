#!/usr/bin/env python3
"""doc_table_row_placement_check.py — a table row in the middle of a paragraph
is a swallowed sentence, and a version gate that checks AGREEMENT cannot see it.

THIS GATE BLOCKS (rc=1).

THE DEFECT, MEASURED 2026-08-21
===============================
``plugin_version_prose_sync_check`` asserts that a version stated in prose EQUALS
the shipped one. It is a good gate and it is blind to this: a version claim
inserted in the WRONG PLACE still agrees.

One release inserted a two-row version-and-count table fragment FIVE TIMES into
running prose in a published document, each time REPLACING the sentence that was
there. The next twenty-five releases faithfully advanced the number inside the
spurious rows, which is exactly why nothing noticed — every gate that looked at
those numbers found them correct, and the missing sentences were not anybody's
denominator.

Placement is checkable and agreement is not the same question. This checks
placement.

THE RULE, AND WHY IT IS THE SEPARATOR AND NOT THE NEIGHBOURS
============================================================
In GitHub-Flavoured Markdown a table is a header row, a DELIMITER row of dashes,
then body rows. The delimiter row is not decoration: without it the "table" is
not a table at all and every one of its lines renders as literal text with pipes
in it. So the rule is structural rather than typographic:

    every contiguous run of table-shaped lines must contain a delimiter row

A fragment pasted mid-paragraph has no delimiter row, because the paste took the
header and the data and left the dashes behind. A legitimate table always has
one, or it would not be rendering as a table for any reader.

Written the other way round — "a table row whose neighbours are prose" — the rule
needs a definition of prose and inherits every argument about lists, block quotes
and footnotes. It does not need one.

WHAT IS SKIPPED, AND WHY
========================
Fenced blocks (``` and ~~~). Inside a fence everything is literal, so a pipe
table drawn as an EXAMPLE — of which this repository has many, including in this
program's own tests — is not a claim about anything and has no delimiter row by
design. Skipping fences is what keeps the sweep at zero false positives; see the
corpus figures in the landing report.

WHAT IT DOES NOT CLAIM
======================
It does not read the numbers. Whether a version claim is CORRECT is
``plugin_version_prose_sync_check``'s question and this program never forms an
opinion about it. The two are complementary and neither subsumes the other:
placement without agreement passes a stale number in a real table, agreement
without placement passes a correct number in a swallowed sentence.

EXIT CODES
==========
    0  every table-shaped line in every examined document belongs to a table
    1  REFUSED — at least one run of table-shaped lines carries no delimiter
       row; the document, the line number, the lines and their prose
       neighbours are printed
    2  VACUOUS — no document was examined (`_vacuous_exit`'s tier, announced)
    3  the command line was rejected (`_gate_usage_exit`)

USAGE
-----
    doc_table_row_placement_check.py [PATH...] [--repo DIR] [--json OUT]

    With no PATH, every tracked ``*.md`` in --repo is examined. A PATH may be a
    file or a directory; a directory is walked for ``*.md``.

chip-AGNOSTIC: Markdown structure only. No design, PDK, vendor or SKU literal.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import _atomic_artefact as _atomic
import _gate_usage_exit as _usage
import _vacuous_exit as _vac

TOOL = "doc_table_row_placement_check"

#: A GFM delimiter row: cells of dashes, optionally colon-aligned. A single
#: dash per cell is legal (`|-|-|-|`) and was the first false positive this
#: pattern produced when it demanded two, on a vendored upstream document.
DELIMITER = re.compile(r"\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?$")

#: Opening/closing token of a fenced block. Length is not checked beyond three
#: because a longer fence is still a fence.
FENCE = re.compile(r"^\s*(?:```|~~~)")


def is_row(line: str) -> bool:
    """A table-SHAPED line: begins a cell and closes at least one more.

    Two pipes is the floor because ``| x`` is an ordinary sentence that happens
    to start with a pipe, and one-cell tables do not occur in this corpus.
    """
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def orphan_blocks(text: str) -> List[Tuple[int, List[str], str, str]]:
    """``[(1-based first line, block lines, line before, line after)]``.

    One entry per contiguous run of table-shaped lines that carries no
    delimiter row. The neighbours travel with the finding because they are the
    evidence: they are the prose the fragment was pasted into, and in the
    measured case they are the halves of the sentence it replaced.
    """
    lines = text.splitlines()
    out: List[Tuple[int, List[str], str, str]] = []
    i, n, fenced = 0, len(lines), False
    while i < n:
        if FENCE.match(lines[i]):
            fenced = not fenced
            i += 1
            continue
        if fenced or not is_row(lines[i]):
            i += 1
            continue
        j = i
        while j < n and not FENCE.match(lines[j]) and is_row(lines[j]):
            j += 1
        block = lines[i:j]
        if not any(DELIMITER.fullmatch(b.strip()) for b in block):
            before = lines[i - 1].strip() if i > 0 else ""
            after = lines[j].strip() if j < n else ""
            out.append((i + 1, block, before, after))
        i = j
    return out


def tracked_markdown(repo: Path) -> Optional[List[Path]]:
    """Every tracked ``*.md``, or None if this is not a readable repository.

    Tracked rather than globbed on purpose: an untracked scratch document is
    not something this repository publishes, and walking the filesystem would
    pull in vendored trees and agent worktrees that no landing touches.
    """
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", "*.md"],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return None
    return [repo / p for p in r.stdout.split("\0") if p]


def _expand(paths: List[Path]) -> List[Path]:
    out: List[Path] = []
    for p in paths:
        if p.is_dir():
            out.extend(sorted(p.rglob("*.md")))
        else:
            out.append(p)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = _usage.GateArgumentParser(
        prog=TOOL,
        description="refuse a table row that does not belong to a table")
    ap.add_argument("paths", nargs="*", type=Path, metavar="PATH")
    ap.add_argument("--repo", type=Path, default=Path("."),
                    help="repository whose tracked *.md are examined when no "
                         "PATH is given")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    if args.paths:
        for p in args.paths:
            if not p.exists():
                return _usage.usage_error(TOOL, f"{p} does not exist")
        docs = _expand(args.paths)
    else:
        docs = tracked_markdown(args.repo)
        if docs is None:
            return _usage.usage_error(
                TOOL, f"--repo {args.repo} is not a readable git repository, so "
                      f"the document set could not be established")

    findings: List[dict] = []
    examined = 0
    rows_seen = 0
    for doc in docs:
        try:
            text = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        examined += 1
        lines = text.splitlines()
        rows_seen += sum(1 for line in lines if is_row(line))
        for lineno, block, before, after in orphan_blocks(text):
            findings.append({
                "document": str(doc), "line": lineno,
                "lines": block, "before": before, "after": after,
            })

    report = {"tool": TOOL, "documents": examined, "table_rows": rows_seen,
              "findings": findings}
    if args.json:
        _atomic.write_json(args.json, report)

    head = (f"{examined} document(s), {rows_seen} table-shaped line(s) examined")

    if examined == 0:
        _vac.announce_vacuous(TOOL, "no-documents")
        print(f"[VACUOUS] {TOOL}: no document was examined, so nothing was "
              f"checked; this is NOT a pass")
        return _vac.RC_VACUOUS

    if findings:
        for f in findings:
            print(f"  [ORPHAN TABLE ROW] {f['document']}:{f['line']} — "
                  f"{len(f['lines'])} table-shaped line(s) with no delimiter "
                  f"row, so this renders as literal text, not as a table")
            for line in f["lines"][:4]:
                print(f"      {line.strip()[:140]}")
            if f["before"]:
                print(f"      preceded by prose: {f['before'][:110]}")
            if f["after"]:
                print(f"      followed by prose: {f['after'][:110]}")
        print(f"[FAIL] {TOOL}: {len(findings)} table fragment(s) sit outside any "
              f"table [{head}]. A version or population claim placed here still "
              f"AGREES with the shipped value, so no agreement gate can see it — "
              f"and the sentence it replaced is gone.")
        return _vac.RC_FAIL

    print(f"[PASS] {TOOL}: every table-shaped line belongs to a table [{head}]")
    return _vac.RC_PASS


if __name__ == "__main__":
    sys.exit(main())
