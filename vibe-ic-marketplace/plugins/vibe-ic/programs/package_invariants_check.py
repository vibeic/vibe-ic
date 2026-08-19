#!/usr/bin/env python3
"""package_invariants_check.py — every code package states its own rules, and
the statement is checked rather than believed.

THE GAP THIS CLOSES
===================
This repo is AHEAD on enforcement and BEHIND on LOCALITY. The rules are real,
adversarially tested, and centrally held: `plugin_full_audit.py` owns "every
program has a test", `gate_zero_denominator_refuses_check.py` owns "a gate may
not answer over an empty population", `single_testpath_guard.py` owns "one
declared test tree", `landing_unselectable_pytest_corpus.py` owns "these test
files reach no landing stage". A contributor standing inside `tools/ci/` or
`_shared/` can see NONE of them without knowing which of 1185 programs to open.

The measured consequence is not hypothetical. `_shared/` holds 3 test files and
283 pytest nodes that no landing stage can reach; that fact is computed by
`landing_unselectable_pytest_corpus.py` and is invisible from `_shared/` itself.

So: a file per code package, next to the code it constrains, naming the rules
that bind that package and — for each rule — the program that already enforces
it. The locality is the deliverable. The enforcement stays where it is.

WHAT A PACKAGE IS, AND WHY IT IS COMPUTED AND NOT LISTED
========================================================
A CODE PACKAGE is a directory holding at least `MIN_SOURCE_FILES` tracked
source files DIRECTLY (not in subdirectories). The population is DISCOVERED on
every run from `git ls-files`; there is no roster.

That is deliberate. `landing_unselectable_pytest_corpus.py` states the reason in
its own words: "A roster is the recorded-register defect this repo has removed
repeatedly (census / tranche baseline / skip ratchet): it goes stale silently
and in the SAFE-LOOKING direction, because fewer files still reports PASS." A
declared population of packages would rot exactly that way — drop an entry and
the gate gets greener.

Measured on this tree at the threshold below (tracked files, direct children,
extensions in `SOURCE_EXT`): 9 directories qualify, the tenth-largest holds 9.
The threshold sits in a gap, not on a slope, so it is not a dial that quietly
changes the answer:

    2637  programs/tests                  15  benchmark
    1185  programs                        10  tools/phase1_engine          (x2)
      61  tools                           10  _shared
      40  tools/ci                       ----  threshold = 10  ------------
      33  mcp-eda/test                     9  tools/phase1_engine/tests    (x2)

THE FILE
========
`INVARIANTS.yaml`, in the package directory:

    schema: 1
    package: tools/ci            # must equal the directory the file is in
    namespace: ci                # unique repo-wide; every id starts "<ns>."
    role: >-
      One paragraph. What this package is, for the human who just opened it.
    invariants:
      - id: ci.<slug>
        statement: >-
          What must be true. Prose, for a reader, not for a parser.
        enforced_by:             # >= 1 tracked path, each must exist
          - tools/ci/protected_landing_transition.py
        rule:                    # OPTIONAL: a predicate THIS gate evaluates
          kind: forbid_regex     # forbid_regex | require_regex | mirror_of
          applies_to: ["*.py", "*.sh"]
          pattern: '...'
          exempt:
            - file: install_hooks.sh
              line_matches: '...'        # forbid_regex only; narrows to a line
              because: 'why this one is not the defect'

`enforced_by` is a BINDING, not a re-implementation: the rule keeps its existing
owner and the package gains a pointer to it. `rule` is for the rules that have
no central owner, and gives the file teeth of its own.

A rule's subject is the package's DIRECT children only (a glob does not descend
into subdirectories -- `programs` and `programs/tests` are separate packages
with separate rules), and `INVARIANTS.yaml` is never its own subject: it is
metadata ABOUT the package, so a `because` sentence cannot trip the pattern it
explains, and two mirrored packages are not required to keep two declarations
byte-identical when each must name its own package and namespace.

WHAT FAILS
==========
Population, computed both ways so neither side can shrink in silence:
  P1  zero packages discovered, or git unavailable       -> rc 2, NOT DETERMINED
  P2  a discovered package has no INVARIANTS.yaml        -> FAIL
      (a missing invariant file must never read as "this package has no rules")
  P3  an INVARIANTS.yaml in a directory that is not a
      discovered package                                 -> FAIL

Conformance:
  C1  not a YAML mapping, or schema != 1                 -> FAIL
  C2  `package` != the directory the file is in          -> FAIL (a stale copy)
  C3  `role` missing or empty                            -> FAIL
  C4  `invariants` missing or empty                      -> FAIL
  C5  an invariant with no `id` or no `statement`        -> FAIL
  C6  an `id` used by two packages, or a `namespace`
      claimed by two packages                            -> FAIL (exclusive
      ownership: one rule, one owner, so a duplicate checker cannot be written
      under a name that is already taken)
  C7  an `id` not prefixed by its package's namespace    -> FAIL (attribution)
  C8  an `enforced_by` path that is not a tracked file   -> FAIL (a rule that
      names an enforcer which does not exist is a claim of protection that was
      never measured -- the shape where an unmeasured thing reads as a
      measured zero)

Local rules:
  L1  a malformed `rule` block                           -> FAIL
  L2  `applies_to` matching ZERO files                   -> FAIL (the
      empty-population defect, one directory down)
  L3  a file violating the predicate                     -> FAIL, attributed:
      `invariant violated by "<package>": <id>`
  L4  an `exempt` entry that no longer exempts anything  -> FAIL ("delete the
      entry") -- so the waiver list can only ever be shortened by a visible edit

Exit: 0 = every package conforms / 1 = a real violation / 2 = NOT DETERMINED.
rc 2 is never a pass: "I could not look" stays distinct from "I looked and
found nothing".

chip-AGNOSTIC: it reasons about repo paths, YAML structure and regular
expressions only. No design, PDK, vendor or process literal appears here or is
required to appear in any INVARIANTS.yaml.

Usage:
    python3 package_invariants_check.py [<path-inside-the-repo>] [--json <out>]
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

#: Extensions counted as SOURCE when deciding whether a directory is a package.
#: `.py`/`.sh` are what this repo is made of (4100 / 34 tracked). The JS/TS
#: entries change the answer on this tree by nothing at all -- verified: the
#: discovered set is identical with and without them -- and are present so that
#: a future sub-project in another language cannot slip under the threshold by
#: being written in a language the constant forgot.
SOURCE_EXT = frozenset({".py", ".sh", ".js", ".mjs", ".ts", ".tsx"})

#: A directory holding this many tracked source files directly is a unit
#: somebody owns. See the measured histogram in the module docstring: the
#: threshold sits in a gap between 10 and 9, not on a slope.
MIN_SOURCE_FILES = 10

FILENAME = "INVARIANTS.yaml"

_RULE_KINDS = ("forbid_regex", "require_regex", "mirror_of")


class NotDetermined(Exception):
    """Raised when the audit could not be performed at all (-> rc 2)."""


def find_repo_root(start: Path) -> Path:
    """The directory that CONTAINS `vibe-ic-marketplace`, at or above *start*.

    Same resolution rule as `programs/tests/_hostpaths.py`, restated here
    rather than imported: this program is invoked as a subprocess from the
    gates, and a sibling import that works as a script dies under
    `spec_from_file_location`.
    """
    for cand in [start] + list(start.parents):
        if (cand / "vibe-ic-marketplace").is_dir():
            return cand
    raise NotDetermined(
        f"no repository root at or above {start} (no 'vibe-ic-marketplace' "
        f"directory) -- the package population is a monorepo artefact and "
        f"cannot be computed here")


def tracked_files(repo: Path) -> list[str]:
    try:
        r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NotDetermined(f"could not run git ls-files: {exc}") from exc
    if r.returncode != 0:
        raise NotDetermined(
            f"git ls-files exited {r.returncode}: {(r.stderr or '').strip()[:200]}")
    files = [p for p in r.stdout.split("\0") if p]
    if not files:
        raise NotDetermined(f"git ls-files reported no tracked files under {repo}")
    return files


def discover_packages(tracked: list[str]) -> list[str]:
    """Directories with >= MIN_SOURCE_FILES tracked source files DIRECTLY in them."""
    counts: dict[str, int] = {}
    for rel in tracked:
        if "/" not in rel:
            continue
        if Path(rel).suffix not in SOURCE_EXT:
            continue
        counts[rel.rsplit("/", 1)[0]] = counts.get(rel.rsplit("/", 1)[0], 0) + 1
    return sorted(d for d, n in counts.items() if n >= MIN_SOURCE_FILES)


def _direct_children(tracked_set: list[str], pkg: str) -> list[str]:
    """Tracked files whose directory is EXACTLY *pkg* (no recursion)."""
    pre = pkg + "/"
    return sorted(rel for rel in tracked_set
                  if rel.startswith(pre) and "/" not in rel[len(pre):])


def _fail(findings: list, pkg: str, code: str, detail: str) -> None:
    findings.append({"package": pkg, "code": code, "detail": detail})


def _check_rule(repo: Path, pkg: str, inv_id: str, rule, tracked: list[str],
                findings: list, stats: dict) -> None:
    if not isinstance(rule, dict):
        _fail(findings, pkg, "L1", f"{inv_id}: `rule` is not a mapping")
        return
    kind = rule.get("kind")
    if kind not in _RULE_KINDS:
        _fail(findings, pkg, "L1",
              f"{inv_id}: rule.kind must be one of {list(_RULE_KINDS)}, got {kind!r}")
        return
    globs = rule.get("applies_to")
    if not isinstance(globs, list) or not globs or \
            not all(isinstance(g, str) and g for g in globs):
        _fail(findings, pkg, "L1",
              f"{inv_id}: rule.applies_to must be a non-empty list of globs")
        return

    children = _direct_children(tracked, pkg)
    names = [rel.rsplit("/", 1)[1] for rel in children]
    # The declaration is never its own subject. `INVARIANTS.yaml` is metadata
    # ABOUT the package, not package content: a rule evaluated over the file
    # that declares it would let a `because` sentence trip its own pattern, and
    # would force every mirror rule to keep two declarations byte-identical when
    # they must differ (each names its own package and namespace).
    subject = sorted({n for n in names
                      if n != FILENAME
                      and any(fnmatch.fnmatch(n, g) for g in globs)})
    if not subject:
        _fail(findings, pkg, "L2",
              f"{inv_id}: applies_to {globs} matches 0 tracked files directly in "
              f"this package -- a rule with an empty population cannot fail")
        return
    stats["rules"] += 1
    stats["files_examined"] += len(subject)

    if kind == "mirror_of":
        _check_mirror(repo, pkg, inv_id, rule, subject, tracked, findings)
        return

    pattern = rule.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        _fail(findings, pkg, "L1", f"{inv_id}: rule.pattern must be a non-empty string")
        return
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        _fail(findings, pkg, "L1", f"{inv_id}: rule.pattern is not a valid regex: {exc}")
        return

    exempt, ok = _parse_exempt(pkg, inv_id, rule, kind, findings)
    if not ok:
        return

    # Which files violate, ignoring exemptions, and which exemptions did work.
    used: set[str] = set()
    for name in subject:
        text = (repo / pkg / name).read_text(encoding="utf-8", errors="replace")
        if kind == "forbid_regex":
            hits = [(i, ln) for i, ln in enumerate(text.splitlines(), 1)
                    if rx.search(ln)]
            if not hits:
                continue
            ex = exempt.get(name)
            if ex is not None:
                lm = ex.get("_line_rx")
                if lm is None:
                    # Whole-file exemption: it did work, because there were hits.
                    used.add(name)
                    continue
                remaining = [h for h in hits if not lm.search(h[1])]
                if len(remaining) < len(hits):
                    # `used` only when the NARROWED exemption actually suppressed
                    # something. An exemption whose line_matches no longer matches
                    # any hit is stale and must be reported by L4, even though the
                    # file still violates for other reasons.
                    used.add(name)
                if not remaining:
                    continue
                hits = remaining
            for line_no, line in hits[:3]:
                _fail(findings, pkg, "L3",
                      f'invariant violated by "{pkg}": {inv_id} -- '
                      f"{pkg}/{name}:{line_no}: {line.strip()[:120]}")
        else:  # require_regex
            if rx.search(text):
                continue
            if name in exempt:
                used.add(name)
                continue
            _fail(findings, pkg, "L3",
                  f'invariant violated by "{pkg}": {inv_id} -- '
                  f"{pkg}/{name} does not match required pattern")

    for name in sorted(set(exempt) - used):
        _fail(findings, pkg, "L4",
              f"{inv_id}: exempt entry for {name} no longer exempts anything -- "
              f"delete the entry")


def _parse_exempt(pkg: str, inv_id: str, rule: dict, kind: str,
                  findings: list) -> tuple[dict, bool]:
    raw = rule.get("exempt", [])
    if not isinstance(raw, list):
        _fail(findings, pkg, "L1", f"{inv_id}: rule.exempt must be a list")
        return {}, False
    out: dict[str, dict] = {}
    for e in raw:
        if not isinstance(e, dict) or not e.get("file") or not e.get("because"):
            _fail(findings, pkg, "L1",
                  f"{inv_id}: every exempt entry needs `file` and `because`")
            return {}, False
        if e["file"] in out:
            _fail(findings, pkg, "L1",
                  f"{inv_id}: duplicate exempt entry for {e['file']}")
            return {}, False
        entry = dict(e)
        lm = e.get("line_matches")
        if lm is not None:
            if kind != "forbid_regex":
                _fail(findings, pkg, "L1",
                      f"{inv_id}: line_matches is only meaningful for forbid_regex")
                return {}, False
            try:
                entry["_line_rx"] = re.compile(lm)
            except re.error as exc:
                _fail(findings, pkg, "L1",
                      f"{inv_id}: exempt.line_matches is not a valid regex: {exc}")
                return {}, False
        out[e["file"]] = entry
    return out, True


def _check_mirror(repo: Path, pkg: str, inv_id: str, rule: dict,
                  subject: list[str], tracked: list[str], findings: list) -> None:
    other = rule.get("package")
    if not isinstance(other, str) or other not in {
            rel.rsplit("/", 1)[0] for rel in tracked if "/" in rel}:
        _fail(findings, pkg, "L1",
              f"{inv_id}: rule.package must name a directory holding tracked "
              f"files, got {other!r}")
        return
    for name in subject:
        theirs = repo / other / name
        if not theirs.is_file():
            _fail(findings, pkg, "L3",
                  f'invariant violated by "{pkg}": {inv_id} -- '
                  f"{pkg}/{name} has no counterpart at {other}/{name}")
            continue
        if (repo / pkg / name).read_bytes() != theirs.read_bytes():
            _fail(findings, pkg, "L3",
                  f'invariant violated by "{pkg}": {inv_id} -- '
                  f"{pkg}/{name} differs from {other}/{name}")


def audit(repo: Path) -> dict:
    tracked = tracked_files(repo)
    tracked_set = set(tracked)
    packages = discover_packages(tracked)
    if not packages:
        raise NotDetermined(
            f"0 code packages discovered under {repo} (no directory holds "
            f"{MIN_SOURCE_FILES}+ tracked source files) -- refusing to report "
            f"a clean audit of nothing")

    # A declaration at the repository ROOT has no "/" to split on, and the root
    # can never BE a package (discovery ignores root-level files), so folding it
    # in as "." is what makes P3 report it instead of never seeing it.
    declared = sorted((rel.rsplit("/", 1)[0] if "/" in rel else ".")
                      for rel in tracked
                      if rel == FILENAME or rel.endswith("/" + FILENAME))
    findings: list = []
    stats = {"rules": 0, "files_examined": 0, "invariants": 0,
             "declarations_read": 0}

    for pkg in sorted(set(declared) - set(packages)):
        _fail(findings, pkg, "P3",
              f"{FILENAME} in a directory that is not a code package "
              f"(< {MIN_SOURCE_FILES} tracked source files directly in it)")

    seen_ids: dict[str, str] = {}
    seen_ns: dict[str, str] = {}
    try:
        import yaml
    except ImportError as exc:                      # pragma: no cover
        raise NotDetermined(f"PyYAML unavailable: {exc}") from exc

    for pkg in packages:
        path = repo / pkg / FILENAME
        if not path.is_file():
            _fail(findings, pkg, "P2",
                  f"no {FILENAME} -- a code package with no invariant file is "
                  f"NOT a package with no constraints")
            continue
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            _fail(findings, pkg, "C1", f"{FILENAME} is not valid YAML: {exc}")
            continue
        if not isinstance(doc, dict):
            _fail(findings, pkg, "C1", f"{FILENAME} is not a mapping")
            continue
        if doc.get("schema") != 1:
            _fail(findings, pkg, "C1",
                  f"schema must be 1, got {doc.get('schema')!r}")
            continue
        if doc.get("package") != pkg:
            _fail(findings, pkg, "C2",
                  f"declares package: {doc.get('package')!r} but lives in {pkg}")
            continue
        stats["declarations_read"] += 1
        role = doc.get("role")
        if not isinstance(role, str) or not role.strip():
            _fail(findings, pkg, "C3", "role: must be a non-empty statement")
        ns = doc.get("namespace")
        if not isinstance(ns, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", ns or ""):
            _fail(findings, pkg, "C1",
                  f"namespace must be a lowercase slug, got {ns!r}")
            continue
        if ns in seen_ns:
            _fail(findings, pkg, "C6",
                  f'namespace "{ns}" is already owned by {seen_ns[ns]}')
            continue
        seen_ns[ns] = pkg

        invs = doc.get("invariants")
        if not isinstance(invs, list) or not invs:
            _fail(findings, pkg, "C4", "invariants: must be a non-empty list")
            continue
        for inv in invs:
            if not isinstance(inv, dict):
                _fail(findings, pkg, "C5", "an invariant entry is not a mapping")
                continue
            inv_id = inv.get("id")
            if not isinstance(inv_id, str) or not inv_id.strip():
                _fail(findings, pkg, "C5", "an invariant has no id")
                continue
            if not isinstance(inv.get("statement"), str) or \
                    not inv["statement"].strip():
                _fail(findings, pkg, "C5", f"{inv_id}: statement must be non-empty")
            if inv_id in seen_ids:
                _fail(findings, pkg, "C6",
                      f'id "{inv_id}" is already owned by {seen_ids[inv_id]} -- '
                      f"one rule, one owner")
                continue
            seen_ids[inv_id] = pkg
            if not inv_id.startswith(ns + "."):
                _fail(findings, pkg, "C7",
                      f'id "{inv_id}" is not prefixed by this package\'s '
                      f'namespace "{ns}." -- a failure must name its owner')
            stats["invariants"] += 1

            enf = inv.get("enforced_by")
            if not isinstance(enf, list) or not enf:
                _fail(findings, pkg, "C8",
                      f"{inv_id}: enforced_by must name at least one tracked path")
            else:
                for p in enf:
                    if not isinstance(p, str) or p not in tracked_set:
                        _fail(findings, pkg, "C8",
                              f"{inv_id}: enforced_by {p!r} is not a tracked file "
                              f"-- a rule may not claim an enforcer that is not there")

            if "rule" in inv:
                _check_rule(repo, pkg, inv_id, inv["rule"], tracked, findings, stats)

    return {"repo": str(repo), "packages": packages, "declared": declared,
            "findings": findings, "stats": stats,
            "passed": not findings}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", nargs="?", default=None,
                    help="any path inside the repository (default: this file)")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    start = Path(a.root).resolve() if a.root else Path(__file__).resolve().parent
    try:
        repo = find_repo_root(start)
        rep = audit(repo)
    except NotDetermined as exc:
        print(f"NOT_CHECKED: {exc}")
        print("=> package invariants NOT DETERMINED (examined 0 packages) -- "
              "rc 2 is not a pass")
        return 2

    st = rep["stats"]
    print(f"examined {len(rep['packages'])} code package(s), "
          f"read {st['declarations_read']} {FILENAME} declaration(s), "
          f"{st['invariants']} invariant(s), "
          f"{st['rules']} local rule(s) over {st['files_examined']} file(s) "
          f"({len(rep['declared'])} {FILENAME} path(s) tracked)")
    for f in rep["findings"]:
        print(f"   [{f['code']}] {f['package']}: {f['detail']}")
    print("=> package invariants " + ("PASS" if rep["passed"] else "FAIL")
          + f" ({len(rep['findings'])} finding(s))")

    if a.json:
        out = Path(a.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n")
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
