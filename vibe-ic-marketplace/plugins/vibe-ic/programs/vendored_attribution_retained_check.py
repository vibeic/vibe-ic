#!/usr/bin/env python3
"""vendored_attribution_retained_check.py — third-party source that SHIPS must
ship with the record that names where it came from. vibe-ic#1043.

THIS GATE BLOCKS (rc=1).

WHY THIS GATE EXISTS
--------------------
#1043 was filed on a licensing obligation, not an engineering preference: a
withdrawal deleted `SOURCE_MANIFEST.md` files while the Apache-2.0 RTL they
attribute stayed in the tree. Apache-2.0 §4(b)/§4(d) attach to distributing the
WORK, not to publishing a run that used it — so withdrawing a run does not
withdraw the duty, and the obligation does not travel with the evidence.

The narrower point, and the reason this is a program rather than a review note:
**nothing in this repository could tell.** The attribution records are emitted
(`source_manifest_md_emit.py`, `staged_rtl_reused_ip_manifest_emit.py`) and read
back for RTL reconciliation, but no gate ever asked whether a licensed file that
is still tracked still has one. A deletion is invisible, and so is the case
below, which nobody deleted at all — it simply never had a record.

MEASURED on `947547716` (v1.10.33) over `benchmark-data/`, before this gate:

    17216 tracked files
      525 carrying an SPDX-License-Identifier  (497 Apache-2.0, 28 ISC)
        1 UNCOVERED

and the one was not a subtlety:
`benchmark-data/ic/spm/v1.10.18_sky130A/phase2/stage2/dft/cell_model_combined.v`
— **152,616 lines** of `Copyright 2020 The SkyWater PDK Authors`, Apache-2.0,
under an IC root carrying no `SOURCE_MANIFEST` of any kind.

WHAT IT CHECKS
--------------
Every TRACKED file whose head declares `SPDX-License-Identifier: <id>` must be
covered by a `SOURCE_MANIFEST.*` in its own directory or an ancestor of it.

Only the header is read. The gate forms no view on WHICH licence obliges what —
that is a legal question and this is a structural one. A file that announces a
licence is a file somebody must be able to trace; the gate asks only whether the
tracing record is still there.

THE COVERING MANIFEST MUST BE A STRICT DESCENDANT OF THE SCAN ROOT
------------------------------------------------------------------
Otherwise one `benchmark-data/SOURCE_MANIFEST.md` would cover the entire corpus
and the gate would be satisfiable by a single file — a check that can be turned
off by adding one path is a ban wearing a checkmark.
:func:`test_a_manifest_at_the_scan_root_does_not_cover_the_world` pins it.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
* It does not read the manifest's CONTENT or check that it names this file.
  A record that exists but is wrong is a different defect and a much softer
  measurement; conflating them would let this gate report an opinion where it
  can only see structure.
* It does not judge generated files differently. `cell_model_combined.v` is a
  concatenation of PDK cell models, and it carries the upstream header because
  it carries the upstream CODE — a derivative work distributes the original.
  Exempting "generated" files would exempt exactly the case that found this.
* It does not scan untracked files. The obligation attaches to what is
  DISTRIBUTED, and the git index is what this repository distributes.

BASELINE
--------
There is none, on purpose. The corpus is clean as of the change that adds this
gate (the one finding above is closed in the same commit by the record that was
always owed), so the gate starts ARMED at zero rather than shipping with a debt
register nobody is obliged to shrink. A baseline is the right tool for debt that
cannot be paid today; this debt could be paid today.

chip-AGNOSTIC: no design, PDK, vendor or licence-id literal decides anything.
The SPDX id is read out of the file and reported; it is never compared against
a list.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

#: The declaration this gate keys on. SPDX is the machine-readable form every
#: vendored tree in this corpus already uses, which is why it is the hook: it
#: is the file's own statement about itself, not an inference from its path.
_SPDX_RE = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.\-+]+)")

#: Only the head is read. A licence header that is not in the first few KB is
#: not a header, and reading whole files would make the gate a function of
#: corpus size — this one file is 152k lines.
_HEAD_BYTES = 4096

#: The attribution record, by name. `.md` and `.json` both ship in this tree.
_MANIFEST_RE = re.compile(r"^SOURCE_MANIFEST\.")

#: Default scan scope: the published corpus, which is what this repository
#: distributes and therefore where the obligation lands.
_DEFAULT_SCOPE = "benchmark-data"


def tracked_files(repo: Path, scope: str) -> List[str]:
    """The git INDEX, never the filesystem. What is distributed is what is
    tracked; an untracked scratch copy carries no obligation and a
    filesystem walk would make the verdict depend on the author's build dir."""
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "HEAD", "--name-only", scope],
        capture_output=True, text=True)
    if out.returncode != 0:
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def manifest_dirs(paths: List[str]) -> set:
    return {str(Path(p).parent) for p in paths
            if _MANIFEST_RE.match(Path(p).name)}


def declared_licence(repo: Path, rel: str) -> Optional[str]:
    try:
        blob = (repo / rel).read_bytes()[:_HEAD_BYTES]
    except OSError:
        return None
    m = _SPDX_RE.search(blob.decode("utf-8", errors="replace"))
    return m.group(1).strip() if m else None


def covering_manifest_dir(rel: str, mdirs: set, scope: str) -> Optional[str]:
    """The nearest ancestor directory carrying a manifest, or None.

    Stops BEFORE the scan root: a manifest at `scope` itself covers nothing,
    or one file would satisfy the whole corpus.
    """
    d = Path(rel).parent
    scope_p = Path(scope)
    while True:
        if str(d) == str(scope_p) or str(d) in (".", "", "/"):
            return None
        if str(d) in mdirs:
            return str(d)
        if d.parent == d:
            return None
        d = d.parent


def scan(repo: Path, scope: str) -> Dict:
    paths = tracked_files(repo, scope)
    mdirs = manifest_dirs(paths)
    licensed: List[Tuple[str, str]] = []
    uncovered: List[Dict[str, str]] = []
    for rel in paths:
        lic = declared_licence(repo, rel)
        if lic is None:
            continue
        licensed.append((rel, lic))
        if covering_manifest_dir(rel, mdirs, scope) is None:
            uncovered.append({"path": rel, "licence": lic})
    return {
        "scope": scope,
        "tracked": len(paths),
        "manifest_dirs": sorted(mdirs),
        "licensed": len(licensed),
        "uncovered": sorted(uncovered, key=lambda d: d["path"]),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--scope", default=_DEFAULT_SCOPE)
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    res = scan(repo, args.scope)

    print(f"vendored_attribution_retained_check: {res['tracked']} tracked "
          f"file(s) under {args.scope}, {res['licensed']} declaring an SPDX "
          f"licence, {len(res['manifest_dirs'])} attribution record(s)")

    if args.json_out:
        atomic_write_text(Path(args.json_out), json.dumps(res, indent=2))

    if not res["licensed"]:
        # A scope with nothing licensed proves nothing. Say so rather than
        # printing a green that means "I looked at an empty set".
        print(f"[VACUOUS_PASS] no tracked file under {args.scope} declares an "
              f"SPDX licence, so this gate checked nothing")
        return 0

    if res["uncovered"]:
        print(f"[FAIL] {len(res['uncovered'])} tracked file(s) declare a "
              f"licence and ship with NO attribution record above them — the "
              f"code is distributed, so the record that names its origin is "
              f"owed:")
        for u in res["uncovered"][:40]:
            print(f"   [{u['licence']}] {u['path']}")
        if len(res["uncovered"]) > 40:
            print(f"   ... and {len(res['uncovered']) - 40} more")
        print("Add a SOURCE_MANIFEST.md at or above each path naming the "
              "upstream project and its licence. Deleting the file is the "
              "other lawful option; deleting only the record is not.")
        return 1

    print(f"[PASS] every one of the {res['licensed']} licence-declaring "
          f"file(s) is covered by an attribution record")
    return 0


if __name__ == "__main__":
    sys.exit(main())
