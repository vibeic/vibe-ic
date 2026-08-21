#!/usr/bin/env python3
"""package_invariants_check.py — the rule lives NEXT TO the code it binds.

WHY THIS EXISTS
---------------
Measured 2026-08-19 against the deepseek-harness tree at 99f6f02fe (counted in a
clone, not read off a summary): 54 top-level packages, 226 leaf packages, and
219 `invariant.ts` files — one per package, next to the code. Our own verdict
against that tree: we are AHEAD on enforcement (our gates are adversarially
tested and they block landing) and BEHIND on LOCALITY. Every rule we enforce
lives centrally, so a contributor editing `commands/` or `ip-catalog/` cannot
see the rule that binds what they are editing without going somewhere else to
look for it — and mostly does not go.

This program closes the locality half WITHOUT giving up the enforcement half.

NOTE ON THE FIVE FILES THAT ALREADY MATCH "invariant" IN THIS REPO
(`cross_constant_invariant_check.py`, `fsm_error_invariant.py`, and three tests):
those are UNRELATED single checks about DESIGN invariants inside a chip. They
are not this pattern, they are not per-package, and they must not be counted as
adoption of it.

THE SHAPE, AND WHY IT IS THIS SHAPE
-----------------------------------
WHAT A PACKAGE DECLARES
    One `INVARIANTS.json` at the package root. Each entry carries
      * `id`         — stable handle, quoted by the gate when it fails;
      * `statement`  — the rule in one sentence, for the human;
      * `why`        — what went wrong, or would go wrong, without it;
      * `rule`       — the machine form (one of four kinds, below);
      * `counterexample` — a file the rule MUST reject; a LIST of them when
                       the rule has more than one clause, one per clause, each
                       carrying a `proves` note. One counterexample against a
                       two-clause rule shows only that one clause
                       discriminates, and leaves the other half a claim nobody
                       has tested.
    Prose and machine form sit in the same object on purpose: a statement with
    no rule is decoration, and a rule with no statement is unreadable.

WHO READS IT
    1. This gate, on every landing run, via
       `programs/tests/test_package_invariants_check.py`. The rules are
       evaluated against the package's own files.
    2. This gate again, differently: every counterexample a rule declares is
       evaluated in isolation and MUST be rejected by that rule. A rule nothing
       can violate is not a rule, and this is what stops a per-package file from
       decaying into per-package decoration — the single biggest risk of moving
       rules out of the centre.
    3. The contributor, at the moment it matters: `--touched` prints the
       invariants binding every package a diff touches, and
       `tools/ci/pre_commit_check.sh` calls it on the staged file list.

WHAT FAILS WHEN IT IS VIOLATED — OR MISSING
    VIOLATION            a package file breaks a rule its own package declares.
    NON_DISCRIMINATING   a rule did not reject its own counterexample.
    MISSING_FILE         an ENROLLED package directory exists with no
                         INVARIANTS.json. A deleted invariant file must never
                         read as "this package has no constraints" — that is the
                         failure mode this whole design would otherwise create,
                         so it is a hard FAIL, not a skip.
    EMPTY                the file exists and declares zero invariants. Same
                         reasoning: empty is not "unconstrained".
    UNENROLLED           an INVARIANTS.json exists in a package the enrollment
                         does not name. An unenrolled file is a file the gate
                         would not have missed if it vanished, i.e. exactly the
                         "nobody reads it" artefact.
    STALE_ENROLLMENT     an enrolled path is no longer a directory. Legitimate
                         when a package is genuinely deleted; the entry must
                         then be pruned in the same change, which is a visible
                         edit rather than a silent one.

ENROLLMENT, AND WHY IT IS NOT DERIVED
    `programs/package_invariants_enrolled.json` names the enrolled packages.
    Enrollment cannot be derived from "has an INVARIANTS.json", because then
    deleting the file would delete the obligation — the gate would go green on
    the exact act it exists to catch. So enrollment is a separate memory:
    the file is required BECAUSE the package is enrolled, not because the file
    is there. The enrollment list is deliberately additive; shrinking it is a
    second edit, in a second file, and the floor pinned in
    `test_package_invariants_check.py::test_enrollment_floor` fails when it
    shrinks. Two loud edits, never one silent one.

RULE KINDS (deliberately four — a rule language is a maintenance surface)
    forbid_regex       no file matching `include` may contain `regex`.
    require_regex      every file matching `include` must contain `regex`.
    require_companion  every entry matching `for_each` must have the file named
                       by `companion` (template over `{path}`, `{dir}`,
                       `{stem}`, `{name}`).
    forbid_path        no entry may match `glob`.

Usage:
    python3 package_invariants_check.py [--repo-root R] [--json OUT]
    python3 package_invariants_check.py --touched <repo-relative path>...

Exit: 0 = every enrolled package present, non-empty, obeyed, and discriminating
      1 = at least one finding
      2 = operational (repo root or enrollment file not found)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402  vibe-ic#1082

INVARIANTS_FILENAME = "INVARIANTS.json"
ENROLLMENT_FILENAME = "package_invariants_enrolled.json"
SCHEMA = 1

# Directories never walked when collecting a package's own files.
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".mypy_cache"}

_RULE_KINDS = ("forbid_regex", "require_regex", "require_companion", "forbid_path")


# --------------------------------------------------------------------------
# glob matching: `*` and `?` do NOT cross `/`; `**` does.
# --------------------------------------------------------------------------
def _glob_to_regex(pattern: str) -> re.Pattern:
    out, i, n = [], 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i:i + 3] == "**/":
                out.append(r"(?:.*/)?")
                i += 3
                continue
            if pattern[i:i + 2] == "**":
                out.append(r".*")
                i += 2
                continue
            out.append(r"[^/]*")
        elif c == "?":
            out.append(r"[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z")


def glob_match(pattern: str, relpath: str) -> bool:
    return _glob_to_regex(pattern).match(relpath) is not None


def _matches_any(patterns, relpath: str) -> bool:
    return any(glob_match(p, relpath) for p in patterns)


# --------------------------------------------------------------------------
# Package entry model. An "entry" is a path inside the package, with the file
# body when it is a file. `content` is a callable so the real walk only reads
# what a rule actually asks for.
# --------------------------------------------------------------------------
class Entry:
    __slots__ = ("relpath", "is_dir", "_read", "_cache")

    def __init__(self, relpath: str, is_dir: bool, read=None, content=None):
        self.relpath = relpath
        self.is_dir = is_dir
        self._read = read
        self._cache = content

    @property
    def content(self) -> str:
        if self._cache is None:
            self._cache = self._read() if self._read else ""
        return self._cache


def collect_entries(pkg_dir: Path) -> list[Entry]:
    entries: list[Entry] = []
    for p in sorted(pkg_dir.rglob("*")):
        rel_parts = p.relative_to(pkg_dir).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        rel = "/".join(rel_parts)
        if p.is_dir():
            entries.append(Entry(rel, True))
        else:
            entries.append(
                Entry(rel, False,
                      read=lambda q=p: q.read_text(encoding="utf-8", errors="ignore")))
    return entries


# --------------------------------------------------------------------------
# Rule evaluation. Returns a list of human-readable violations.
# --------------------------------------------------------------------------
def _compile(rule: dict, key: str) -> re.Pattern:
    flags = 0
    for f in rule.get("flags", []):
        flags |= {"IGNORECASE": re.I, "MULTILINE": re.M, "DOTALL": re.S}[f]
    return re.compile(rule[key], flags)


def _selected(rule: dict, entries, include_key: str, want_dir=None):
    include = rule.get(include_key) or []
    exclude = rule.get("exclude") or []
    for e in entries:
        if want_dir is not None and e.is_dir != want_dir:
            continue
        if not _matches_any(include, e.relpath):
            continue
        if exclude and _matches_any(exclude, e.relpath):
            continue
        yield e


def evaluate_rule(rule: dict, entries: list[Entry]) -> list[str]:
    kind = rule.get("kind")
    if kind == "forbid_regex":
        rx = _compile(rule, "regex")
        return [f"{e.relpath}: matches forbidden pattern {rule['regex']!r}"
                for e in _selected(rule, entries, "include", want_dir=False)
                if rx.search(e.content)]
    if kind == "require_regex":
        rx = _compile(rule, "regex")
        return [f"{e.relpath}: does not contain required pattern {rule['regex']!r}"
                for e in _selected(rule, entries, "include", want_dir=False)
                if not rx.search(e.content)]
    if kind == "require_companion":
        want_dir = {"dir": True, "file": False}.get(rule.get("for_each_kind", "file"))
        present = {e.relpath for e in entries}
        out = []
        for e in _selected(rule, entries, "for_each", want_dir=want_dir):
            name = e.relpath.rsplit("/", 1)[-1]
            stem = name[:name.rfind(".")] if "." in name else name
            parent = e.relpath.rsplit("/", 1)[0] if "/" in e.relpath else ""
            companion = rule["companion"].format(
                path=e.relpath, dir=parent, stem=stem, name=name).lstrip("/")
            if companion not in present:
                out.append(f"{e.relpath}: required companion {companion!r} is absent")
        return out
    if kind == "forbid_path":
        return [f"{e.relpath}: path is forbidden by {rule['glob']!r}"
                for e in _selected(rule, entries, "glob")]
    raise ValueError(f"unknown rule kind {kind!r} (known: {_RULE_KINDS})")


def counterexamples(inv: dict) -> list[dict]:
    """`counterexample` is one object, or a list when a rule has more than one
    clause. A two-clause rule proved by a single counterexample has only been
    shown to check one of its clauses, so each clause gets its own."""
    ce = inv["counterexample"]
    return list(ce) if isinstance(ce, list) else [ce]


def counterexample_entries(ce: dict) -> list[Entry]:
    """One counterexample as a one-entry virtual package."""
    return [Entry(ce["path"], bool(ce.get("is_dir", False)),
                  content=ce.get("content", ""))]


# --------------------------------------------------------------------------
# Schema validation of one INVARIANTS.json
# --------------------------------------------------------------------------
def validate_document(doc, pkg: str) -> list[str]:
    errs = []
    if not isinstance(doc, dict):
        return [f"{pkg}: {INVARIANTS_FILENAME} is not a JSON object"]
    if doc.get("schema") != SCHEMA:
        errs.append(f"{pkg}: schema must be {SCHEMA}, got {doc.get('schema')!r}")
    if doc.get("package") != pkg:
        errs.append(f"{pkg}: 'package' must be the package's own repo-relative "
                    f"path, got {doc.get('package')!r}")
    invs = doc.get("invariants")
    if not isinstance(invs, list):
        errs.append(f"{pkg}: 'invariants' must be a list")
        return errs
    seen = set()
    for i, inv in enumerate(invs):
        at = f"{pkg}: invariants[{i}]"
        if not isinstance(inv, dict):
            errs.append(f"{at}: not an object")
            continue
        for field in ("id", "statement", "why", "rule", "counterexample"):
            if not inv.get(field):
                errs.append(f"{at}: missing required field {field!r}")
        rid = inv.get("id")
        if rid in seen:
            errs.append(f"{at}: duplicate invariant id {rid!r}")
        seen.add(rid)
        rule = inv.get("rule")
        if isinstance(rule, dict) and rule.get("kind") not in _RULE_KINDS:
            errs.append(f"{at}: unknown rule kind {rule.get('kind')!r}")
        ce = inv.get("counterexample")
        ces = ce if isinstance(ce, list) else [ce]
        if isinstance(ce, list) and not ce:
            errs.append(f"{at}: counterexample list is empty")
        for j, one in enumerate(ces):
            if not isinstance(one, dict) or not one.get("path"):
                errs.append(f"{at}: counterexample[{j}] needs a 'path'")
    return errs


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------
def load_enrollment(programs_dir: Path) -> list[str]:
    f = programs_dir / ENROLLMENT_FILENAME
    doc = json.loads(f.read_text(encoding="utf-8"))
    return list(doc.get("packages", []))


def find_stray_invariant_files(repo: Path, enrolled: set[str]) -> list[str]:
    """Any INVARIANTS.json in a package the enrollment does not name."""
    stray = []
    for p in repo.rglob(INVARIANTS_FILENAME):
        rel_parts = p.relative_to(repo).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        pkg = "/".join(rel_parts[:-1])
        if pkg not in enrolled:
            stray.append(pkg)
    return sorted(stray)


def check(repo: Path, programs_dir: Path) -> dict:
    enrolled = load_enrollment(programs_dir)
    findings: list[dict] = []
    packages: list[dict] = []

    for pkg in enrolled:
        pkg_dir = repo / pkg
        if not pkg_dir.is_dir():
            findings.append({
                "code": "STALE_ENROLLMENT", "package": pkg,
                "detail": f"enrolled package directory {pkg} does not exist; "
                          f"prune the entry from {ENROLLMENT_FILENAME} in the "
                          f"same change that removed the package"})
            continue
        inv_file = pkg_dir / INVARIANTS_FILENAME
        if not inv_file.is_file():
            findings.append({
                "code": "MISSING_FILE", "package": pkg,
                "detail": f"{pkg}/{INVARIANTS_FILENAME} is absent. An enrolled "
                          f"package with no invariant file is NOT a package "
                          f"with no constraints — restore the file, or remove "
                          f"the package and prune its enrollment."})
            continue
        try:
            doc = json.loads(inv_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            findings.append({"code": "SCHEMA", "package": pkg,
                             "detail": f"{pkg}/{INVARIANTS_FILENAME}: {exc}"})
            continue
        schema_errs = validate_document(doc, pkg)
        if schema_errs:
            findings += [{"code": "SCHEMA", "package": pkg, "detail": e}
                         for e in schema_errs]
            continue
        invs = doc["invariants"]
        if not invs:
            findings.append({
                "code": "EMPTY", "package": pkg,
                "detail": f"{pkg}/{INVARIANTS_FILENAME} declares zero "
                          f"invariants. An empty invariant file is not a "
                          f"package without constraints; it is a package whose "
                          f"constraints were never written down."})
            continue

        entries = collect_entries(pkg_dir)
        for inv in invs:
            rule, rid = inv["rule"], inv["id"]
            try:
                violations = evaluate_rule(rule, entries)
            except (ValueError, KeyError, re.error) as exc:
                findings.append({"code": "SCHEMA", "package": pkg, "id": rid,
                                 "detail": f"{pkg}:{rid}: rule is not "
                                           f"evaluable: {exc}"})
                continue
            for v in violations:
                findings.append({
                    "code": "VIOLATION", "package": pkg, "id": rid,
                    "detail": f"{pkg}:{rid} — {inv['statement']} :: {v}"})
            # The counterexamples are the negative control, run every time.
            for ce in counterexamples(inv):
                try:
                    ce_hits = evaluate_rule(rule, counterexample_entries(ce))
                except (ValueError, KeyError, re.error) as exc:
                    findings.append({"code": "SCHEMA", "package": pkg,
                                     "id": rid,
                                     "detail": f"{pkg}:{rid}: counterexample "
                                               f"is not evaluable: {exc}"})
                    continue
                if not ce_hits:
                    proves = ce.get("proves", "the rule")
                    findings.append({
                        "code": "NON_DISCRIMINATING", "package": pkg, "id": rid,
                        "detail": f"{pkg}:{rid} — the declared counterexample "
                                  f"{ce['path']!r}, which is supposed to prove "
                                  f"{proves}, does NOT violate this rule. A "
                                  f"rule that cannot reject its own "
                                  f"counterexample checks nothing."})
        packages.append({"package": pkg, "invariants": len(invs),
                         "counterexamples": sum(len(counterexamples(i))
                                                for i in invs),
                         "files": sum(1 for e in entries if not e.is_dir)})

    for pkg in find_stray_invariant_files(repo, set(enrolled)):
        findings.append({
            "code": "UNENROLLED", "package": pkg,
            "detail": f"{pkg}/{INVARIANTS_FILENAME} exists but {pkg} is not "
                      f"named in {ENROLLMENT_FILENAME}. An unenrolled invariant "
                      f"file is one nobody would miss — enroll it."})

    return {"gate": "package_invariants_check",
            "verdict": "PASS" if not findings else "FAIL",
            "enrolled": len(enrolled), "packages": packages,
            "findings": findings}


# --------------------------------------------------------------------------
# --touched: the human-facing half. Print the rules that bind what you edited.
# --------------------------------------------------------------------------
def render_touched(repo: Path, programs_dir: Path, paths: list[str]) -> str:
    enrolled = load_enrollment(programs_dir)
    hit = []
    for pkg in enrolled:
        if any(p == pkg or p.startswith(pkg + "/") for p in paths):
            hit.append(pkg)
    if not hit:
        return ""
    out = []
    for pkg in hit:
        f = repo / pkg / INVARIANTS_FILENAME
        if not f.is_file():
            out.append(f"  {pkg}: {INVARIANTS_FILENAME} MISSING (enrolled)")
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            out.append(f"  {pkg}: {INVARIANTS_FILENAME} unreadable: {exc}")
            continue
        out.append(f"  {pkg}/{INVARIANTS_FILENAME}")
        for inv in doc.get("invariants", []):
            out.append(f"    [{inv.get('id')}] {inv.get('statement')}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--programs-dir", default=None,
                    help="directory holding " + ENROLLMENT_FILENAME)
    ap.add_argument("--json", default=None)
    ap.add_argument("--touched", nargs="*", default=None,
                    help="repo-relative changed paths; print the invariants "
                         "binding the packages they belong to")
    a = ap.parse_args(argv)

    here = Path(__file__).resolve().parent
    programs_dir = Path(a.programs_dir).resolve() if a.programs_dir else here
    repo = Path(a.repo_root).resolve() if a.repo_root else here.parents[3]

    if not repo.is_dir():
        print(f"NORECORD: repo root {repo} is not a directory", file=sys.stderr)
        return 2
    if not (programs_dir / ENROLLMENT_FILENAME).is_file():
        print(f"NORECORD: {programs_dir / ENROLLMENT_FILENAME} not found",
              file=sys.stderr)
        return 2

    if a.touched is not None:
        text = render_touched(repo, programs_dir, list(a.touched))
        if text:
            print("Invariants binding the packages you touched:")
            print(text)
        else:
            print("  (no enrolled package touched)")
        return 0

    res = check(repo, programs_dir)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        # vibe-ic#1082 — the report appears under its final name only once it
        # is complete, so a reader cannot mistake a half-written verdict for a
        # finished one.
        write_json(a.json, res)

    if res["findings"]:
        print(f"FAIL: {len(res['findings'])} finding(s) across "
              f"{res['enrolled']} enrolled package(s):")
        for f in res["findings"]:
            print(f"  [{f['code']}] {f['detail']}")
        return 1
    total = sum(p["invariants"] for p in res["packages"])
    ces = sum(p["counterexamples"] for p in res["packages"])
    print(f"PASS: {total} invariant(s) declared by {res['enrolled']} enrolled "
          f"package(s); every rule obeyed by its own package, and all {ces} "
          f"declared counterexample(s) rejected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
