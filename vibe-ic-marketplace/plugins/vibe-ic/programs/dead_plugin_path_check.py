#!/usr/bin/env python3
"""dead_plugin_path_check.py — no retired-second-plugin path may ship.

After plugin unification the deterministic-edition plugin tree no longer
exists anywhere, so any doctrine/path that references it is dead: a guard
like "if you have the deterministic edition installed" never fires, and
an agent following the text verbatim runs a nonexistent checker.

This checker scans the shipped bundle (skills/ + programs/ + _shared/ by
default) for the retired plugin token and fails on any occurrence —
path forms (`plugins/<token>/...`) and bare prose mentions alike, since
both reintroduce dead doctrine.

THE DECISION #511 ASKED FOR: THIS ZERO NEEDS A DENOMINATOR
-----------------------------------------------------------
The verdict line used to read ``PASS — 0 retired-plugin reference(s)``. The
count of HITS was disclosed, which is more than the two gates #511 names did,
and it is still not enough — because the number that can be zero for the wrong
reason is not the hit count, it is the SCAN SIZE. ``audit()`` walks exactly
three subtrees and skips silently when a subtree is absent, so a root that
carries none of them scans zero files and reports the same sentence as a full
1200-file sweep of a clean bundle. MEASURED at v1.7.73+: run against a
structurally empty project directory, this checker printed
``PASS — 0 retired-plugin reference(s)`` and exited 0, having opened nothing.
That is the #447 class exactly ("a scan of 1239 files and a scan of 0 printed
the same sentence, byte for byte"), reached through a different door.

So the zero GROWS a denominator rather than being declared meaningful on its
own: the verdict now states how many files were read and how many of the three
bundle subtrees existed, and a scan that reached NO file is a disclosed
VACUOUS_PASS (rc 2), not a PASS. Under `tools/ci/repo_hygiene_gates.sh` the
`run` helper fails the suite on any non-zero rc, so a mis-rooted invocation
becomes RED there instead of silently green — the gate gets louder, never
quieter, and its FAIL on a real hit is untouched.

Exit: 0 = PASS (files scanned, no references)
      1 = FAIL (references listed)
      2 = VACUOUS_PASS (nothing was scanned — disclosed, NOT a clean verdict)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import _gate_denominator as _gd
import _published_tree as _pt

# Constructed at runtime so this checker never matches itself.
RETIRED_PLUGIN_TOKEN = "vibe-ic-" + "d"

_SCAN_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".json", ".txt", ".sh", ".tcl"}
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules"}
_BUNDLE_SUBTREES = ("skills", "programs", "_shared")

#: What ONE unit is, in this gate's own terms.
DENOMINATOR_UNIT = ("shipped bundle file(s) read and searched for the retired "
                    "plugin token")

RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2


def scan(plugin_root: str) -> Tuple[List[str], Dict[str, int]]:
    """Return (``path:lineno: line`` hits, scan statistics).

    The statistics are the denominator: ``files_scanned`` is how many files
    were actually READ, ``subtrees_present`` how many of the three bundle
    subtrees existed. ``audit()`` keeps the historic hits-only signature for
    its callers.
    """
    root = Path(plugin_root)
    me = Path(__file__).resolve()
    hits: List[str] = []
    files_scanned = 0
    files_considered = 0
    present: List[str] = []
    # SHIPPED means committed, so the bundle is what the COMMIT carries — not
    # what this disk holds. A walk answered "what is on this machine", and the
    # two diverge as soon as anyone runs the suite: measured at the commit that
    # landed this, 3379 files examined in a working checkout against 3323 in a
    # fresh worktree OF THE SAME COMMIT. `None` is "not a published tree" and
    # NEVER "published and empty" — a user's own project publishes nothing, and
    # there the walk is already the honest answer.
    published = _pt.published_paths(root)
    enumeration = "filesystem-walk" if published is None else "git-tracked"
    for sub in _BUNDLE_SUBTREES:
        base = root / sub
        if not base.is_dir():
            continue
        present.append(sub)
        candidates = [p for p in sorted(base.rglob("*"))
                      if p.is_file() and p.suffix in _SCAN_SUFFIXES
                      and not any(part in _SKIP_DIRS for part in p.parts)]
        if published is not None:
            candidates = _pt.filter_to_published(root, candidates)
        for p in candidates:
            files_considered += 1
            if p.resolve() == me:
                continue
            try:
                text = p.read_text(errors="replace")
            except Exception:
                continue
            files_scanned += 1
            if RETIRED_PLUGIN_TOKEN not in text:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if RETIRED_PLUGIN_TOKEN in line:
                    hits.append(f"{p}:{i}: {line.strip()[:120]}")
    return hits, {
        "files_scanned": files_scanned,
        "files_considered": files_considered,
        "subtrees_present": len(present),
        "subtrees_declared": len(_BUNDLE_SUBTREES),
        "subtrees": present,
        # Reported, not merely recorded: the walk and the tracked set produce
        # the same sentence, so the only way a reader can tell which one
        # answered is for the answer to say which one it was.
        "enumeration": enumeration,
    }


def audit(plugin_root: str) -> List[str]:
    """Return `path:lineno: line` hits for the retired token in the bundle."""
    return scan(plugin_root)[0]


def denominator(stats: Dict[str, int], plugin_root: str) -> _gd.Denominator:
    """What the scan actually READ. Zero owes a written reason (#496/#511)."""
    scanned = int(stats.get("files_scanned", 0))
    reason = ""
    if scanned == 0:
        subs = "/".join(_BUNDLE_SUBTREES)
        reason = (
            f"no file was read: {stats.get('subtrees_present', 0)} of "
            f"{stats.get('subtrees_declared', 0)} bundle subtree(s) ({subs}) "
            f"exist under {plugin_root!r} and they hold no file with a "
            f"scanned suffix. NOT a clean-bundle verdict — nothing was "
            f"searched, so this run says nothing about whether a retired-"
            f"plugin reference ships. Point the checker at the plugin root "
            f"(the directory that CONTAINS {subs}).")
    return _gd.Denominator(
        unit=DENOMINATOR_UNIT,
        examined=scanned,
        considered=int(stats.get("files_considered", 0)),
        not_applicable_reason=reason,
        details={"subtrees_present": stats.get("subtrees"),
                 "subtrees_declared": list(_BUNDLE_SUBTREES),
                 "plugin_root": str(plugin_root)},
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("plugin_root", nargs="?", default=".",
                   help="plugin root containing skills/ programs/ _shared/")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    hits, stats = scan(args.plugin_root)
    denom = denominator(stats, args.plugin_root)
    summary: Dict[str, object] = {"hits": len(hits)}
    _gd.attach(summary, denom)
    # NAMED IN EVERY VERDICT. The tracked set and the walk emit the same
    # sentence, so a fallback that is only recorded is a fallback nobody can
    # see — and invisibility is how the host-dependence this fixes survived.
    how = f" [{stats.get('enumeration', 'unknown')}]"
    for h in hits:
        print(h)
    if hits:
        # A real finding outranks everything: the scan reached files and one
        # of them carries the token. Unchanged rc, unchanged listing.
        print(f"FAIL — {len(hits)} retired-plugin reference(s); "
              f"{_gd.line_of(summary)}{how}")
        return RC_FAIL
    if denom.is_vacuous:
        print(f"[VACUOUS_PASS] dead_plugin_path_check: "
              f"{_gd.line_of(summary)}{how}")
        print(f"VACUOUS_PASS: {denom.not_applicable_reason}", file=sys.stderr)
        return RC_VACUOUS
    print(f"PASS — 0 retired-plugin reference(s); {_gd.line_of(summary)}{how}")
    return RC_PASS


if __name__ == "__main__":
    raise SystemExit(main())
