#!/usr/bin/env python3
"""_published_tree.py — "is this artefact PUBLISHED?", answered once.

WHY THIS MODULE EXISTS
======================
Three independent programs asked the same question on the same day and three
independent programs got it wrong the same way: they asked THIS MACHINE'S DISK
whether an artefact is there, when the question was whether the PUBLISHED TREE
carries it. Published means git-TRACKED. A working checkout also holds whatever
the last local run left behind; a fresh clone, and a `git worktree`, hold only
what is tracked.

The consequence is not a cosmetic difference — it is a gate that gives DIFFERENT
VERDICTS ON DIFFERENT HOSTS for byte-identical code:

  provenance_output_hash_completeness_check (v1.6.88)
      37 declared outputs were present-but-untracked, turning three cells'
      honest "not shipped" disclosures into "the disclosure is false".
      PASS in a worktree, FAIL in a working checkout.

  cross_layer_reference_check (v1.6.90)
      corpus of 46 L1 documents on disk vs 23 tracked. Its regression BASELINE
      records counts, so a baseline recorded in a worktree read 3 and the same
      corpus read 4 in a checkout — CI failing for no change to the code.

  l4_systemrdl_export (this landing)
      299 L4 documents on disk vs 201 tracked. Its docstring already recorded
      "0 of 201" from an earlier bug, which is how we know 201 was a worktree
      count. audit-corpus PASSes in a worktree and FAILs in a checkout.

Whoever runs the flow locally fails; whoever does not, passes. That inverts the
signal: the more you exercise the tool, the more its gates lie to you.

THE DISCRIMINATOR
=================
Not every tree is a published one. A raw run directory handed over on its own,
or a run that happens to sit inside a repository uncommitted, has published
NOTHING — there tracked-ness is not a question that applies and presence on
disk is the honest answer. Callers say which they are:

    published_paths(root)                       -> tracked set, or None
    published_paths(root, require="x.jsonl")    -> None unless x.jsonl is tracked

`None` means "not a published tree — use the disk". It never means "published
and empty", and callers must keep those apart: collapsing them turns "I could
not look" into "I looked and there is nothing", which is the false-certificate
shape this repo keeps finding.

THE HOLE THIS FILTER LEFT OPEN: A TRACKED SYMLINK (vibe-ic#404)
===============================================================
Every caller asks the question by PATH and then answers it by DEREFERENCE:
`rel in published` decides the artefact ships, and `(root / rel).read_text()`
supplies the bytes. Those two are not the same question when `rel` is a symlink
(git mode 120000) whose TARGET the index does not carry. The link ships; its
content does not. A clean clone gets a dangling link; a host that kept its run
leftovers gets a file — from the same commit.

MEASURED on this repo's published corpus at the commit that landed this:

    tracked paths                                       20324
    tracked symlinks                                      172
    ...whose target the index does NOT carry               43   <- the hole
    of those 43, readable on a working checkout            15
    of those 43, readable in a clean worktree               0

    published cells whose netlist-width reader answers
    DIFFERENTLY on the two trees, same commit            3 / 15

That is precisely the host-dependence this module exists to eliminate, walking
back in through a path the PATH filter waves through. So a tracked symlink is
published only when the published tree also carries what it points AT.

WHY THE INDEX AND NOT `os.readlink`
====================================
The link text is read out of the git index (`ls-files -s` + `cat-file`), never
off the disk. Answering "where does this link point?" with this machine's
filesystem would reintroduce, inside the fix, the exact dependence being
removed — and it is not hypothetical: a sparse or partial checkout has the
index entry with no file behind it at all.
"""
from __future__ import annotations

import posixpath
import re
import subprocess
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Set

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

_SYMLINK_MODE = "120000"
# A link chain is followed, not assumed absent. Measured 0 of 172 in this
# corpus, so the loop is pinned by a fixture rather than by real data — but
# stopping at one hop would call a chain ending outside the tree "published",
# which is the very verdict this filter exists to refuse.
_MAX_LINK_HOPS = 8
_INDEX_MODE = re.compile(r"[0-7]{6}\Z")
_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class PublishedTreeIndeterminate(RuntimeError):
    """Git failed to enumerate a tree whose exact population was required."""


def _index(root: Path, timeout: Optional[float], *,
           strict: bool = False) -> Optional[List[tuple]]:
    """(mode, blob-sha, path) for every index entry under `root`, or None.

    `ls-files -s` rather than plain `ls-files` because the MODE is what
    distinguishes a file that ships its own bytes from a symlink that only
    ships a promise about someone else's.
    """
    try:
        r = _pr.run(["git", "-C", str(root), "ls-files", "-s", "-z"],
                           capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError, _pr.Stalled) as exc:
        # `_pr.Stalled` is a RuntimeError, so `SubprocessError` does not catch
        # it and it would escape this helper into a caller that has no handler
        # for it. It belongs HERE: a git that stopped moving is exactly this
        # branch's subject — "git could not be asked", which is not the same as
        # clean and is what the strict path raises Indeterminate about.
        if strict:
            raise PublishedTreeIndeterminate(
                f"git could not enumerate the published tree {root}: {exc}") \
                from exc
        return None
    if r.returncode != 0:
        if strict:
            raise PublishedTreeIndeterminate(
                f"git index enumeration failed for {root} with rc "
                f"{r.returncode}")
        return None
    rows: List[tuple] = []
    seen_paths: Set[str] = set()
    for ent in r.stdout.split("\0"):
        if not ent:
            continue
        if "\t" not in ent:
            if strict:
                raise PublishedTreeIndeterminate(
                    f"git returned a malformed index row for {root}")
            continue
        meta, path = ent.split("\t", 1)
        parts = meta.split()
        if len(parts) < 2 or not path:
            if strict:
                raise PublishedTreeIndeterminate(
                    f"git returned an incomplete index row for {root}")
            continue
        if strict and (len(parts) != 3
                       or _INDEX_MODE.fullmatch(parts[0]) is None
                       or _OBJECT_ID.fullmatch(parts[1]) is None
                       or parts[2] != "0" or path in seen_paths):
            raise PublishedTreeIndeterminate(
                f"git returned an ambiguous index identity for {root}")
        rows.append((parts[0], parts[1], path))
        seen_paths.add(path)
    return rows


def _blobs(root: Path, shas: List[str], timeout: Optional[float], *,
           strict: bool = False) -> Dict[str, str]:
    """Blob text for each sha, in ONE `cat-file --batch`.

    Absent from the result means "could not be read" — never "empty". A link
    whose text this cannot recover is treated as not delivering content, since
    the alternative is to claim publication on the strength of a read failure.
    """
    if not shas:
        return {}
    try:
        r = _pr.run(["git", "-C", str(root), "cat-file", "--batch"],
                           input=("\n".join(shas) + "\n").encode(),
                           capture_output=True, text=False)
    except (OSError, subprocess.SubprocessError) as exc:
        if strict:
            raise PublishedTreeIndeterminate(
                f"git could not read published symlink blobs for {root}: "
                f"{exc}") from exc
        return {}
    if r.returncode != 0:
        if strict:
            raise PublishedTreeIndeterminate(
                f"git blob enumeration failed for {root} with rc "
                f"{r.returncode}")
        return {}
    out, pos, got = r.stdout, 0, {}
    for expected_sha in shas:
        nl = out.find(b"\n", pos)
        if nl < 0:
            if strict:
                raise PublishedTreeIndeterminate(
                    f"git returned a truncated blob header for {root}")
            break
        header = out[pos:nl].split()
        # "<sha> missing" — two fields, no body follows.
        if len(header) != 3:
            if strict:
                raise PublishedTreeIndeterminate(
                    f"git could not supply every published symlink blob for "
                    f"{root}")
            pos = nl + 1
            continue
        if strict and (header[0].decode("ascii", "replace") != expected_sha
                       or header[1] != b"blob"):
            raise PublishedTreeIndeterminate(
                f"git returned the wrong published symlink blob for {root}")
        try:
            size = int(header[2])
        except ValueError:
            if strict:
                raise PublishedTreeIndeterminate(
                    f"git returned a malformed blob size for {root}")
            break
        if size < 0 or nl + 1 + size >= len(out):
            if strict:
                raise PublishedTreeIndeterminate(
                    f"git returned a truncated blob body for {root}")
            break
        got[header[0].decode("ascii", "replace")] = \
            out[nl + 1:nl + 1 + size].decode("utf-8", "replace")
        pos = nl + 1 + size + 1          # body, then git's trailing newline
    if strict and pos != len(out):
        raise PublishedTreeIndeterminate(
            f"git returned trailing bytes after published symlink blobs for "
            f"{root}")
    if strict and set(got) != set(shas):
        raise PublishedTreeIndeterminate(
            f"git did not return the exact published symlink blob set for "
            f"{root}")
    return got


def _delivers_content(rel: str, link_text: Dict[str, str],
                      modes: Dict[str, str], dirs: Set[str]) -> bool:
    """Does the PUBLISHED tree carry what `rel` — a symlink — points at?

    Resolution is lexical against the index. It follows a chain of tracked
    links, and refuses on anything that leaves the published tree: an absolute
    target, a `..` escape, an unreadable link, or a cycle.
    """
    cur = rel
    for _ in range(_MAX_LINK_HOPS):
        target = link_text.get(cur)
        if target is None or target.startswith("/"):
            return False
        nxt = posixpath.normpath(
            posixpath.join(posixpath.dirname(cur), target.strip("\n")))
        if nxt == "." or nxt.startswith(".."):
            return False
        mode = modes.get(nxt)
        if mode is None:
            # git tracks files, never directories: a link to a DIRECTORY the
            # tree carries files under does deliver content to a clean clone.
            return nxt in dirs
        if mode != _SYMLINK_MODE:
            return True
        cur = nxt
    return False


def published_paths(root: Path,
                    require: Optional[str] = None,
                    timeout: Optional[float] = 180, *,
                    strict: bool = False) -> Optional[FrozenSet[str]]:
    """Paths whose CONTENT the published tree under `root` delivers.

    Tracked, minus the symlinks that point outside it (#404) — a clean clone
    receives those as dangling links, so their bytes are not a reader's bytes.

    Returns None when `root` is not a published tree: not in a git work tree,
    git unavailable, nothing tracked under it, or — when `require` is given —
    that path is not itself published. `require` is how a caller says "this is
    a published DELIVERABLE", keyed on the artefact that makes it one (its
    ledger, its manifest), rather than on the accident of some file under it
    happening to be committed.

    ``strict=True`` is for a parent-manifested semantic gate.  Such a caller
    also passes ``timeout=None``: its owning process supervisor classifies a
    stalled Git child as NORECORD.  Git launch/protocol/exit failures raise
    instead of turning an unreadable index into a host-local disk population.
    A valid empty index retains the ordinary ``None``/loose-tree contract;
    strictness changes probe failure handling, not the caller's population.
    """
    if strict and timeout is not None:
        raise ValueError(
            "strict published-tree probes must be owned without an inner timeout")
    rows = _index(root, timeout, strict=strict)
    if rows is None:
        return None
    # EMPTY IS DECIDED ON THE RAW INDEX, BEFORE THE SYMLINK DROP. A tree whose
    # every entry is a hollow link is a published tree that publishes nothing;
    # letting the drop empty the set would return None, send the caller to the
    # disk, and read exactly the leftovers this refuses to read.
    if not rows:
        return None
    modes = {p: m for m, _s, p in rows}
    links = [(p, s) for m, s, p in rows if m == _SYMLINK_MODE]
    if links:
        text = _blobs(root, [s for _p, s in links], timeout, strict=strict)
        link_text = {p: text[s] for p, s in links if s in text}
        dirs: Set[str] = set()
        for p in modes:
            parts = p.split("/")
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]))
        paths = frozenset(
            p for p in modes
            if modes[p] != _SYMLINK_MODE
            or _delivers_content(p, link_text, modes, dirs))
    else:
        paths = frozenset(modes)
    if require is not None and require not in paths:
        return None
    return paths


def is_published(root: Path, rel: str,
                 published: Optional[FrozenSet[str]] = None,
                 require: Optional[str] = None) -> bool:
    """Does this deliverable SHIP `rel`?

    Falls back to the disk when `root` is not a published tree. Pass a
    `published` set computed once if you are asking about many paths — the git
    call is not free and the answer cannot change mid-audit.
    """
    if published is None:
        published = published_paths(root, require=require)
    if published is None:
        return (root / rel).is_file()
    return rel in published


def filter_to_published(root: Path, paths: Iterable[Path],
                        require: Optional[str] = None,
                        published: Optional[FrozenSet[str]] = None) -> List[Path]:
    """Keep only the paths the published tree carries.

    Order-preserving. When `root` is not a published tree every path is kept,
    because nothing has been published and the caller's own walk is already
    the right answer.
    """
    paths = list(paths)
    if published is None:
        published = published_paths(root, require=require)
    if published is None:
        return paths
    root = root.resolve()
    keep: List[Path] = []
    for p in paths:
        try:
            rel = p.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in published:
            keep.append(p)
    return keep
