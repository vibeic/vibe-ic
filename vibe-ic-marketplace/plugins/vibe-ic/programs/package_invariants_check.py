#!/usr/bin/env python3
"""package_invariants_check.py — a package's rules live next to its code.

ENFORCEMENT: blocking
A violation exits 1. Every caller in this repo treats a non-zero exit as a red
gate, so a declared invariant that stops holding STOPS THE LANDING. It does not
record and continue: an advisory locality gate would be the worst of both
worlds — the rule moved next to the code AND stopped being enforced.

THE GAP THIS CLOSES
===================
Measured against `deepseek-harness` @ 99f6f02fe (54 top-level packages, 226 leaf
packages, 219 `invariant.ts` files) and written up in
`docs/research/2026-08-19-deepseek-harness-source-study.md`: we are AHEAD on
ENFORCEMENT — our gates are stronger and adversarially tested — and BEHIND on
LOCALITY. Our rules live centrally, so a contributor editing a module cannot see
the rule that binds it without going somewhere else.

Central rules are read by whoever goes looking. A rule nobody goes looking for is
obeyed by accident.

WHY THE OBVIOUS PORT DOES NOT FIT, AND WHAT REPLACES IT
=======================================================
Theirs is directory-as-package, and it is load-bearing for them because a package
is a publishable unit with its own manifest and build; their
`scripts/verify-package-invariants.ts` checks that wiring. Counted here, the
directories that directly hold source are dominated by two flat ones — 2636
tracked files in `programs/tests`, 1211 in `programs` — so directory-as-package
buys nothing exactly where it is needed most: the flat `programs/` tree would be
ONE package with ONE file, and moving those files into per-subsystem directories
would cost the flat-namespace grep that D1/D2, the denominator audits and the
checker-execution wiring audit all depend on.

So the unit here is not "a directory". It is:

    A PACKAGE IS A SCOPE DECLARED BY EXACTLY ONE INVARIANT FILE, AND THE FILE'S
    OWN PATH DETERMINES WHAT IT MAY OWN.

Two forms, and the second is what makes a flat tree work:

    <dir>/INVARIANTS.yaml              owns <dir>/**            (nested tree)
    <dir>/<prefix>.INVARIANTS.yaml     owns <dir>/<prefix>*     (flat namespace)

In a flat directory, alphabetical adjacency IS locality: `l9.INVARIANTS.yaml`
sorts next to `l9_floorplan_contract_check.py`, so `ls programs/ | grep l9` shows
the rule beside the code without one file being moved.

Exclusive ownership falls out of the path rule — a package cannot reach outside
its own directory — and it is the half of theirs worth taking: their
`invariants/src/index.ts:140-142` refuses a duplicate registration, and this repo
has ~1200 programs in one namespace with no mechanism that says "this rule
already has an owner". Here, TWO PACKAGES CLAIMING ONE FILE IS A REFUSAL.

WHAT A PACKAGE DECLARES
=======================
    package: tools/ci                    # must equal the id derived from the path
    invariants:
      - id: <globally unique>
        rule: |
          <prose the contributor reads, and the measured reason it exists>
        applies_to: ["*.py", "*.sh"]     # globs, package-relative
        excludes:   ["test_*.py"]        # optional
        forbid: '<regex>'                # exactly one of forbid / require
        require: '<regex>'
        counterexample: '<text this rule MUST reject>'

`require` is existential (the pattern must appear somewhere in each applicable
file). `forbid` is universal — and with a negative lookahead it expresses
"every X must be Y" without a second predicate kind, which is why there are only
two.

A GUARD NEVER SEEN TO FAIL HAS NOT BEEN SHOWN TO CHECK ANYTHING
===============================================================
`counterexample` is mandatory, and this program verifies it on every run: the
text must VIOLATE the rule that ships it — matched by a `forbid`, unmatched by a
`require`. A rule whose counterexample passes is MALFORMED, and is refused with
the same weight as a real violation.

The reason it is a required field rather than a convention: a rule can hold over
a whole population because it is true, or because its pattern matches nothing it
was ever pointed at, and from a green run those are indistinguishable. Every
`forbid` here is expected to match zero files today — that is the healthy state
for a prohibition, and it is also exactly what a typo in the regex looks like.
The counterexample is what separates them, permanently and per rule, rather than
once by whoever happened to author it.

WHO READS IT, AND WHAT FAILS
============================
The contributor reads it because it is in the directory they are already in. This
program reads it because a rule nobody machine-checks decays into a comment.
Failures are ATTRIBUTED to the owning package — `<package>: <id>` — not to a
central checker, which is the property that makes the file worth having where it
is.

Refusals (all exit 1):

  VIOLATION     an applicable file violates a declared invariant
  VACUOUS       an invariant's `applies_to` selects ZERO files. A rule that
                cannot fire is not a rule; this repo's own lesson is that an
                unmeasured thing reads as a measured zero
  TOOTHLESS     an invariant's own `counterexample` does not violate it — the
                rule has not been shown to check anything
  OVERLAP       two packages own one file
  MISPLACED     `package:` disagrees with the declaring file's own location
  DUPLICATE_ID  one id declared by two packages
  MALFORMED     unparsable YAML, missing/unknown key, uncompilable regex
  UNDECLARED    a package the LEDGER records has no invariant file on disk
  UNLEDGERED    an invariant file on disk that the ledger does not record

UNDECLARED IS THE WHOLE POINT
=============================
A missing invariant file must NOT read as "this package has no constraints".
That is why the ledger (`package_invariants_ledger.json`) lives OUTSIDE every
package it records: deleting a package's own file cannot delete the record that
it owes one. The comparison is EXACT-SET EQUALITY in both directions, so the
ledger can neither quietly absorb a new package nor quietly forget an old one.

This does not make the register unforgeable — nothing does, against an author
willing to edit everything. It raises deletion from ONE silent edit to THREE
visible ones: the declaration, the ledger row, and the named constant in
`test_package_invariants_check.py` that pins the ledger's membership.

EXIT CODES AND THE DENOMINATOR
==============================
    0  every declared invariant holds, over a NON-EMPTY population
    1  a refusal above
    2  NOT_CHECKED — the root is not a directory, or discovery found ZERO
       invariant files

rc 2 rather than rc 0 on an empty population is deliberate, and it is the exact
defect measured in theirs: `scripts/package-invariants.ts:38` discovers owners
with a hardcoded depth-2 glob, `verify-package-invariants.ts:13` exits 1 only
when `violations.length > 0`, so a moved corpus yields 0 owners, an empty
violations list, and `0 hand-owned package companion(s) conform.` — exit 0. A
gate that cannot tell a moved corpus from a clean one is the class
`gate_zero_denominator_refuses_check` exists to find.

Every run prints its denominator — population source, tracked files, packages,
invariants, files examined — whether it passes or fails, so a PASS can never be
read off a scan that examined nothing.

WIRING (stated so the wiring cannot be assumed)
===============================================
Enforced today by `programs/tests/test_package_invariants_check.py`, which runs
this program over the real tree; a failure there is a red test and blocks the
landing at the full-suite cadence and on any change that selects this module.

It BELONGS in `tools/ci/repo_hygiene_gates.sh` — it is a repo-wide invariant
needing no PR context, which is that file's stated admission rule — as:

    run "package invariants" "$ROOT" python3 "$PG/package_invariants_check.py" "$ROOT"

That file is a PROTECTED landing-authority path and is deliberately NOT edited
here. Until that line lands, this gate does not run on a patch-cadence PR that
touches only a constrained package file, and this docstring says so rather than
letting the wiring be assumed.

chip-AGNOSTIC: it reasons about file paths, YAML declarations and regexes. It
hardcodes no package, no design, no PDK and no vendor — the package set comes
from the ledger and the rules come from the packages themselves.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only where PyYAML is absent
    yaml = None

_DECL_BASENAME = "INVARIANTS.yaml"
_DECL_SUFFIX = "." + _DECL_BASENAME
_DEFAULT_LEDGER = "package_invariants_ledger.json"

#: Keys a declaration may carry. Anything else is MALFORMED rather than ignored:
#: a typo'd key that is silently dropped turns a rule into a comment, which is
#: the failure mode this whole program exists to prevent.
_PKG_KEYS = {"package", "invariants"}
_INV_KEYS = {"id", "rule", "applies_to", "excludes", "require", "forbid",
             "counterexample"}

_ID_RE = re.compile(r"\A[a-z0-9][a-z0-9-]{2,63}\Z")


# ---------------------------------------------------------------------------
# population


def _git_tracked(root: Path) -> Optional[List[str]]:
    """Tracked paths, repo-relative, or None when this is not a git worktree.

    Returning None rather than an empty list is the point: "git said nothing"
    and "git is not here" are different facts, and only the caller can decide
    what to do with the second one.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, check=False,
        )
    except OSError:
        return None
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def _walk(root: Path) -> List[str]:
    """Every file under `root`, repo-relative, skipping VCS and caches."""
    skip = {".git", "__pycache__", ".pytest_cache", "node_modules"}
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        rel_dir = Path(dirpath).relative_to(root)
        for name in sorted(filenames):
            rel = rel_dir / name
            found.append(rel.as_posix())
    return sorted(found)


def population(root: Path) -> Tuple[List[str], str]:
    """(paths, source). The source is REPORTED, never inferred by the reader."""
    tracked = _git_tracked(root)
    if tracked is not None:
        return sorted(tracked), "git-tracked"
    return _walk(root), "filesystem-walk"


# ---------------------------------------------------------------------------
# globs
#
# `fnmatch` is not usable here: its `*` matches `/`, so `*.py` would claim
# `a/b/c.py` and every `applies_to` would silently widen to the whole subtree.


def glob_to_re(pattern: str) -> re.Pattern:
    out = ["\\A"]
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i:i + 3] == "**/":
                out.append("(?:[^/]+/)*")
                i += 3
                continue
            if pattern[i:i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(c))
        i += 1
    out.append("\\Z")
    return re.compile("".join(out))


def _matches_any(rel: str, patterns: Sequence[re.Pattern]) -> bool:
    return any(p.search(rel) for p in patterns)


# ---------------------------------------------------------------------------
# model


@dataclass
class Invariant:
    id: str
    rule: str
    applies_to: List[str]
    excludes: List[str]
    kind: str                      # "require" | "forbid"
    pattern: str
    regex: re.Pattern
    counterexample: str
    applies_re: List[re.Pattern] = field(default_factory=list)
    excl_re: List[re.Pattern] = field(default_factory=list)


@dataclass
class Package:
    decl: str                      # repo-relative path of the declaration
    kind: str                      # "directory" | "prefix"
    directory: str                 # repo-relative dir ("" for the root)
    prefix: str                    # "" for the directory form
    package_id: str
    declared_id: str
    invariants: List[Invariant] = field(default_factory=list)

    def owns(self, rel: str) -> bool:
        if rel == self.decl or _is_decl(rel):
            return False
        base = (self.directory + "/") if self.directory else ""
        if not rel.startswith(base):
            return False
        return rel[len(base):].startswith(self.prefix)

    def relative(self, rel: str) -> str:
        base = (self.directory + "/") if self.directory else ""
        return rel[len(base):]


def _is_decl(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name == _DECL_BASENAME or name.endswith(_DECL_SUFFIX)


def derive_id(decl: str) -> Tuple[str, str, str, str]:
    """(kind, directory, prefix, package_id) from the declaration's own path."""
    directory, _, name = decl.rpartition("/")
    if name == _DECL_BASENAME:
        return "directory", directory, "", (directory or ".")
    prefix = name[: -len(_DECL_SUFFIX)]
    return "prefix", directory, prefix, f"{directory or '.'}:{prefix}"


# ---------------------------------------------------------------------------
# findings


@dataclass
class Finding:
    code: str
    package: str
    detail: str

    def line(self) -> str:
        return f"[{self.code}] {self.package}: {self.detail}"


def _parse_invariant(raw: object, pkg_id: str, out: List[Finding]) -> Optional[Invariant]:
    if not isinstance(raw, dict):
        out.append(Finding("MALFORMED", pkg_id, f"invariant is {type(raw).__name__}, not a mapping"))
        return None
    unknown = sorted(set(raw) - _INV_KEYS)
    if unknown:
        out.append(Finding("MALFORMED", pkg_id, f"unknown invariant key(s): {', '.join(unknown)}"))
        return None
    inv_id = raw.get("id")
    if not isinstance(inv_id, str) or not _ID_RE.match(inv_id):
        out.append(Finding("MALFORMED", pkg_id,
                           f"id must be lower-kebab-case, 3-64 chars; got {inv_id!r}"))
        return None
    rule = raw.get("rule")
    if not isinstance(rule, str) or len(rule.strip()) < 20:
        out.append(Finding("MALFORMED", pkg_id,
                           f"{inv_id}: `rule` must be prose a contributor can act on "
                           f"(>= 20 chars); got {rule!r}"))
        return None
    applies = raw.get("applies_to")
    if not isinstance(applies, list) or not applies or not all(isinstance(g, str) for g in applies):
        out.append(Finding("MALFORMED", pkg_id, f"{inv_id}: `applies_to` must be a non-empty list of globs"))
        return None
    excludes = raw.get("excludes", [])
    if not isinstance(excludes, list) or not all(isinstance(g, str) for g in excludes):
        out.append(Finding("MALFORMED", pkg_id, f"{inv_id}: `excludes` must be a list of globs"))
        return None
    has = [k for k in ("require", "forbid") if k in raw]
    if len(has) != 1:
        out.append(Finding("MALFORMED", pkg_id,
                           f"{inv_id}: declare exactly one of `require` / `forbid`; got {has or 'neither'}"))
        return None
    kind = has[0]
    pattern = raw[kind]
    if not isinstance(pattern, str) or not pattern:
        out.append(Finding("MALFORMED", pkg_id, f"{inv_id}: `{kind}` must be a non-empty regex"))
        return None
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        out.append(Finding("MALFORMED", pkg_id, f"{inv_id}: `{kind}` is not a valid regex: {exc}"))
        return None
    counter = raw.get("counterexample")
    if not isinstance(counter, str) or not counter:
        out.append(Finding("MALFORMED", pkg_id,
                           f"{inv_id}: `counterexample` is mandatory — a rule with no "
                           f"text it is known to reject has not been shown to check anything"))
        return None
    rejected = (rx.search(counter) is not None) if kind == "forbid" else (rx.search(counter) is None)
    if not rejected:
        out.append(Finding("TOOTHLESS", pkg_id,
                           f"{inv_id}: the declared counterexample {counter[:60]!r} does NOT "
                           f"violate `{kind}: {pattern!r}`. Either the pattern does not mean "
                           f"what the rule says, or the counterexample does not exercise it; "
                           f"a rule that has never been seen to reject anything cannot be "
                           f"distinguished from one that matches nothing"))
        return None
    inv = Invariant(inv_id, rule, applies, list(excludes), kind, pattern, rx, counter)
    inv.applies_re = [glob_to_re(g) for g in applies]
    inv.excl_re = [glob_to_re(g) for g in excludes]
    return inv


def load_package(root: Path, decl: str, out: List[Finding]) -> Optional[Package]:
    kind, directory, prefix, pkg_id = derive_id(decl)
    try:
        text = (root / decl).read_text(encoding="utf-8")
    except OSError as exc:
        out.append(Finding("MALFORMED", pkg_id, f"unreadable: {exc}"))
        return None
    if yaml is None:
        out.append(Finding("MALFORMED", pkg_id, "PyYAML is not importable; declarations cannot be read"))
        return None
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        out.append(Finding("MALFORMED", pkg_id, f"unparsable YAML: {exc}"))
        return None
    if not isinstance(doc, dict):
        out.append(Finding("MALFORMED", pkg_id, f"top level is {type(doc).__name__}, not a mapping"))
        return None
    unknown = sorted(set(doc) - _PKG_KEYS)
    if unknown:
        out.append(Finding("MALFORMED", pkg_id, f"unknown top-level key(s): {', '.join(unknown)}"))
        return None
    declared = doc.get("package")
    invs_raw = doc.get("invariants")
    if not isinstance(invs_raw, list) or not invs_raw:
        out.append(Finding("MALFORMED", pkg_id, "`invariants` must be a non-empty list"))
        return None
    pkg = Package(decl, kind, directory, prefix, pkg_id, declared if isinstance(declared, str) else "")
    if pkg.declared_id != pkg_id:
        out.append(Finding("MISPLACED", pkg_id,
                           f"`package: {declared!r}` disagrees with the declaration's own "
                           f"location; from {decl} the id is {pkg_id!r}"))
        return None
    for raw in invs_raw:
        inv = _parse_invariant(raw, pkg_id, out)
        if inv is not None:
            pkg.invariants.append(inv)
    return pkg


# ---------------------------------------------------------------------------
# the check


@dataclass
class Report:
    rc: int
    findings: List[Finding]
    summary: Dict[str, object]

    def render(self) -> str:
        lines = [f.line() for f in self.findings]
        s = self.summary
        lines.append(
            "package_invariants: "
            f"population_source={s['population_source']} "
            f"files_in_tree={s['files_in_tree']} "
            f"packages={s['packages']} "
            f"invariants={s['invariants']} "
            f"files_examined={s['files_examined']} "
            f"file_rule_pairs={s['file_rule_pairs']} "
            f"violations={s['violations']}"
        )
        verdict = {0: "PASS", 1: "FAIL", 2: "NOT_CHECKED"}[self.rc]
        lines.append(f"package_invariants: {verdict} — {s['verdict_reason']}")
        return "\n".join(lines)


def check(root: Path, ledger_path: Optional[Path] = None) -> Report:
    base_summary: Dict[str, object] = {
        "population_source": "none",
        "files_in_tree": 0,
        "packages": 0,
        "invariants": 0,
        "files_examined": 0,
        "file_rule_pairs": 0,
        "violations": 0,
        "package_ids": [],
        "verdict_reason": "",
    }

    if not root.is_dir():
        s = dict(base_summary, verdict_reason=f"root is not a directory: {root}")
        return Report(2, [], s)

    paths, source = population(root)
    base_summary["population_source"] = source
    base_summary["files_in_tree"] = len(paths)

    decls = sorted(p for p in paths if _is_decl(p))
    if not decls:
        s = dict(base_summary,
                 verdict_reason=("no INVARIANTS.yaml declaration found in "
                                 f"{len(paths)} file(s); nothing was checked, and an "
                                 "empty population is NOT a pass"))
        return Report(2, [], s)

    findings: List[Finding] = []
    packages: List[Package] = []
    for decl in decls:
        pkg = load_package(root, decl, findings)
        if pkg is not None:
            packages.append(pkg)

    # DUPLICATE_ID — one rule, one owner, across the whole repo.
    seen: Dict[str, str] = {}
    for pkg in packages:
        for inv in pkg.invariants:
            prev = seen.get(inv.id)
            if prev is not None:
                findings.append(Finding("DUPLICATE_ID", pkg.package_id,
                                        f"id {inv.id!r} is already declared by {prev}"))
            else:
                seen[inv.id] = pkg.package_id

    # OVERLAP — exclusive ownership, refused rather than resolved.
    owners: Dict[str, List[str]] = {}
    for rel in paths:
        if _is_decl(rel):
            continue
        claim = [p.package_id for p in packages if p.owns(rel)]
        if len(claim) > 1:
            owners[rel] = claim
    for rel, claim in sorted(owners.items()):
        findings.append(Finding("OVERLAP", claim[0],
                                f"{rel} is claimed by {len(claim)} packages: {', '.join(sorted(claim))}"))

    # LEDGER — exact-set equality, both directions.
    ledger = ledger_path if ledger_path is not None else (
        Path(__file__).resolve().parent / _DEFAULT_LEDGER)
    ledger_ids: Optional[List[str]] = None
    if ledger.is_file():
        try:
            doc = json.loads(ledger.read_text(encoding="utf-8"))
            ledger_ids = sorted(e["package"] for e in doc["packages"])
        except (ValueError, KeyError, TypeError) as exc:
            findings.append(Finding("MALFORMED", str(ledger), f"unreadable ledger: {exc}"))
    else:
        findings.append(Finding("MALFORMED", str(ledger),
                                "ledger absent; a package set with no register cannot "
                                "tell a deleted declaration from a package that never had one"))

    on_disk = sorted(p.package_id for p in packages)
    if ledger_ids is not None:
        for pid in ledger_ids:
            if pid not in on_disk:
                findings.append(Finding(
                    "UNDECLARED", pid,
                    "the ledger records this package but no INVARIANTS.yaml declares "
                    "it; a missing invariant file does not mean 'no constraints'"))
        for pid in on_disk:
            if pid not in ledger_ids:
                findings.append(Finding(
                    "UNLEDGERED", pid,
                    "declares invariants but is absent from the ledger; an unledgered "
                    "package can be deleted without the deletion being visible"))

    # The rules themselves.
    examined: set = set()
    pairs = 0
    violations = 0
    for pkg in packages:
        owned = [rel for rel in paths if pkg.owns(rel)]
        for inv in pkg.invariants:
            applicable = [
                rel for rel in owned
                if _matches_any(pkg.relative(rel), inv.applies_re)
                and not _matches_any(pkg.relative(rel), inv.excl_re)
            ]
            if not applicable:
                findings.append(Finding(
                    "VACUOUS", pkg.package_id,
                    f"{inv.id}: applies_to {inv.applies_to} selects 0 files of the "
                    f"{len(owned)} this package owns; a rule that cannot fire is not a rule"))
                continue
            for rel in applicable:
                pairs += 1
                examined.add(rel)
                try:
                    text = (root / rel).read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    findings.append(Finding("MALFORMED", pkg.package_id,
                                            f"{inv.id}: cannot read {rel}: {exc}"))
                    violations += 1
                    continue
                hit = inv.regex.search(text)
                if inv.kind == "forbid" and hit is not None:
                    line_no = text.count("\n", 0, hit.start()) + 1
                    violations += 1
                    findings.append(Finding(
                        "VIOLATION", f"{pkg.package_id}: {inv.id}",
                        f"{rel}:{line_no} matches forbidden pattern {inv.pattern!r} "
                        f"({hit.group(0)[:80]!r}) — {_first_line(inv.rule)}"))
                elif inv.kind == "require" and hit is None:
                    violations += 1
                    findings.append(Finding(
                        "VIOLATION", f"{pkg.package_id}: {inv.id}",
                        f"{rel} does not match required pattern {inv.pattern!r} — "
                        f"{_first_line(inv.rule)}"))

    summary = dict(
        base_summary,
        packages=len(packages),
        invariants=sum(len(p.invariants) for p in packages),
        files_examined=len(examined),
        file_rule_pairs=pairs,
        violations=violations,
        package_ids=on_disk,
    )
    structural = [f for f in findings if f.code != "VIOLATION"]
    if findings:
        summary["verdict_reason"] = (
            f"{violations} violation(s) and {len(structural)} structural refusal(s) "
            f"across {len(packages)} package(s)")
        return Report(1, findings, summary)
    summary["verdict_reason"] = (
        f"{summary['invariants']} invariant(s) from {len(packages)} package(s) hold "
        f"over {len(examined)} file(s)")
    return Report(0, findings, summary)


def _first_line(rule: str) -> str:
    for line in rule.splitlines():
        if line.strip():
            return line.strip()
    return ""


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".", help="repository root to check")
    ap.add_argument("--ledger", default=None,
                    help="package ledger JSON (default: next to this program)")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the machine record here")
    args = ap.parse_args(list(argv) if argv is not None else None)

    rep = check(Path(args.root).resolve(),
                Path(args.ledger).resolve() if args.ledger else None)
    print(rep.render())
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "schema": 1,
            "kind": "vibeic.package-invariants",
            "rc": rep.rc,
            "summary": rep.summary,
            "findings": [{"code": f.code, "package": f.package, "detail": f.detail}
                         for f in rep.findings],
        }, indent=2) + "\n", encoding="utf-8")
    return rep.rc


if __name__ == "__main__":
    sys.exit(main())
