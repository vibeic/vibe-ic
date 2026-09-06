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
    python3 nda_tracked_tree_scan.py [--repo DIR] [--ref REF] [--json OUT]

`--ref origin/main` judges what is PUBLISHED rather than what this
checkout happens to hold; without it the gate WARNS when the checkout
is behind its upstream, because a clean verdict on a stale tree
describes a tree nobody is serving.

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
        # `nda_token_patterns()`, not `nda_regex_family()`. Two reasons, both
        # measured on this gate's own parent commit:
        #
        #  (a) COVERAGE. `nda_regex_family()` was three of the eight roles
        #      `nda_tokens()` names, so this gate — the one whose whole job is
        #      "no NDA token in the tracked tree" — could not see a foundry
        #      BRAND, the IP vendor or the IP part. Planting one token per role
        #      into a tracked file of a throwaway repo and running this gate:
        #      index 0,1,2 -> rc 1, index 3..7 -> rc 0 with the message "no NDA
        #      token in any tracked path or content". Five of eight tokens had
        #      a clean, specific, false PASS. The family is the whole token
        #      list now, and this call is what makes the docstring above ("if a
        #      role is added to the store, this gate starts covering it with no
        #      edit here") true rather than aspirational.
        #
        #  (b) ESCAPING. The loop below used to `re.compile()` the family
        #      LITERALS. A token is a literal, not a pattern: any regex
        #      metacharacter in it changed what this gate matched, silently and
        #      in the direction of matching MORE than the token. The builder
        #      escapes each token and applies the same boundaries every other
        #      NDA detector uses, so all of them now answer one question.
        pats = _c.nda_token_patterns()
    except Exception:  # noqa: BLE001 — an unusable store is "no store"
        return []
    return [re.compile(p, re.IGNORECASE) for p in pats or []]


def _roles():
    """The ROLE of each pattern index, index-aligned with `_patterns()`.

    Reported, never the literal. `pattern index [4]` on its own is unreadable
    to everyone but the operator holding the private config; `4=foundry_brand2`
    says what class of leak it is and still prints nothing protected."""
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    try:
        import _commercial_pdk as _c
        return list(_c.nda_regex_family_roles())
    except Exception:  # noqa: BLE001 — same "unusable store is no store" rule
        return []


def _toplevel(repo: Path) -> Path:
    """The repository ROOT, never the directory the caller happened to be in.

    #416. `--repo` defaulted to `"."`, and git's enumeration commands honour
    the current-directory PREFIX: run from `plugins/vibe-ic/`, `ls-files -s`
    and `ls-tree -r` list only that subtree AND print the paths with the
    prefix stripped. `_blobs` then asks for `{ref}:{rel}`, which resolves
    against the ROOT, so almost every request came back `missing` and was
    dropped. The gate reported

        [PASS] ... 21 tracked blob(s) scanned

    against 20143 from the repo root — the same verdict word for the
    accidental INTERSECTION of two unrelated directories' path sets. The
    enumeration and the lookups have to agree by CONSTRUCTION, not by the
    caller standing in the right place.
    """
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() \
        else repo


def _tracked(repo: Path, ref: str = None):
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
    # `-z`: NUL-separated records and RAW paths. Without it git C-QUOTES any
    # path that is not plain ASCII (`"a/\346\225\264 .json"`), and `_blobs`
    # then asks `cat-file` for that quoted string, which cannot resolve — so
    # every non-ASCII path comes back `missing`. That is the same failure the
    # `_toplevel` docstring above records from #416, reached by a different
    # route: the enumeration and the lookups must agree BY CONSTRUCTION.
    # Measured on a repo carrying 401 such paths: 401 unresolvable before, 0 after.
    cmd = (["git", "-C", str(repo), "ls-files", "-s", "-z"] if ref is None
           else ["git", "-C", str(repo), "ls-tree", "-r", "-z", "--full-tree", ref])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # #416. An empty list scans clean. "git would not tell me what is
        # tracked" is not "nothing is tracked" — raise, so the caller has to
        # decide, instead of inheriting a PASS.
        raise RuntimeError(
            f"git could not enumerate the tracked tree "
            f"({' '.join(cmd[3:])}): {r.stderr.strip()[:200]}")
    out = []
    for line in r.stdout.split("\0"):        # -z: records are NUL-separated
        if not line:
            continue
        try:
            meta, rel = line.split("\t", 1)
            mode = meta.split()[0]
        except (ValueError, IndexError):
            continue
        out.append((mode, rel))
    return out


def upstream_gap(repo: Path, ref: str = None):
    """(behind, ahead) versus the upstream this checkout tracks, or None.

    WHY THE GATE REPORTS THIS. Run against a STALE checkout, a clean verdict
    describes a tree nobody is serving, and a FINDING describes a leak that
    may have been fixed upstream already. Both happened: scanning a fork's
    local HEAD reported a token that its published `origin/main` does not
    contain — the checkout was simply behind. "Clean here" and "clean in
    what is published" are different claims and the gate must not blur them.
    """
    if ref is not None:
        return None
    up = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref",
         "--symbolic-full-name", "@{upstream}"],
        capture_output=True, text=True)
    if up.returncode != 0:
        return None
    counts = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--left-right", "--count",
         f"{up.stdout.strip()}...HEAD"], capture_output=True, text=True)
    if counts.returncode != 0:
        return None
    try:
        behind, ahead = (int(x) for x in counts.stdout.split())
    except ValueError:
        return None
    return (up.stdout.strip(), behind, ahead)


def scan(repo: Path, ref: str = None) -> dict:
    pats = _patterns()
    if not pats:
        return {"configured": False, "findings": [], "scanned": 0}
    repo = _toplevel(repo)
    findings, scanned, links, wanted, gitlinks = [], 0, 0, [], []
    for mode, rel in _tracked(repo, ref):
        path_hits = [i for i, p in enumerate(pats) if p.search(rel)]
        if path_hits:
            findings.append({"file": rel, "carrier": "PATH",
                             "patterns": path_hits, "hits": len(path_hits)})
        if mode == "160000":
            # A GITLINK — a submodule pointer. `cat-file` cannot read it:
            # the object is a commit in ANOTHER repository. Skipped, and
            # COUNTED, because this is the one exclusion that is correct
            # rather than convenient: what this repo publishes for a
            # submodule is its PATH (scanned just above) and its URL in
            # `.gitmodules` (a tracked blob, scanned like any other). The
            # submodule's own files are not in this tree. Four of these were
            # being silently dropped by the `missing` branch before #416, and
            # they are the reason `scanned` never matched what was requested.
            gitlinks.append(rel)
            continue
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
    unresolved = []
    for rel, text in _blobs(repo, wanted, ref):
        if text is None:
            unresolved.append(rel)
            continue
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
    return {"configured": True, "findings": findings, "ref": ref or "(index)",
            "roles": _roles(),
            "scanned": scanned, "symlinks": links,
            "repo": str(repo), "requested": len(wanted),
            "unresolved": unresolved, "gitlinks": gitlinks,
            "upstream": upstream_gap(repo, ref)}


def _blobs(repo: Path, rels: List[str], ref: str = None):
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
            prefix = ":" if ref is None else f"{ref}:"
            proc.stdin.write(
                ("".join(f"{prefix}{r}\n" for r in rels)).encode())
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
            # `cat-file --batch` echoes the REQUEST before `missing`, so a path
            # containing a space produces THREE tokens ending in `missing` and a
            # count-based test walks straight into `int(b"missing")`, killing the
            # whole scan. Key on the size field: a header is usable only when its
            # third token is a number.
            if len(parts) < 3 or not parts[2].isdigit():
                # "<obj> missing". #416: this used to `continue`, which made
                # a request that resolved to NOTHING indistinguishable from a
                # file that carried no token — and that is how 3316 dropped
                # lookups read as a clean tree. Report it; the caller fails.
                yield rel, None
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
    ap.add_argument("--ref", default=None,
                    help="scan this REF's tree instead of the index — e.g. "
                         "`origin/main` to judge what is actually PUBLISHED "
                         "rather than what this checkout happens to hold")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()

    try:
        rep = scan(repo, a.ref)
    except RuntimeError as exc:
        print(f"[ERROR] nda_tracked_tree_scan: {exc}\n"
              "   Nothing was scanned. This is NOT a clean result.")
        return 2
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=2) + "\n")

    if not rep["configured"]:
        print("[SKIP] nda_tracked_tree_scan: no token store configured — "
              "nothing to match. This is NOT a clean result.")
        return 2

    up = rep.get("upstream")
    if up and up[1]:
        print(f"[WARN] this checkout is {up[1]} commit(s) BEHIND {up[0]} — the "
              f"verdict below describes THIS tree, not what is published. "
              f"Re-run with --ref {up[0]} to judge the published tree.")

    if rep.get("unresolved"):
        # #416. Requested N blobs, git resolved fewer. Whatever the cause,
        # part of the tracked tree went unread, and an unread file is exactly
        # as silent as a clean one.
        print(f"[ERROR] nda_tracked_tree_scan: requested "
              f"{rep['requested']} blob(s), git resolved "
              f"{rep['scanned']} — {len(rep['unresolved'])} unreadable, "
              f"first: {rep['unresolved'][0]}\n"
              "   The tree was scanned INCOMPLETELY. This is NOT a clean "
              "result.")
        return 2

    if rep["findings"]:
        roles = rep.get("roles") or []
        print(f"[FAIL] {len(rep['findings'])} tracked path(s) carry an NDA "
              f"token. The delta guards cannot see these: nothing about them "
              f"is changing, so they stay served by the public repo forever.")
        for f in rep["findings"]:
            named = ", ".join(
                f"{i}={roles[i]}" if i < len(roles) else str(i)
                for i in f["patterns"])
            print(f"   {f['carrier']:7s} {f['file']}  "
                  f"(pattern index {named}, {f['hits']} hit(s))")
        print("   Output is MASKED on purpose — the literal is never printed.")
        return 1

    gl = rep.get("gitlinks") or []
    print(f"[PASS] nda_tracked_tree_scan: {rep['scanned']} tracked blob(s) "
          f"scanned (incl. {rep.get('symlinks', 0)} symlink target-string(s)), no "
          f"NDA token in any tracked path or content.")
    print(f"   repo root {rep.get('repo', '?')} — every requested blob was "
          f"read ({rep.get('requested', rep['scanned'])} requested).")
    if gl:
        print(f"   {len(gl)} submodule gitlink(s) hold no blob in this repo; "
              f"their path and their .gitmodules URL were scanned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
