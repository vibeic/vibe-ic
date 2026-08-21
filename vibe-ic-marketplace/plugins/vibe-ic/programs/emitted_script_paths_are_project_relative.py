#!/usr/bin/env python3
"""emitted_script_paths_are_project_relative.py — a deck identifies a
configuration, not a directory.

WHY THIS EXISTS
===============
A generated analysis script IS the identity of a measurement: two runs of one
configuration should produce the same deck, so the deck can be hashed and the two
runs compared as the same measurement. When the generator writes the ABSOLUTE
path of the directory the run happened in, the deck becomes unique per run. Every
identity taken over it then identifies WHERE the run happened instead of WHAT was
configured, and every cross-run identity check over it either refuses or drops
the script from the comparison — which is how a configuration silently stops
being comparable to itself.

MEASURED IN THIS REPOSITORY: the emitted power decks under the published trial
records link the netlist, the constraints and the parasitics by absolute
run-trial path, three such paths per deck.

TWO ROOTS ARE LEGITIMATE, AND THEY ARE NOT THE SAME AS A RUN DIRECTORY
=====================================================================
    TOOL ROOT      `/foss`, `/usr`, `/opt`, `/openlane`, `/pdk`, `/tools`, and
                   the ordinary system directories. These are the same on every
                   host that runs the pinned image, so a deck naming them
                   hashes the same everywhere. The open process kits live here
                   and are correctly named absolutely.
    RUN DIRECTORY  `/home/*`, `/root/*`, `/tmp/*`, `/mnt/*`, `/media/*`,
                   `/Users/*`. These are per-host and usually per-run. This is
                   the population the rule refuses.

WHERE THIS RULE HAS ITS TEETH
=============================
Pointed at this repository it guards the scripts that SHIP — the tool script and
the deck fixtures a future run reads. Its real subject is a freshly generated run
tree: `emitted_script_paths_are_project_relative.py <run-dir>` over the decks a
run just emitted is where a regression shows up on the day it is introduced,
rather than after the identity check has already started refusing.

PUBLISHED RECORDS ARE DISCLOSED, NOT SILENTLY SKIPPED
=====================================================
Scripts under a published record directory are counted and PRINTED with their
count, and are not findings. They are immutable evidence — rewriting them to buy
a green would destroy the record of the very defect this rule exists to prevent.
The count is on its own line so that "20 historical offenders, 0 live" can never
be read as "0 offenders". A rule whose PASS depends on an exclusion has to say
how big the exclusion is.

    rc 0   N>0 live scripts were read and none names a run directory.
    rc 1   a live script names a run directory.
    rc 2   NOT CHECKED — empty population, or a script that could not be read.
    rc 3   bad invocation.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

NAME = "emitted_script_paths_are_project_relative"
SUFFIXES = (".tcl", ".sp", ".sdc", ".ys", ".spi", ".cir")
SKIP_DIRS = {".git", "docs/capture", "node_modules", "__pycache__"}

# Top-level trees whose contents are COMMITTED OUTPUT OF A PAST RUN — published
# evidence, not something a future run will read. Enumerated rather than guessed,
# because the line between "a deck a run emitted" and "a deck a run will use" is
# the whole rule and must not be drawn by accident.
#
#     ppa-crosslayer/  ppa-e2e/   trial and end-to-end run records; every deck
#                                 under them names the run directory of the
#                                 specific past run that wrote it
#     docs/research/               captured run folders kept as triage evidence
RECORD_MARKERS = ("/records/", "ppa-crosslayer/", "ppa-e2e/",
                  "docs/research/", "fleet_run_folder_triage_evidence/")

RUN_ROOTS = ("/home/", "/root/", "/tmp/", "/mnt/", "/media/", "/Users/")

_ABS = re.compile(r"(?<![\w.-])(/[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+*-]+)+)")


def _walk(root: Path) -> List[Path]:
    """Every candidate under `root`, WITHOUT following symlinked directories.

    `Path.rglob` follows a symlinked directory, so a checkout carrying a link to
    a corpus elsewhere on the host would silently enlarge this population and
    make the count host-dependent. The verdict must be about the tree named.
    """
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        rel = "" if rel == "." else rel
        dirnames[:] = [d for d in dirnames
                       if not os.path.islink(os.path.join(dirpath, d))
                       and f"{rel}/{d}".lstrip("/") not in SKIP_DIRS
                       and d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(SUFFIXES):
                p = Path(dirpath) / fn
                if not p.is_symlink():
                    out.append(p)
    return sorted(out)


class Finding:
    def __init__(self, path: str, line: int, abspath: str):
        self.path, self.line, self.abspath = path, line, abspath

    def __str__(self) -> str:
        return (f"{self.path}:{self.line}: names the run directory "
                f"{self.abspath!r}. Two runs of one configuration then produce "
                f"different decks, so the deck identifies where the run "
                f"happened, not what was measured. Write it relative to the "
                f"project root or to a declared tool root.")


def offending_paths(text: str) -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0]
        for m in _ABS.finditer(line):
            p = m.group(1)
            if p.startswith(RUN_ROOTS):
                out.append((i, p))
    return out


def audit(root: Path) -> Tuple[List[Finding], List[Finding], List[str], int]:
    """(live findings, historical findings, unread, live scripts examined)."""
    live: List[Finding] = []
    historical: List[Finding] = []
    unread: List[str] = []
    examined = 0
    for path in _walk(root):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            unread.append(f"{rel}: {exc}")
            continue
        is_record = any(m in f"/{rel}" for m in RECORD_MARKERS)
        if not is_record:
            examined += 1
        for lineno, p in offending_paths(text):
            (historical if is_record else live).append(Finding(rel, lineno, p))
    return live, historical, unread, examined


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".")
    try:
        args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit:
        return 3
    root = Path(args.root)
    if not root.is_dir():
        print(f"[{NAME}] BAD INVOCATION — {args.root!r} is not a directory.",
              file=sys.stderr)
        return 3
    try:
        live, historical, unread, examined = audit(root)
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the scan itself failed: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    for f in live:
        print(str(f))
    for u in unread:
        print(f"NOT CHECKED — {u}", file=sys.stderr)
    # The exclusion states its own size, so a PASS bought by it is legible.
    print(f"examined {examined} live analysis script(s) under {str(root)!r}; "
          f"{len(historical)} run-directory path(s) in published records "
          f"disclosed and not counted as findings")
    if examined == 0:
        print(f"[{NAME}] NOT CHECKED — no live analysis script was found.",
              file=sys.stderr)
        return 2
    if live:
        print(f"[{NAME}] FAIL — an emitted script names a run directory")
        return 1
    if unread:
        print(f"[{NAME}] NOT CHECKED — a script could not be read")
        return 2
    print(f"[{NAME}] PASS — every live emitted script is project-relative")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
