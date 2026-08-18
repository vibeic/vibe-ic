#!/usr/bin/env python3
"""stated_count_drift_check.py — a count stated in prose must equal the
generated inventory it claims to report.

THIS GATE BLOCKS (rc=1) when a README states a number that the generated
inventory does not agree with, and it names the file and line that stated it.

WHY THIS GATE EXISTS
--------------------
The plugin ships three generated inventories — `PROGRAM_INVENTORY.json`,
`SKILL_INVENTORY.json`, `MCP_TOOL_INVENTORY.json` — and each already has a
drift guard proving the ARTEFACT matches the TREE. None of them proved that the
prose a reader actually sees matches the artefact. So the tool count stayed
right (it had been re-typed from a generated number) while the program count
drifted for a month without a single check going red: measured at 397b3f25f on
2026-08-19, the two READMEs stated 917 deterministic programs against 1178
files matching the glob they cited, and 3,737 against 3817 — the second one
labelled "programs" while walking the test suite as well.

An inventory nobody quotes from is not a source of truth; it is a second
opinion. This gate is what makes the artefact load-bearing.

WHAT IT CHECKS
--------------
A registry of SITES, each one (file, inventory key, pattern, occurrences):

  1. every match of that pattern must state exactly the inventory's number for
     that key — otherwise `stated-drift`, reported with file:line, the stated
     value and the generated one;
  2. the number of matches must equal the declared `occurrences` — otherwise
     `site-count`.

Clause 2 is what stops this gate failing OPEN. A pattern anchored on prose
stops matching the moment somebody rewords the sentence around it, and a
scanner that then reports "0 mismatches, PASS" is worse than no scanner: it
certifies exactly the state it can no longer see. Declaring the expected number
of statements makes a reword a FAILURE that says so, and makes adding a new
uncounted claim a failure too.

THE ANCHOR IS A CONVENTION, AND IT IS THE POINT
------------------------------------------------
Each key's pattern anchors on the words that say WHICH count is meant —
"top-level", "catalogued", "checker-shaped", "test_*.py", "skills", "tools".
`programs/*.py` and `*_check.py` are both true answers to "how many programs?"
and they differ by more than a factor of two; a bare integer in prose does not
say which question it answered, which is why nobody could tell 917 was wrong.
Prose that quotes a count is expected to carry its anchor, so this gate can
find it and so a reader can tell what they are holding.

WHAT THIS GATE DOES NOT DO
--------------------------
It does not scan for unregistered claims in files outside the registry — it
cannot tell a live claim ("there are N programs") from a pinned record of a
past measurement ("measured 917 at 73d1efb20"), and re-deriving the second
would destroy the evidence that makes a past decision reviewable. Registration
is the human judgement that a sentence is the first kind. That boundary is
stated here rather than left as a silent gap.

`--fix` RE-TYPES THE PROSE FROM THE INVENTORY, AND WHY THAT IS NOT A LOOPHOLE
-----------------------------------------------------------------------------
These counts move on every PR that adds a program, exactly as `programs/INDEX.md`
does, and this repo already ruled on that shape (vibe-ic#1382): re-derive at
LAND, do not ask each author to re-type tree-wide counters that every branch
touches. `--fix` is that mechanical re-derivation — it rewrites a registered
number to the generated one and nothing else.

It CANNOT fix a `site-count` finding, and does not try. A sentence that no
longer carries its anchor, or a new claim nobody registered, is a judgement
about prose; `--fix` reports it and still exits 1.

Usage:
  python3 programs/stated_count_drift_check.py           # rc 0 clean / 1 drift
  python3 programs/stated_count_drift_check.py --root R  # check the tree at R
  python3 programs/stated_count_drift_check.py --fix     # re-type from the inventory
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"
MARKETPLACE_README = "vibe-ic-marketplace/README.md"
PLUGIN_README = f"{PLUGIN_REL}/README.md"

PROGRAM_INVENTORY = f"{PLUGIN_REL}/PROGRAM_INVENTORY.json"
SKILL_INVENTORY = f"{PLUGIN_REL}/SKILL_INVENTORY.json"
MCP_TOOL_INVENTORY = f"{PLUGIN_REL}/mcp-eda/MCP_TOOL_INVENTORY.json"

#: `**1180**` / `1,180` / `1180` immediately before the anchor words.
_N = r"(?P<n>\d[\d,]*)\*{0,2}\s+"

PATTERNS = {
    # up to two qualifier words ("top-level Python programs", "top-level
    # deterministic programs") — the anchor is "top-level", the noun closes it.
    "programs_top_level": _N + r"top-level(?:\s+[\w-]+){0,2}\s+(?:modules|programs|`?\*?\.py`?)",
    "programs_catalogued": _N + r"(?:of them\s+)?catalogued\b",
    "checkers_top_level": _N + r"checker-shaped\b",
    "py_files_recursive": _N + r"`?\.py`?\s+files\b",
    "test_files": _N + r"`test_\*\.py`",
    "mcp_test_files": _N + r"under\s+`[^`\n]*mcp-eda/test",
    "skills": _N + r"skills\b",
    "mcp_tools": _N + r"(?:[\w/-]+\s+)?tools\b",
}


@dataclass(frozen=True)
class Site:
    """One registered family of count statements in one file."""
    path: str
    key: str
    occurrences: int


#: THE REGISTRY. `occurrences` is measured, not guessed — run this program
#: after editing the prose and it will tell you what it found.
SITES: tuple[Site, ...] = (
    Site(MARKETPLACE_README, "programs_top_level", 6),
    Site(MARKETPLACE_README, "programs_catalogued", 2),
    Site(MARKETPLACE_README, "checkers_top_level", 1),
    Site(MARKETPLACE_README, "py_files_recursive", 1),
    Site(MARKETPLACE_README, "test_files", 2),
    Site(MARKETPLACE_README, "mcp_test_files", 1),
    Site(MARKETPLACE_README, "skills", 2),
    Site(MARKETPLACE_README, "mcp_tools", 4),
    Site(PLUGIN_README, "programs_top_level", 5),
    Site(PLUGIN_README, "programs_catalogued", 2),
    Site(PLUGIN_README, "test_files", 3),
    Site(PLUGIN_README, "mcp_test_files", 1),
    # 3, not 4: the L1/L2/L3 coverage sentence is a PINNED measurement ("at
    # <sha> on <date>"), and re-deriving it would destroy the record. That is
    # the same boundary `derived_corpus_figure_check` draws, applied here.
    Site(PLUGIN_README, "skills", 3),
)


class Unmeasurable(RuntimeError):
    """An input this gate needs is absent or unreadable.

    Raised, never swallowed. A gate that cannot read its authority has NOT
    checked anything, and reporting that as a pass is the failure mode every
    other clause here exists to prevent.
    """


def load_inventory(root: Path) -> dict[str, int]:
    """The generated numbers, merged from the three inventory artefacts."""
    out: dict[str, int] = {}

    prog = root / PROGRAM_INVENTORY
    if not prog.is_file():
        raise Unmeasurable(
            f"{PROGRAM_INVENTORY} missing — run "
            f"`python3 programs/gen_program_inventory.py`")
    counts = json.loads(prog.read_text()).get("counts")
    if not isinstance(counts, dict) or not counts:
        raise Unmeasurable(f"{PROGRAM_INVENTORY} carries no `counts` block")
    out.update({k: int(v) for k, v in counts.items()})

    for rel, key in ((SKILL_INVENTORY, "skills"), (MCP_TOOL_INVENTORY, "mcp_tools")):
        p = root / rel
        if not p.is_file():
            raise Unmeasurable(f"{rel} missing")
        total = json.loads(p.read_text()).get("total")
        if not isinstance(total, int):
            raise Unmeasurable(f"{rel} carries no integer `total`")
        out[key] = total

    return out


@dataclass(frozen=True)
class Finding:
    kind: str          # "stated-drift" | "site-count"
    path: str
    line: int          # 0 when the finding is about the file as a whole
    key: str
    stated: str
    expected: str

    def render(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return (f"[{self.kind}] {where} — {self.key}: "
                f"states {self.stated}, generated inventory says {self.expected}")


def scan(root: Path,
         inventory: dict[str, int],
         sites: tuple[Site, ...] = SITES) -> list[Finding]:
    findings: list[Finding] = []
    for site in sites:
        if site.key not in inventory:
            raise Unmeasurable(
                f"site {site.path} names key `{site.key}`, which no inventory "
                f"provides")
        f = root / site.path
        if not f.is_file():
            raise Unmeasurable(f"registered file {site.path} is absent")
        text = f.read_text(errors="replace")
        expected = inventory[site.key]
        matches = list(re.finditer(PATTERNS[site.key], text))
        for m in matches:
            stated = int(m.group("n").replace(",", ""))
            if stated != expected:
                line = text.count("\n", 0, m.start()) + 1
                findings.append(Finding("stated-drift", site.path, line,
                                        site.key, str(stated), str(expected)))
        if len(matches) != site.occurrences:
            findings.append(Finding(
                "site-count", site.path, 0, site.key,
                f"{len(matches)} statement(s)",
                f"{site.occurrences} registered — a reworded sentence this "
                f"gate can no longer see, or a new claim to register in "
                f"programs/stated_count_drift_check.py"))
    return findings


def fix(root: Path,
        inventory: dict[str, int],
        sites: tuple[Site, ...] = SITES) -> list[str]:
    """Re-type every registered number from the inventory. Returns the
    repo-relative paths actually rewritten (empty when nothing drifted).

    Matches are rewritten LAST-FIRST so an earlier replacement cannot shift the
    offsets of a later one — the classic off-by-N that silently corrupts the
    second edit in a file.
    """
    rewritten: list[str] = []
    by_path: dict[str, list[Site]] = {}
    for s in sites:
        by_path.setdefault(s.path, []).append(s)

    for path, path_sites in by_path.items():
        f = root / path
        if not f.is_file():
            raise Unmeasurable(f"registered file {path} is absent")
        text = original = f.read_text(errors="replace")
        edits: list[tuple[int, int, str]] = []
        for site in path_sites:
            expected = str(inventory[site.key])
            for m in re.finditer(PATTERNS[site.key], text):
                if m.group("n").replace(",", "") != expected:
                    edits.append((m.start("n"), m.end("n"), expected))
        for start, end, value in sorted(edits, reverse=True):
            text = text[:start] + value + text[end:]
        if text != original:
            f.write_text(text)
            rewritten.append(path)
    return sorted(rewritten)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None,
                    help="repo root to check (default: this checkout)")
    ap.add_argument("--fix", action="store_true",
                    help="re-type every registered number from the generated "
                         "inventory; still exits 1 on a finding --fix cannot "
                         "make (a reworded or unregistered claim)")
    a = ap.parse_args()
    root = Path(a.root).resolve() if a.root else Path(__file__).resolve().parents[4]

    try:
        inventory = load_inventory(root)
        if a.fix:
            for rel in fix(root, inventory):
                print(f"FIXED {rel}")
        findings = scan(root, inventory)
    except Unmeasurable as e:
        print(f"[FAIL] stated_count_drift_check: NOT CHECKED — {e}")
        return 1

    print(f"stated_count_drift_check: {len(SITES)} registered site(s) over "
          f"{len({s.path for s in SITES})} file(s); inventory {inventory}")
    if findings:
        for f in findings:
            print(f.render())
        print(f"[FAIL] {len(findings)} stated count(s) drifted from the "
              f"generated inventory. Regenerate with "
              f"`python3 programs/gen_program_inventory.py` and re-type the "
              f"prose from `counts`, never by hand.")
        return 1
    print("[PASS] every registered stated count matches its generated inventory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
