#!/usr/bin/env python3
"""nda_tracked_tree_scan.py — the NDA guards all scan CHANGES; nothing scanned
what is already HERE.

THIS GATE BLOCKS (rc=1) on any NDA token in the tracked tree.

WHY THIS GATE EXISTS
--------------------
This repo has three NDA guards and every one of them looks at a DELTA:

    commit_msg_nda_check    the commit MESSAGES a push introduces
    nda_diff_scan_check     the CONTENT and PATHS a diff adds
    source_chip_agnostic    the plugin's own source

None of them can see a token that is ALREADY tracked. A token that landed
before a guard existed, or that a one-time hand clean-pass missed, is
invisible to all of them forever — they will keep reporting clean while the
repo keeps serving the literal. This repo has had two full-history NDA
rewrites; what it never had is a standing check that the CURRENT tracked
tree is clean.

WHAT THIS GATE'S OWN FIRST VERSION GOT WRONG — kept, because it is the
sharpest statement of what "tracked" has to mean here. It read the
WORKING-TREE file for every tracked path and reported two documents as
carrying a commercial-PDK token. They did not. Both tracked entries are
SYMLINKS (mode 120000) whose targets are untracked local run outputs; the
scan followed the links and read content the repository does not contain
and a clone would never see. The finding was real on this machine and
false about the repo, and it was one commit away from being published as
a leak report. A guard that manufactures a leak is not safer than one that
misses one — it is differently wrong, and it burns the credibility the
real findings depend on. Hence: read the INDEXED BLOB, never the working
tree, and treat a symlink's tracked content as the target PATH STRING it
actually is.

WHAT IT CHECKS
--------------
Every tracked file's PATH and CONTENT against the same token family the
other guards use. One source of truth: if a role is added to the store,
this gate starts covering it with no edit here.

OUTPUT IS MASKED. Findings name the file, the pattern INDEX and the hit
count — never the literal. A gate that prints what it protects publishes
it into every CI log it runs in.

UNCONFIGURED IS A SKIP, NEVER A PASS
------------------------------------
When no token store is configured (the usual state for an outside
contributor — the store lives in a private config OUTSIDE this repo), this
gate has nothing to match and exits 2. Reporting PASS there would make
"I could not look" indistinguishable from "I looked and it is clean",
which is the exact defect this repo removes everywhere else.

chip-AGNOSTIC by construction: no literal appears in this file. The tokens
come from `_commercial_pdk`, which reads them from a private config.

USAGE
-----
    python3 nda_tracked_tree_scan.py [--repo DIR] [--json OUT]

EXIT CODES
----------
    0 = PASS      1 = FAIL (a token is tracked)      2 = SKIP (no store)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import List

# Extensions whose bytes are not text; reading them wastes the scan's budget
# and cannot carry a readable token anyway.
_BINARY_SUFFIXES = frozenset((
    ".gds", ".gds2", ".oas", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip",
    ".gz", ".bz2", ".xz", ".tar", ".bin", ".so", ".o", ".a", ".pyc", ".woff",
    ".woff2", ".ttf", ".ico", ".vcd", ".fsdb", ".shm", ".wlf",
))
# A file larger than this is a data dump, not prose or source. Scanned in
# CHUNKS rather than skipped: skipping by size is how a token hides in the
# one big file nobody looks at.
_CHUNK = 4 << 20


def _patterns():
    """The token family, compiled. Empty when no store is configured."""
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    try:
        import _commercial_pdk as _c
    except ImportError:
        return []
    try:
        fam = _c.nda_regex_family()
    except Exception:  # noqa: BLE001 — an unusable store is "no store"
        return []
    out = []
    for p in fam or []:
        out.append(p if hasattr(p, "search")
                   else re.compile(p, re.IGNORECASE))
    return out


def _tracked(repo: Path) -> List[str]:
    """Tracked paths, with their git index MODE.

    The mode is load-bearing. A tracked SYMLINK (120000) whose target is not
    tracked is a pointer to LOCAL content: reading the working-tree file
    follows the link and scans a file the repository does not contain. The
    first version of this gate did exactly that and reported two tracked
    documents as carrying an NDA token — the token was in the untracked local
    run output the links pointed at, and a clone would never have seen it. A
    guard that manufactures a leak report is as bad as one that misses a leak,
    and this one nearly published the claim.

    A symlink's tracked CONTENT is its target PATH STRING. That string IS
    repo content and is scanned as a blob — an earlier version skipped
    symlinks outright, claiming the path scan already covered them, but the
    path scan reads the LINK's own name and never the target it points at.
    """
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-s"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        try:
            meta, rel = line.split("\t", 1)
            mode = meta.split()[0]
        except (ValueError, IndexError):
            continue
        out.append((mode, rel))
    return out


def scan(repo: Path) -> dict:
    pats = _patterns()
    if not pats:
        return {"configured": False, "findings": [], "scanned": 0}
    findings, scanned, links, wanted = [], 0, 0, []
    for mode, rel in _tracked(repo):
        path_hits = [i for i, p in enumerate(pats) if p.search(rel)]
        if path_hits:
            findings.append({"file": rel, "carrier": "PATH",
                             "patterns": path_hits, "hits": len(path_hits)})
        if mode == "120000":
            # A symlink's tracked BLOB is its TARGET PATH STRING, and that
            # string is repo content like any other. An earlier version
            # skipped symlinks entirely with the comment "already scanned
            # above" — but "above" scans the LINK's own path, never the
            # target it names, so a link pointing into `<token>_dir/...`
            # went unseen. Read the blob (it is one short line); what must
            # NOT happen is following the link into the working tree.
            links += 1
            wanted.append(rel)
            continue
        if Path(rel).suffix.lower() in _BINARY_SUFFIXES:
            continue
        wanted.append(rel)

    # Read the INDEXED BLOBS, never the working-tree files: the working tree
    # may hold local edits or, through a link, content the repo does not
    # contain. What ships is what git has.
    #
    # One streaming `cat-file --batch` rather than one process per file:
    # 19 930 spawns took ~116 s, which is a gate people start skipping. The
    # tokens stay inside this process either way — passing them to `git grep`
    # would put the literal in a command line, visible in `ps` to every user
    # on the host.
    for rel, text in _blobs(repo, wanted):
        scanned += 1
        content_hits = {}
        for i, p in enumerate(pats):
            n = len(p.findall(text))
            if n:
                content_hits[i] = n
        if content_hits:
            findings.append({"file": rel, "carrier": "CONTENT",
                             "patterns": sorted(content_hits),
                             "hits": sum(content_hits.values())})
    return {"configured": True, "findings": findings,
            "scanned": scanned, "symlinks": links}


def _blobs(repo: Path, rels: List[str]):
    """Yield (path, text) for each tracked path, via one `cat-file --batch`."""
    if not rels:
        return
    proc = subprocess.Popen(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    # The requests go out on their OWN thread. Writing all ~20 000 of them
    # before reading any output DEADLOCKS: git fills its stdout pipe and
    # blocks, this process is still blocked writing stdin, and neither side
    # moves. That version did not fail — it HUNG past a 600 s timeout, which
    # is the worst shape for a gate, because it reads as a slow scan rather
    # than a broken one.
    def _feed():
        try:
            proc.stdin.write(("".join(f":{r}\n" for r in rels)).encode())
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    writer = threading.Thread(target=_feed, daemon=True)
    writer.start()
    try:
        for rel in rels:
            header = proc.stdout.readline()
            if not header:
                break
            parts = header.split()
            if len(parts) < 3:
                # "<obj> missing" — the path is not in the index after all.
                continue
            size = int(parts[2])
            data = proc.stdout.read(size)
            proc.stdout.read(1)                     # trailing newline
            yield rel, data.decode("utf-8", errors="replace")
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        proc.wait()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()

    rep = scan(repo)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=2) + "\n")

    if not rep["configured"]:
        print("[SKIP] nda_tracked_tree_scan: no token store configured — "
              "nothing to match. This is NOT a clean result.")
        return 2

    if rep["findings"]:
        print(f"[FAIL] {len(rep['findings'])} tracked path(s) carry an NDA "
              f"token. The delta guards cannot see these: nothing about them "
              f"is changing, so they stay served by the public repo forever.")
        for f in rep["findings"]:
            print(f"   {f['carrier']:7s} {f['file']}  "
                  f"(pattern index {f['patterns']}, {f['hits']} hit(s))")
        print("   Output is MASKED on purpose — the literal is never printed.")
        return 1

    print(f"[PASS] nda_tracked_tree_scan: {rep['scanned']} tracked blob(s) "
          f"scanned (incl. {rep.get('symlinks', 0)} symlink target-string(s)), no "
          f"NDA token in any tracked path or content.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
