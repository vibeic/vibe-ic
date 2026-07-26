#!/usr/bin/env python3
"""evidence_citation_resolves_check.py — a cited evidence artifact must EXIST.

THIS GATE BLOCKS (rc=1) on any NEW dangling citation.

WHY THIS GATE EXISTS
--------------------
An evidence document that says "see `foo.log`" and ships no `foo.log` is
unverifiable, and the failure is SILENT: the sentence reads exactly the same
whether the artifact is there or not. Nothing in the flow ever opened the
file, so nothing ever noticed.

MEASURED (#361, 2026-07-26). Over ALL of `benchmark-data/`, counting `.log`
only: 39 cited, 27 unresolvable against ANY base — 69%. Over this gate's own
DEFAULT SCOPE (`benchmark-data/ic`, `.log` + `.rpt`): 110 cited, 65
unresolvable. The root cause is not author carelessness: `.gitignore` ignores
`*.log` repo-wide, so committing a proof log requires `git add -f` and the
22 logs that ARE tracked all got in that way. The structural hole and the
absent gate together made "claims a proof, ships no artifact" the default
outcome rather than a mistake — it was found by hitting it twice in one
review (a PR fixing exactly that defect reproduced it one level down).

WHAT IT CHECKS
--------------
Every backticked citation in a Markdown file whose token looks like an
artifact filename with an evidence-bearing extension must RESOLVE to a file
on disk. Resolution walks a ladder of bases — the citing document's own
directory, then each ancestor up to the scan root — because citations in
this tree are written relative to either the document or the IC root.

    MEASUREMENT NOTE, stated because getting it wrong is the same class of
    error this gate exists to catch: a single-base resolver (document
    directory only) reports 35 unresolvable instead of 27. It counts every
    IC-root-relative citation as dangling. The ladder is not a convenience;
    without it the gate would fabricate findings.

BASELINE, AND WHY IT MAY ONLY SHRINK
------------------------------------
65 dangling citations already exist in the default scope. Failing the tree
on all of them would
make the gate un-landable and it would be disabled, which is how a gate ends
up reporting FAIL while blocking nothing. So the known set is recorded in a
baseline file and this gate FAILs on:

  * any citation NOT in the baseline that does not resolve — a NEW hole; and
  * a baseline that has GROWN, or that lists entries which now resolve —
    both mean the baseline was edited to accommodate a regression instead of
    the regression being fixed. The baseline is a debt register, not a
    waiver list: it may only shrink.

Regenerate it deliberately with `--write-baseline` (and only ever to a
SMALLER set — the gate re-checks that on the next run).

chip-AGNOSTIC: pure Markdown/filesystem structure. No design, PDK, vendor or
value literal appears here.

USAGE
-----
    python3 evidence_citation_resolves_check.py [ROOT] [--json OUT]
                                                [--write-baseline]

EXIT CODES
----------
    0 = PASS (every citation resolves, or the unresolved set is within a
        baseline that has not grown)
    1 = FAIL (a new dangling citation, or the baseline grew / went stale)
    2 = SKIP (no scan root — nothing to check)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Extensions that carry sign-off EVIDENCE. Deliberately narrow: this gate
# judges "the proof you pointed at is missing", not "every path in prose".
_EVIDENCE_EXT = (".log", ".rpt", ".sby")

# A backticked token that looks like a file path. Anchored so prose in
# backticks (a command line, a sentence) is never mistaken for a citation.
_CITE_RE = re.compile(r"`([A-Za-z0-9_./+-]+)`")

# Tokens that are TEMPLATES / GLOBS, not citations of a specific artifact.
# Judging these would manufacture findings against text that never claimed a
# particular file exists.
_TEMPLATE_RE = re.compile(r"[*?]|<[^>]*>|\{[^}]*\}|\bN\b")

# The baseline lives with the DATA it describes, not in plugin source: its
# entries are benchmark-data document paths and therefore carry design names,
# which `source_chip_agnostic_check` (rightly) forbids anywhere under
# `programs/`. The program itself stays chip-AGNOSTIC; only the debt register
# names the designs whose evidence is missing.
_BASELINE_NAME = "evidence_citation_baseline.json"

# DEFAULT SCOPE — the IC sign-off trees, where a document asking a reader to
# believe a result points at the artifact that backs it.
_DEFAULT_ROOT_REL = "benchmark-data/ic"

# OUT OF SCOPE BY DEFAULT, stated here rather than left as a silent narrowing:
# `benchmark-data/evaluation/` holds PER-TASK, machine-generated run outputs
# (one summary document per benchmark item, regenerated wholesale on every
# campaign). Measured 2026-07-26: 14354 documents, 129 citations, 124
# unresolved — i.e. its reports are simply not retained, by design. Gating it
# would fail on every benchmark commit for a reason no author can act on, and
# a gate that must be bypassed to work is a gate that gets deleted. Scan it
# deliberately by passing the path; the count is disclosed on every run so
# nobody can mistake "not scanned" for "clean".
_DISCLOSED_OUT_OF_SCOPE = (
    "benchmark-data/evaluation",
    "per-task generated run outputs; reports not retained by design "
    "(measured 2026-07-26: 124 of 129 citations unresolved)")


def tracked_files(root: Path) -> Optional[set]:
    """The set of git-TRACKED paths under `root`, or None when that cannot be
    determined (not a repo / no git).

    LOAD-BEARING, and learned the hard way: the first version of this gate
    judged plain filesystem existence, so its baseline was computed from a
    working tree that also held UNTRACKED artifacts. It was green locally and
    RED in CI — 12 baseline entries "resolved" (their citing documents are
    untracked, so the citation was never produced) and 9 new dangling
    citations appeared. A gate whose verdict depends on what happens to be
    lying in the author's tree is a false certificate of exactly the kind
    this gate exists to remove.

    The question is "does the REPO ship the proof", not "does this machine
    have it" — so an untracked local artifact must NOT satisfy a citation.
    """
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                           capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out = r.stdout.decode("utf-8", "replace")
    names = [n for n in out.split("\0") if n]
    if not names:
        return None
    # LOGICAL paths, never `resolve()`. `benchmark-data/ic` carries 787
    # symlinks; resolving follows them to targets that exist on the author's
    # machine and not in a fresh checkout, which is precisely how this gate
    # enumerated 440 documents locally and 422 in CI on the SAME commit. With
    # logical relative paths the verdict is a pure function of the git index
    # and therefore identical in every environment.
    return {n for n in names}


def _is_citation(tok: str) -> bool:
    if not tok.lower().endswith(_EVIDENCE_EXT):
        return False
    if _TEMPLATE_RE.search(tok):
        return False
    return True


def resolve_citation(md: Path, cite: str, root: Path,
                     tracked: Optional[set] = None) -> Optional[Path]:
    """Resolve `cite` against the ladder: the citing document's directory,
    then each ancestor up to (and including) `root`. Returns the resolved
    path or None.

    The ladder is load-bearing — see the MEASUREMENT NOTE in the module
    docstring. A document-directory-only resolver reports ~30% more
    findings, all of them false.
    """
    _ = tracked  # membership is tested on logical paths below
    if Path(cite).is_absolute():
        # An absolute path is non-portable by construction: it can only
        # resolve on the machine that wrote it, so it substantiates nothing
        # for any other reader. Never resolvable, regardless of this host.
        return None
    import posixpath
    try:
        rel_dir = md.parent.relative_to(root).as_posix()
    except ValueError:
        return None
    if rel_dir == ".":
        rel_dir = ""
    while True:
        cand_rel = posixpath.normpath(
            posixpath.join(rel_dir, cite) if rel_dir else cite)
        if not cand_rel.startswith(".."):
            if tracked is not None:
                if cand_rel in tracked:
                    return root / cand_rel
            elif (root / cand_rel).is_file():
                return root / cand_rel
        if not rel_dir:
            return None
        rel_dir = posixpath.dirname(rel_dir)


# JSON GATE REPORTS (#366). A report that declares a `verdict` AND names the
# artifact substantiating it is making the same promise a Markdown citation
# makes, in a different container. Measured 2026-07-26 over benchmark-data/ic:
# 788 such reports, 118 artifact references, 75 unresolvable in the TRACKED
# tree — including three spm PDK cells whose `formal_evidence.json` carries
# verdict PASS with "PROOF_CHAIN_OK ... substantiated by an elaboratable .sby
# + SymbiYosys PASS transcript" while no `.sby` and no transcript exist
# anywhere in the repo.
#
# The gate that wrote those reports is NOT at fault: it verifies the paths
# before emitting PASS, and they existed on disk when it ran. The evidence
# then could not be SHIPPED — `*.sby.log` matches `.gitignore`'s repo-wide
# `*.log`, so zero are tracked. A PASS that no reader can re-verify is the
# same false certificate as a fabricated one; only the mechanism differs.
_VERDICT_KEY = "verdict"


def _json_artifact_refs(path: Path) -> List[Tuple[str, str]]:
    """[(field, cited_path)] for a JSON GATE REPORT — a dict carrying a
    `verdict`. Anything else is data, not a claim, and is not judged."""
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or _VERDICT_KEY not in data:
        return []
    out: List[Tuple[str, str]] = []
    for k, v in data.items():
        if isinstance(v, str) and _is_citation(v):
            out.append((str(k), v))
    return out


def scan(root: Path,
         tracked: Optional[set] = None) -> Tuple[List[Dict[str, str]], int, int]:
    """Return (dangling, cited_total, docs_scanned). Only TRACKED documents
    are scanned and only TRACKED artifacts satisfy a citation when `tracked`
    is available — see `tracked_files`."""
    dangling: List[Dict[str, str]] = []
    cited = 0
    docs = 0
    # ENUMERATE FROM THE TRACKED LIST, never from a filesystem walk. A
    # walk-then-filter enumerated 440 documents locally and 422 in CI on the
    # SAME commit — directory traversal is environment-dependent (symlinks,
    # traversal order, name encoding) in ways `git ls-files` is not. The
    # baseline is a set of digests, so any enumeration difference between
    # where it is WRITTEN and where it is CHECKED shows up as phantom
    # "resolved" entries. One source of truth for what exists.
    _mds = (sorted(root / t for t in tracked if t.lower().endswith(".md"))
            if tracked is not None else sorted(root.rglob("*.md")))
    for md in _mds:
        try:
            text = md.read_text(errors="replace")
        except OSError:
            continue
        docs += 1
        for tok in _CITE_RE.findall(text):
            if not _is_citation(tok):
                continue
            cited += 1
            if resolve_citation(md, tok, root, tracked) is None:
                dangling.append({
                    "doc": str(md.relative_to(root)),
                    "citation": tok,
                })
    _jsons = (sorted(root / t for t in tracked if t.lower().endswith(".json"))
              if tracked is not None else sorted(root.rglob("*.json")))
    for js in _jsons:
        refs = _json_artifact_refs(js)
        if refs:
            docs += 1
        for field, tok in refs:
            cited += 1
            if resolve_citation(js, tok, root, tracked) is None:
                dangling.append({
                    "doc": str(js.relative_to(root)),
                    "citation": f"[{field}] {tok}",
                })
    return dangling, cited, docs


def _working_tree_dirt(root: Path) -> List[str]:
    """Untracked or modified paths under `root`, as git reports them. Empty
    when the tree is clean or git is unavailable (the caller degrades)."""
    try:
        r = subprocess.run(["git", "-C", str(root), "status", "--porcelain",
                            "--", "."], capture_output=True, text=True,
                           timeout=120)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    return [ln[3:] for ln in r.stdout.splitlines() if ln.strip()]


def _key(d: Dict[str, str]) -> str:
    """Human-readable identity: `<doc>::<citation>`. Printed at RUN time,
    never written to the baseline — see `_digest`."""
    return f"{d['doc']}::{d['citation']}"


def _digest(key: str) -> str:
    """What the BASELINE stores.

    The register must not publish the paths it lists. Some benchmark-data
    directory names embed a commercial foundry product name, and a landed
    diff is permanent public content — writing the literal paths would make
    this gate a leak vector (caught by `nda_diff_scan_check` on its first
    attempt to land, exactly as intended). A digest gives the register the
    only thing it actually needs — set membership — while the offending
    paths stay fully visible to whoever RUNS the gate, printed from the live
    scan. Machine-checkable without disclosure; readable on demand."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _load_baseline(path: Path) -> Optional[List[str]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    ents = data.get("unresolved") if isinstance(data, dict) else data
    return sorted({str(e) for e in ents}) if isinstance(ents, list) else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="cited evidence artifacts must exist (#361)")
    ap.add_argument("root", nargs="?", default=None)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the CURRENT unresolved set; it may only "
                         "ever shrink from there")
    ap.add_argument("--scope-expanded", metavar="REASON",
                    help="permit a GROWING baseline for this write, because "
                         "the gate now LOOKS at more than it did (a wider "
                         "scope finds pre-existing debt; that is not a "
                         "regression). Requires a reason, which is recorded "
                         "in the baseline beside the previous size — a "
                         "deliberate, auditable act, never a bypass flag.")
    args = ap.parse_args(argv)

    here = Path(__file__).resolve()
    explicit_root = bool(args.root)
    if args.root:
        root = Path(args.root)
    else:
        root = next((b / _DEFAULT_ROOT_REL for b in here.parents
                     if (b / _DEFAULT_ROOT_REL).is_dir()), None)
    if root is None or not root.is_dir():
        print("[SKIP] evidence_citation_resolves_check: no scan root "
              f"({args.root or _DEFAULT_ROOT_REL} not found).")
        return 2

    baseline_path = (Path(args.baseline) if args.baseline
                     else root.parent / _BASELINE_NAME)
    tracked = tracked_files(root)
    dangling, cited, docs = scan(root, tracked)
    now = sorted({_key(d) for d in dangling})

    if args.write_baseline:
        # REFUSE to record a baseline from a DIRTY tree. This is not caution,
        # it is the bug that shipped: the first baseline was generated from a
        # working tree holding untracked artifacts, so it was green locally
        # and RED in CI (12 entries "resolved", 9 new dangling). A debt
        # register describing the author's laptop is worse than none.
        if args.scope_expanded is not None and len(
                args.scope_expanded.strip()) < 30:
            print("[FAIL] --scope-expanded needs a real reason (>=30 chars) "
                  "naming what the gate now looks at that it did not before.")
            return 1
        dirty = _working_tree_dirt(root)
        if dirty:
            print(f"[FAIL] refusing to write a baseline from a DIRTY tree — "
                  f"{len(dirty)} untracked/modified path(s) under {root} "
                  f"would change what resolves. Generate it from a clean "
                  f"checkout (e.g. `git worktree add --detach <tmp> HEAD`).")
            for d in dirty[:5]:
                print(f"   {d}")
            return 1
        prev = _load_baseline(baseline_path) or []
        if prev and len(now) > len(prev) and args.scope_expanded is None:
            print(f"[FAIL] refusing to GROW the baseline "
                  f"({len(prev)} -> {len(now)}). The baseline is a debt "
                  f"register, not a waiver list. If the gate now LOOKS at "
                  f"more than it did, say so with --scope-expanded '<why>' "
                  f"— a wider scope finding pre-existing debt is not a "
                  f"regression, but it must be recorded, not assumed.")
            return 1
        baseline_path.write_text(json.dumps(
            {"_comment": ("Known-unresolved evidence citations (#361). MAY "
                          "ONLY SHRINK. Entries are sha256-32 digests of "
                          "'<doc>::<citation>' — the paths themselves are "
                          "NOT stored (some embed a commercial foundry "
                          "product name and a landed diff is permanent "
                          "public content). Run the gate to see them."),
             "unresolved": sorted(_digest(k) for k in now),
             **({"scope_expansion": {
                 "previous_size": len(prev),
                 "reason": args.scope_expanded.strip()}}
                if args.scope_expanded is not None and len(now) > len(prev)
                else {})}, indent=2)
            + "\n")
        print(f"wrote {baseline_path} ({len(now)} entr(ies))")
        return 0

    base = _load_baseline(baseline_path)
    now_dig = {_digest(k): k for k in now}
    findings: List[str] = []
    if base is None:
        findings = list(now)
        stale: List[str] = []
    else:
        findings = [k for k in now if _digest(k) not in set(base)]
        # entries the baseline claims are broken but that now resolve: the
        # debt was paid and the register must be updated, else the register
        # slowly turns into permission.
        stale = [d for d in base if d not in now_dig]

    result = {
        "program": "evidence_citation_resolves_check",
        "docs_scanned": docs,
        "citations_checked": cited,
        "unresolved_total": len(now),
        "baseline_size": (len(base) if base is not None else None),
        "new_dangling": findings,
        "stale_baseline_entries": stale,
        "passed": not findings and not stale,
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2) + "\n")

    print(f"evidence_citation_resolves_check: {docs} doc(s), "
          f"{cited} citation(s) checked under {root}")
    if not explicit_root:
        print(f"  NOT scanned    : {_DISCLOSED_OUT_OF_SCOPE[0]} — "
              f"{_DISCLOSED_OUT_OF_SCOPE[1]}")
    if tracked is None:
        print("  WARNING        : git-tracked file set unavailable — falling "
              "back to plain filesystem existence. An UNTRACKED local "
              "artifact can satisfy a citation here, so this run is weaker "
              "than CI's and its baseline must not be committed.")
    print(f"  unresolved now : {len(now)}"
          + (f"   baseline: {len(base)}" if base is not None else
             "   (no baseline recorded)"))
    if stale:
        print(f"[FAIL] {len(stale)} baseline entr(ies) now RESOLVE — the "
              f"debt was paid; shrink the baseline so it cannot become a "
              f"standing waiver:")
        for d in stale[:10]:
            print(f"   (resolved) digest {d}")
    if findings:
        print(f"[FAIL] {len(findings)} NEW dangling evidence citation(s) — "
              f"the document points at a proof it does not ship:")
        for k in findings[:20]:
            print(f"   {k}")
        if len(findings) > 20:
            print(f"   ... and {len(findings) - 20} more (not truncated "
                  f"silently — this line is the disclosure)")
    if not findings and not stale:
        print(f"[PASS] every cited evidence artifact resolves, or is "
              f"within a baseline that has not grown.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
