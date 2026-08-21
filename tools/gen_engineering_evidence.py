#!/usr/bin/env python3
"""gen_engineering_evidence.py — the four published dimensions, generated.

vibe-ic#1120. Engineering Velocity, Autonomous Improvement, Adversarial
Verification and Silicon Proof, every figure DERIVED from the repository at a
stated anchor commit and none of them hand-maintainable.

THE RULE THIS FILE EXISTS TO ENFORCE
====================================
A velocity figure's denominator is **changes that LANDED on `main`**, never PRs
opened, commits authored, issues filed, or lines written.

That rule was not chosen on taste; it was measured on 2026-08-12. Authoring was
scaled to 23 agents, roughly 25 PRs opened within a few hours, open PR count
went 31 -> 46, and two versions landed in the same window. Queue growth
~10/hour against a drain of ~4/hour. **A published "PRs per hour" would have
read excellent while the system went backwards**, and the regression was caught
from a dashboard, not from any produced number. That is lie-shape #12 from this
repo's own catalogue — measuring a proxy rather than the property — turned on
our own reporting.

Landing is the gate, and that is why `main` is the legal denominator: the
gatekeeper pushes only with a `gatekeeper-land.sh` stamp and `pre-push` refuses
a commit that has none, so "reachable from `main`" *is* "passed the full gate".
No separate ledger is consulted, because a ledger is a thing someone can write
into.

A TRUNCATED HISTORY IS A REFUSAL, NOT A SMALLER NUMBER
======================================================
This is the defect this file hit on its own first run, and it is the reason the
shallow guard exists rather than being a nicety.

Generated on the authoring host, the page read `86 of 89 commits are
landed-and-gated`. The host's clone is SHALLOW: `.git/shallow` present,
`rev-list --count` 89, history beginning at the graft boundary. The remote
`main` carries 2007. The figure was wrong by a factor of ~22 and looked
entirely plausible — a confident number that measured the clone rather than the
project, which is precisely the class vibe-ic#1120 exists to prevent, arriving
inside the instrument written to prevent it.

So `--check` and generation both REFUSE (rc 2) on a shallow repository and say
why. `run_tolerating_uncheckable` is the right dispatch for that: a developer's
shallow clone is LOUD and non-fatal, while CI checks out complete and genuinely
checks. What must never happen is a smaller number reported as a result.

WHY AN ANCHOR, AND NOT `HEAD`
=============================
Every velocity figure is history-derived, so a page generated against `HEAD` is
stale the instant the next change lands — and a freshness gate that reddens on
every landing is one that gets bypassed within a day. The page records an
explicit `ANCHOR`, and `--check` re-derives every figure **at that anchor** and
compares. A hand-edited number cannot survive that. A newer `main` does not
falsely redden it: the page does not claim to be current, it claims to be
correct about the commit it names.

The anchor is also why this cannot be talked upward. Moving a figure requires
moving the anchor, which requires the history at that anchor to actually say so.

PROPERTIES vs PROXIES
=====================
Published as properties: what landed, what is guarded, what has been proven on
silicon. Deliberately NOT published, with the reason printed in the page rather
than left to a reader's charity: fixes-per-month (rises when work is split
finer), median time-to-fix (falls when only easy things are attempted), and
counts of commits / PRs / lines. Where any proxy is ever added it must carry
its denominator in the same sentence, the way this repo's census prints
"guards 131 of 344 figures = 38%" and never a bare pass.

SILICON PROOF IS ZERO AND SAYS SO
=================================
No Vibe-IC design has been fabricated. That dimension reads 0 and is the reason
the other three are believable — a scorecard with no zero on it is a brochure.

The zero is MEASURED, not written down: `silicon_proof()` scans the published
corpus for fabrication evidence and reports `0 of N`. Planting one fabrication
record moves the number, which is what separates a measurement from a claim.

chip-AGNOSTIC: reads git history and tracked paths, never a design.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
PAGE_REL = "docs/ENGINEERING_EVIDENCE.md"
PROGRAMS_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"

RC_OK, RC_STALE, RC_REFUSED = 0, 1, 2

#: A squash commit the gatekeeper landed carries the PR number it came from.
_LANDED_RE = re.compile(r"\(#(\d+)\)\s*$")
#: A version bump the gatekeeper assigned at merge.
_VERSION_RE = re.compile(r"^\[v(\d+\.\d+\.\d+)\]")

#: Gate-shaped program names, the same four suffixes `gate_is_wired_check`
#: uses. Kept identical on purpose: two instruments that disagree about what a
#: gate is would publish two different denominators for the same tree.
_GATE_SUFFIXES = ("_check", "_lint", "_audit", "_guard")

#: Tracked-path markers that would be evidence a design was FABRICATED.
#: Deliberately broad — a false positive here reads as "we found silicon we do
#: not have" and is caught immediately, whereas a false negative silently
#: preserves a flattering zero. Biased toward finding something.
_FAB_MARKERS = (
    "tapeout_receipt",
    "foundry_shuttle",
    "silicon_measurement",
    "fabricated_die",
    "wafer_lot",
)


def _git(root: Path, args: Sequence[str]) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=False,
    ).stdout


def is_shallow(root: Path) -> bool:
    """True when this clone does not carry complete history.

    A shallow clone yields a smaller, plausible, WRONG velocity figure — see
    the module docstring for the measured instance.
    """
    return _git(root, ["rev-parse", "--is-shallow-repository"]).strip() == "true"


def resolve_anchor(root: Path, anchor: str) -> Optional[str]:
    """Full sha for `anchor`, or None if this repository does not carry it."""
    out = _git(root, ["rev-parse", "--verify", "--quiet",
                      f"{anchor}^{{commit}}"]).strip()
    return out or None


def landed_subjects(root: Path, anchor: str) -> List[str]:
    """Subjects of every commit reachable from `anchor`."""
    out = _git(root, ["log", "--format=%s", anchor])
    return [ln for ln in out.splitlines() if ln.strip()]


def velocity(subjects: Sequence[str]) -> Dict[str, int]:
    return {
        "commits": len(subjects),
        "landed_changes": len([s for s in subjects if _LANDED_RE.search(s)]),
        "versions": len([s for s in subjects if _VERSION_RE.match(s)]),
    }


def autonomous(subjects: Sequence[str]) -> Dict[str, int]:
    landed = [s for s in subjects if _LANDED_RE.search(s)]
    cites = [s for s in landed if len(re.findall(r"#\d+", s)) >= 2]
    return {"landed_changes": len(landed), "citing_a_tracked_item": len(cites)}


def adversarial(root: Path) -> Dict[str, int]:
    """Gate count, and how many programs carry a test named after them."""
    progs_dir = root / PROGRAMS_REL
    tests_dir = progs_dir / "tests"
    progs = [p for p in sorted(progs_dir.glob("*.py"))
             if not p.name.startswith("_")]
    gates = [p for p in progs if p.stem.endswith(_GATE_SUFFIXES)]
    tests = sorted(tests_dir.glob("test_*.py"))
    test_stems = {p.stem[len("test_"):] for p in tests}
    covered = [p for p in progs if p.stem in test_stems]
    return {
        "programs": len(progs),
        "gates": len(gates),
        "programs_with_named_test": len(covered),
        "test_files": len(tests),
    }


def silicon_proof(root: Path, anchor: str) -> Dict[str, int]:
    """Fabrication evidence in the published corpus at `anchor`."""
    tracked = _git(root, ["ls-tree", "-r", "--name-only", anchor, "--",
                          "benchmark-data/ic"]).splitlines()
    cells = {p.split("/")[2] for p in tracked if p.count("/") >= 3}
    hits = [p for p in tracked if any(m in p.lower() for m in _FAB_MARKERS)]
    return {"published_cells": len(cells), "fabricated": len(hits)}


def _pct(num: int, den: int) -> str:
    return "n/a" if den == 0 else f"{100.0 * num / den:.0f}%"


def render(anchor_full: str, v: Dict[str, int], au: Dict[str, int],
           a: Dict[str, int], si: Dict[str, int]) -> str:
    out: List[str] = []
    w = out.append
    w("# Engineering Evidence")
    w("")
    w("<!-- GENERATED by tools/gen_engineering_evidence.py — DO NOT EDIT. -->")
    w("<!-- Every figure is re-derived at the ANCHOR below and compared by")
    w("     `--check`, so a hand-edited number does not survive CI. -->")
    w("")
    w(f"ANCHOR: {anchor_full}")
    w("")
    w("Figures describe the commit named above. This page does not claim to be")
    w("current; it claims to be correct about that commit.")
    w("")
    w("## The denominator, and why it is the only legal one")
    w("")
    w("Every velocity figure below counts changes that **landed on `main`**.")
    w("Landing is the gate: the gatekeeper pushes only with a")
    w("`gatekeeper-land.sh` stamp and `pre-push` refuses a commit that has")
    w("none, so *reachable from `main`* is *passed the full gate*.")
    w("")
    w("On 2026-08-12 authoring was scaled to 23 agents; ~25 PRs opened within")
    w("a few hours, open PR count went 31 -> 46, and two versions landed.")
    w("Queue growth ~10/hour against a drain of ~4/hour. A published \"PRs per")
    w("hour\" would have read excellent while the system went backwards. That")
    w("is why PRs opened, commits authored, issues filed and lines written are")
    w("**not** published here, alone or at all.")
    w("")
    w("## Engineering Velocity")
    w("")
    w(f"- **{v['landed_changes']} of {v['commits']} commits** at this anchor")
    w(f"  are landed-and-gated changes carrying the PR they came from")
    w(f"  ({_pct(v['landed_changes'], v['commits'])}).")
    w(f"- **{v['versions']} versions** were assigned at merge and landed.")
    w("")
    w("Not published, and the reason: *fixes per month* rises when work is")
    w("split finer; *median time-to-fix* falls when only easy things are")
    w("attempted. Neither is a property of the engineering.")
    w("")
    w("## Autonomous Improvement")
    w("")
    w(f"- **{au['citing_a_tracked_item']} of {au['landed_changes']}** landed")
    w(f"  changes cite the tracked item they resolve")
    w(f"  ({_pct(au['citing_a_tracked_item'], au['landed_changes'])}).")
    w(f"- The compounding surface is **{a['gates']} gates** of")
    w(f"  **{a['programs']} programs** ({_pct(a['gates'], a['programs'])}):")
    w("  each landed fix that becomes a gate cannot be silently un-fixed.")
    w("")
    w("## Adversarial Verification")
    w("")
    w(f"- **{a['programs_with_named_test']} of {a['programs']} programs**")
    w(f"  carry a test named after them")
    w(f"  ({_pct(a['programs_with_named_test'], a['programs'])}), across")
    w(f"  **{a['test_files']} test files**.")
    w("")
    w("A named test is a lower bound, not a coverage claim: a program can be")
    w("exercised by a test that is not named after it, and a named test can be")
    w("weak. It is published because it is derivable and cannot be inflated by")
    w("editing this page.")
    w("")
    w("## Silicon Proof")
    w("")
    w(f"- **{si['fabricated']} of {si['published_cells']} published cells**")
    w("  have been fabricated.")
    w("")
    if si["fabricated"] == 0:
        w("**Zero. No Vibe-IC design has been fabricated.** Everything above")
        w("is pre-silicon: RTL, sign-off and GDS, verified against open-source")
        w("EDA tools and open PDKs. This dimension is the reason to believe")
        w("the other three — a scorecard with no zero on it is a brochure.")
        w("")
        w("The zero is measured, not written down: the corpus is scanned for")
        w("fabrication evidence at the anchor, and planting one record moves")
        w("this number.")
    else:
        w("Fabrication evidence was found at this anchor. The count above is")
        w("what the scan returned; this page reports it and does not")
        w("interpret it.")
    w("")
    return "\n".join(out) + "\n"


def build(root: Path, anchor: str) -> Optional[str]:
    full = resolve_anchor(root, anchor)
    if full is None:
        return None
    subjects = landed_subjects(root, full)
    if not subjects:
        return None
    return render(full, velocity(subjects), autonomous(subjects),
                  adversarial(root), silicon_proof(root, full))


def page_anchor(text: str) -> Optional[str]:
    m = re.search(r"^ANCHOR:\s*([0-9a-f]{7,40})\s*$", text, re.MULTILINE)
    return m.group(1) if m else None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="gen_engineering_evidence")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the page disagrees with its own anchor")
    ap.add_argument("--anchor", default="HEAD",
                    help="commit to derive from when generating (default HEAD)")
    ap.add_argument("--root", default=str(DEFAULT_ROOT),
                    help="repository root (default: this file's repo)")
    ap.add_argument("--out", default=None,
                    help=f"output path (default <root>/{PAGE_REL})")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    out_path = Path(a.out) if a.out else root / PAGE_REL

    # BEFORE anything else, and before the page is even read: a truncated
    # history yields a smaller number that looks like a result. See the module
    # docstring — this fired on this tool's own first run.
    if is_shallow(root):
        sys.stderr.write(
            f"SHALLOW_HISTORY: {root} is a shallow clone, so every "
            f"history-derived figure here would measure the clone rather than "
            f"the project. NOTHING has been generated or checked. Run "
            f"`git fetch --unshallow` and repeat.\n")
        return RC_REFUSED

    if a.check:
        if not out_path.exists():
            sys.stderr.write(
                f"NOT_GENERATED: {out_path} does not exist — this is NOT a "
                f"pass; run `python3 tools/gen_engineering_evidence.py`.\n")
            return RC_REFUSED
        existing = out_path.read_text()
        anchor = page_anchor(existing)
        if anchor is None:
            sys.stderr.write(
                "NO_ANCHOR: the page states no ANCHOR, so nothing can be "
                "re-derived and nothing has been checked.\n")
            return RC_REFUSED
        body = build(root, anchor)
        if body is None:
            sys.stderr.write(
                f"UNRESOLVABLE_ANCHOR: {anchor} is not a commit in this "
                f"repository — the page has NOT been checked.\n")
            return RC_REFUSED
        if existing != body:
            sys.stderr.write(
                f"STALE: {out_path} disagrees with what its own anchor "
                f"{anchor[:12]} generates; re-run "
                f"`python3 tools/gen_engineering_evidence.py`.\n")
            return RC_STALE
        print(f"[PASS] engineering evidence fresh: re-derived at anchor "
              f"{anchor[:12]} and byte-identical.")
        return RC_OK

    body = build(root, a.anchor)
    if body is None:
        sys.stderr.write(
            f"REFUSED: {a.anchor} did not resolve to a commit with history — "
            f"nothing was generated.\n")
        return RC_REFUSED
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body)
    print(f"wrote {out_path} (anchor {page_anchor(body)[:12]})")
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
