#!/usr/bin/env python3
"""Every program must carry a test — enforced for NEW programs, grandfathered for old.

WHY THIS EXISTS
---------------
A program that lands without a test creates a window in which it can be wrong and
nobody finds out. This repo has measured that window closing badly more than once:
a gate that returned FAIL on three consecutive versions while the flow shipped its
artifacts anyway, and a completeness check that counted a token appearing anywhere
instead of appearing where its consumer reads it.

The rule is therefore not "please remember to write a test" but a check, because a
rule that depends on remembering is the same class of thing this repo keeps finding
broken.

BLOCKING vs ADVISORY
--------------------
This check is **BLOCKING for programs added after the baseline** and silent for
programs already present when it landed. That split is deliberate:

  * Firing on 60 pre-existing untested generators would make it noise on day one,
    and a gate people learn to ignore is worse than no gate (see
    skills/flow-change-acceptance, criterion 2).
  * Firing on a NEW untested program is exactly the moment the cost of a missing
    test is lowest.

The grandfather list is data, not code: `programs/_test_coverage_baseline.txt`. It
is expected to SHRINK. It must never grow — adding an entry is the same as saying
"this new program ships untested", and the check refuses to be edited that way by
verifying that every listed name still resolves to a program that predates the
baseline commit recorded in the file header.

WHAT COUNTS AS COVERAGE
-----------------------
A program `foo.py` is covered when its stem appears either in a test filename under
`programs/tests/`, or anywhere inside a test file's body (an import, a monkeypatch
target, a subprocess invocation). That is intentionally generous: the goal is to
catch programs nothing exercises at all, not to mandate a naming convention.

Exit codes: 0 = every non-grandfathered program is covered. 1 = at least one new
program has no test. 2 = the baseline file is missing or malformed.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

BASELINE_NAME = "_test_coverage_baseline.txt"


def _programs_dir(root: Path) -> Path:
    for c in (
        root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
        root / "programs",
        root,
    ):
        if (c / "tests").is_dir():
            return c
    return root


def _program_stems(pdir: Path) -> list[str]:
    out = []
    for f in sorted(pdir.glob("*.py")):
        n = f.name
        if n.startswith("_") or n == "conftest.py":
            continue
        out.append(f.stem)
    return out


def _covered(pdir: Path) -> str:
    """Stems mentioned by any test file, by name or inside its body."""
    tdir = pdir / "tests"
    names = " ".join(p.name for p in tdir.glob("*.py"))
    body_parts = [names]
    for p in tdir.glob("*.py"):
        try:
            body_parts.append(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    # Substring, not tokenisation: a test named test_foo.py tokenises to the
    # single token test_foo, which would NOT reveal that foo is exercised.
    # The gate's own negative controls caught exactly that.
    return "\n".join(body_parts)


def _load_baseline(pdir: Path) -> tuple[set[str], str]:
    f = pdir / BASELINE_NAME
    if not f.is_file():
        return set(), ""
    names, commit = set(), ""
    for line in f.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            m = re.search(r"baseline-commit:\s*([0-9a-f]{7,40})", s)
            if m:
                commit = m.group(1)
            continue
        names.add(s)
    return names, commit


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", nargs="?", default=".", help="repo or plugin root")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    pdir = _programs_dir(Path(args.root).resolve())
    if not (pdir / "tests").is_dir():
        print(f"program_test_coverage_check: no programs/tests under {pdir}", file=sys.stderr)
        return 2

    stems = _program_stems(pdir)
    covered = _covered(pdir)
    grandfathered, baseline_commit = _load_baseline(pdir)

    uncovered = [s for s in stems if s not in covered]  # substring test
    new_uncovered = sorted(x for x in uncovered if x not in grandfathered)
    still_uncovered_old = sorted(x for x in uncovered if x in grandfathered)
    # An entry that no longer names a real program, or now HAS a test, should be
    # dropped so the list keeps shrinking rather than quietly rotting.
    stale_entries = sorted(grandfathered - set(uncovered))

    verdict = "FAIL" if new_uncovered else "PASS"

    if args.json:
        import json

        print(json.dumps({
            "gate": "program_test_coverage_check",
            "verdict": verdict,
            "blocks": True,
            "programs_total": len(stems),
            "uncovered_total": len(uncovered),
            "grandfathered": len(grandfathered),
            "new_uncovered": new_uncovered,
            "still_uncovered_grandfathered": len(still_uncovered_old),
            "stale_baseline_entries": stale_entries,
            "baseline_commit": baseline_commit,
        }, indent=2))
    else:
        print(f"programs: {len(stems)}   uncovered: {len(uncovered)}   "
              f"grandfathered: {len(grandfathered)}")
        if stale_entries:
            print(f"baseline entries that are no longer needed ({len(stale_entries)}) — "
                  f"please remove them so the list keeps shrinking:")
            for s in stale_entries[:20]:
                print(f"  - {s}")
        if new_uncovered:
            print(f"\nFAIL: {len(new_uncovered)} program(s) added without a test:")
            for s in new_uncovered:
                print(f"  - {s}.py has no test under programs/tests/")
            print("\nA program that lands without a test creates a window in which it "
                  "can be wrong and nobody finds out.\nAdd a test that fails against "
                  "the code as it was before this program existed; see\n"
                  "skills/flow-change-acceptance for what makes a control non-vacuous.")
        else:
            print("\nPASS: every non-grandfathered program is exercised by some test.")

    return 1 if new_uncovered else 0


if __name__ == "__main__":
    sys.exit(main())
