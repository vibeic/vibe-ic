#!/usr/bin/env python3
"""eda_fork_sync_log_append_only_check.py — a fork-sync round is a RECORD of
what was measured on one day. A merge may only ADD one; it may never quietly
edit or shrink one that already landed.

THIS GATE BLOCKS (rc=1).

THE DEFECT (vibe-ic#1228), measured
===================================
`EDA_FORK_SYNC_LOG.md` is an append-only ledger: one `## <date> — <image>`
section per gatekeeper round, each section a complete list of that round's
per-tool verdicts. Consecutive rounds report the SAME tools, so consecutive
sections share long, byte-identical bullet lines.

That is precisely the input a 3-way text merge cannot read. Two rounds landing
out of order conflict, and the conflict hunk aligns on the shared trailing
bullet. Reproduced on `origin/main` @ `75776dbbb` merging PR #1238 (the
2026-08-13 round) with the 2026-08-12 round already landed:

    main    ## 2026-08-12 — 0.2.91   Trilinos · cocotb · ngspice · open_pdks
    PR1238  ## 2026-08-13 — 0.2.92   Trilinos · cocotb ·           open_pdks
                                                                   ^^^^^^^^^
    the `open_pdks` line falls OUTSIDE the conflict hunk — git treats the one
    line as common context belonging to both sections at once.

Resolve that hunk the obvious way — keep both sides, which is what "these are
two independent daily reports" tells you to do — and the shared line is claimed
by the LATER section. The earlier, ALREADY-LANDED round silently loses a
verdict it recorded:

    take-both-sides result
      ## 2026-08-12 — 0.2.91   Trilinos · cocotb · ngspice        <- open_pdks GONE
      ## 2026-08-13 — 0.2.92   Trilinos · cocotb · open_pdks

Nothing in the tree can tell that apart from a round that genuinely had three
verdicts. The file still parses, the markdown still renders, the diff still
reads `+6/-0` at a glance because the deletion is one line in a 250-line file.
The record of a measurement is destroyed and the destruction leaves no trace —
which is the whole failure this ledger exists to prevent.

WHY NO EXISTING GATE CATCHES IT
===============================
`tools/vibeic-eda/sync_image_version.py --check` guards the image ANCHOR (the
pointer set + the no-regress rule) and never reads the log. Nothing else in the
tree references `EDA_FORK_SYNC_LOG.md` at all. The log had a producer and a
reader and no gate between them.

WHAT THIS MEASURES
==================
BASE-vs-HEAD, not the file alone — the property is historical, so a snapshot
cannot carry it. For every dated section present in the BASE revision:

    1. it is still present in HEAD                       (not dropped)
    2. its body is byte-identical in HEAD                (not edited, not shrunk)
    3. sections appear in HEAD in their BASE order       (not reshuffled)

and on HEAD alone:

    4. no unresolved conflict markers survive in the file
    5. no two sections carry the same `<date> — <image>` heading

New sections are unconstrained in content; that is what "append" means. This
gate has NO opinion on what a round says, only that a round already written
down is not rewritten by a merge.

Rule 3 is what makes 1+2 sufficient. Without it a resolution could preserve
every base section byte-for-byte and still interleave a new one between them,
and the ledger would read as though the rounds happened in an order they did
not.

WHAT THIS REFUSES THAT YOU MIGHT NOT EXPECT, stated because a bound nobody
states gets read as a guarantee: text appended to the END of the file WITHOUT a
new `## ` heading is inside the last round's body, so it is reported as an edit
to that round. That is the intended reading — the ledger has no trailing prose
today, and the alternative is a rule that cannot distinguish "a footnote after
the last round" from "a bullet grafted onto the last round", which is the exact
ambiguity the merge exploited. Adding trailing prose is possible; it just has to
be done deliberately rather than arrive inside a merge resolution.

SWEEP (vibe-ic#1228, criterion 2)
=================================
Run over every commit that has ever touched the log on `origin/main` — 6 of 6,
each parent→child pair — plus `origin/main`→the correct resolution of #1238.
Zero false positives; every one is a pure append. The log has never, in its
whole history, legitimately edited a landed round, so the property is observed
rather than invented.

chip-AGNOSTIC: reads two revisions of one markdown ledger. No design, PDK or
vendor input.

USAGE
-----
    eda_fork_sync_log_append_only_check.py [<repo>] [--base REV] [--head REV] [--json OUT]
    eda_fork_sync_log_append_only_check.py --base-file A --head-file B

`--base` defaults to `origin/main`; `--head` defaults to the WORKTREE, so an
author gets an answer about what they have rather than about what they have
committed. `gatekeeper_review` passes an explicit `--head` because a reviewer is
not parked on the branch under review — omitting it there would measure the
reviewer's own checkout, which is how vibe-ic#459's shape guard returned PASS
over an unsquashed branch for a whole release.

The two-file form takes the same decision on plain files, for callers that have
the revisions on disk already.

EXIT CODES
----------
    0 = PASS     1 = a landed round was dropped, edited, reordered, duplicated,
                     or a conflict marker survived  (BLOCKING)
    2 = cannot measure — no such revision, unreadable file, not a git repo.
        NOT a pass: an unreadable base has not told us the ledger is intact,
        it has told us we could not look (vibe-ic#1228).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

#: The ledger this gate guards, repo-relative.
LOG_PATH = "tools/vibeic-eda/EDA_FORK_SYNC_LOG.md"

#: A round heading. The date and image tag are captured as OPAQUE text — the
#: gate compares headings, it never parses a version or judges a date, so a
#: change to the producer's heading format cannot make this gate wrong.
_HEADING = re.compile(r"^##[ \t]+(?P<title>\S.*?)[ \t]*$")

#: Left behind by an unresolved `git merge`. `>>>>>>>` and `<<<<<<<` are
#: unambiguous; a bare `=======` is not (markdown setext H1 underline), so it
#: is deliberately NOT matched on its own.
_CONFLICT = re.compile(r"^(<{7}|>{7})[ \t]")

RC_OK, RC_VIOLATION, RC_CANNOT_MEASURE = 0, 1, 2


class CannotMeasure(Exception):
    """The question was not answered. Never collapsed into a PASS."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=60)


def split_rounds(text: str):
    """`[(title, body_lines)]` in file order, preamble dropped.

    Body is every line up to the next `## ` heading, trailing blank lines
    stripped — so a resolution that only churns whitespace between sections is
    not reported as an edit. A dropped BULLET is never whitespace.
    """
    rounds, title, body = [], None, []
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            if title is not None:
                rounds.append((title, _trim(body)))
            title, body = m.group("title"), []
        elif title is not None:
            body.append(line)
    if title is not None:
        rounds.append((title, _trim(body)))
    return rounds


def _trim(lines):
    out = list(lines)
    while out and not out[-1].strip():
        out.pop()
    return out


def compare(base_text: str, head_text: str):
    """`[violation]` — empty means the ledger was appended to and nothing else."""
    v = []

    for n, line in enumerate(head_text.splitlines(), 1):
        if _CONFLICT.match(line):
            v.append({
                "kind": "conflict_marker",
                "line": n,
                "detail": f"line {n} is an unresolved merge conflict marker: "
                          f"{line[:40]!r}",
            })

    head_rounds = split_rounds(head_text)
    seen = {}
    for i, (title, _) in enumerate(head_rounds):
        if title in seen:
            v.append({
                "kind": "duplicate_round",
                "round": title,
                "detail": f"'## {title}' appears twice (positions {seen[title]} "
                          f"and {i}) — two rounds cannot be the same round; a "
                          f"merge that keeps both sides of one heading produced "
                          f"this",
            })
        else:
            seen[title] = i

    head_by_title = {t: b for t, b in head_rounds}
    head_order = {t: i for i, (t, _) in enumerate(head_rounds)}

    prev_pos = -1
    prev_title = None
    for title, base_body in split_rounds(base_text):
        if title not in head_by_title:
            v.append({
                "kind": "round_dropped",
                "round": title,
                "detail": f"'## {title}' is recorded in the base and is GONE "
                          f"from the head — a landed round cannot be unwritten",
            })
            continue

        head_body = head_by_title[title]
        if head_body != base_body:
            lost = [ln for ln in base_body if ln not in head_body]
            gained = [ln for ln in head_body if ln not in base_body]
            v.append({
                "kind": "round_edited",
                "round": title,
                "lines_lost": len(lost),
                "lines_gained": len(gained),
                "detail": f"'## {title}' already landed with {len(base_body)} "
                          f"line(s) and the head has {len(head_body)}: "
                          f"{len(lost)} lost, {len(gained)} gained. "
                          + (f"First line lost: {lost[0][:110]!r}. " if lost else "")
                          + "A round is the RECORD of one day's measurement; "
                            "a merge appends the next one, it does not revise "
                            "this one",
            })

        pos = head_order[title]
        if pos < prev_pos:
            v.append({
                "kind": "round_reordered",
                "round": title,
                "detail": f"'## {title}' follows '## {prev_title}' in the base "
                          f"and precedes it in the head — the ledger is "
                          f"chronological, so the order is part of the record",
            })
        prev_pos, prev_title = pos, title

    return v


def read_rev(repo: Path, rev: str, path: str) -> str:
    """The ledger at `rev`, or raise — an unreachable revision is rc=2, never a pass."""
    r = _git(repo, "show", f"{rev}:{path}")
    if r.returncode != 0:
        raise CannotMeasure(
            f"cannot read {path} at '{rev}': {(r.stderr or '').strip()[:200]} "
            f"— this is NOT a clean ledger, it is an unanswered question"
        )
    return r.stdout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".", help="repo root (default: .)")
    ap.add_argument("--base", default="origin/main",
                    help="revision the head is measured against (default: origin/main)")
    ap.add_argument("--head", default=None,
                    help="revision under review (default: the worktree)")
    ap.add_argument("--path", default=LOG_PATH, help=f"ledger path (default: {LOG_PATH})")
    ap.add_argument("--base-file", help="compare two files instead of two revisions")
    ap.add_argument("--head-file", help="see --base-file")
    ap.add_argument("--json", dest="json_out", help="write the verdict here")
    a = ap.parse_args(argv)

    repo = Path(a.repo).resolve()
    try:
        if bool(a.base_file) != bool(a.head_file):
            raise CannotMeasure("--base-file and --head-file are used together")
        if a.base_file:
            base_text = Path(a.base_file).read_text(encoding="utf-8")
            head_text = Path(a.head_file).read_text(encoding="utf-8")
            where = f"{a.base_file} -> {a.head_file}"
        else:
            if not (repo / ".git").exists():
                raise CannotMeasure(f"{repo} is not a git repository")
            base_text = read_rev(repo, a.base, a.path)
            if a.head:
                head_text = read_rev(repo, a.head, a.path)
                where = f"{a.base}:{a.path} -> {a.head}"
            else:
                head = repo / a.path
                if not head.is_file():
                    raise CannotMeasure(
                        f"{a.path} is present at '{a.base}' and absent from the "
                        f"worktree — the ledger was deleted, not appended to"
                    )
                head_text = head.read_text(encoding="utf-8")
                where = f"{a.base}:{a.path} -> worktree"
    except (CannotMeasure, OSError, UnicodeDecodeError) as e:
        print(f"[CANNOT-MEASURE] {e}", file=sys.stderr)
        if a.json_out:
            Path(a.json_out).write_text(
                json.dumps({"verdict": "CANNOT_MEASURE", "reason": str(e)}, indent=2),
                encoding="utf-8")
        return RC_CANNOT_MEASURE

    violations = compare(base_text, head_text)
    n_base = len(split_rounds(base_text))
    n_head = len(split_rounds(head_text))

    print(f"eda_fork_sync_log_append_only: {where}")
    print(f"  rounds in base : {n_base}")
    print(f"  rounds in head : {n_head}  ({n_head - n_base:+d})")

    if a.json_out:
        Path(a.json_out).write_text(json.dumps({
            "verdict": "FAIL" if violations else "PASS",
            "blocking": True,
            "base_rounds": n_base,
            "head_rounds": n_head,
            "violations": violations,
        }, indent=2), encoding="utf-8")

    if violations:
        print(f"[FAIL] {len(violations)} landed round(s) were changed by this "
              f"head, not appended to:", file=sys.stderr)
        for x in violations:
            print(f"  - {x['kind']}: {x['detail']}", file=sys.stderr)
        print("       BLOCKING. Re-do the merge as an APPEND: keep the base "
              "file whole and add the new round's whole block after it.",
              file=sys.stderr)
        return RC_VIOLATION

    print(f"[PASS] every one of the {n_base} landed round(s) survives "
          f"byte-identical and in order; {n_head - n_base} appended.")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
