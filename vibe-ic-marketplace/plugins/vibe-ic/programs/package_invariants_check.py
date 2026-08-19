#!/usr/bin/env python3
"""package_invariants_check.py — every source package declares its own rules, in place.

VERDICT: BLOCKING. A failure here stops the gate run in
`tools/ci/repo_hygiene_gates.sh`, which is invoked by the PR check and by the
merge queue, so a package that violates, omits, or empties its declaration
cannot land.

WHY THIS EXISTS
===============
This repository's rules are strong and they are CENTRAL. `repo_hygiene_gates.sh`
carries ~60 of them in one list; ~500 `*_check.py` programs carry the rest. That
concentration is why the enforcement is good, and it is also the whole defect:
a contributor editing a directory cannot see, from that directory, the rule that
binds what they are editing. They have to already know to go somewhere else.

The measured cost of that distance is not hypothetical, and it is not about
style — it is about a rule reaching the code at all:

  * `tools/phase1_engine/tests/` was collected by NOTHING. Not by `run_tests.sh`,
    not by `pytest.ini` (one testpath, deliberately). It carried failing tests on
    main that no suite reported (vibe-ic#1391).
  * `mcp-eda/test/` — 201 tests — was named by the PR template and by CONTRIBUTING
    as a separate command, and by no runner at all. Prose in a checklist is not
    automation, so it ran when a human remembered.
  * the repo-level tests under `tools/` reached no selection at all, because the
    targeted selector is plugin-scoped by construction: 28 files / 552 tests
    gating nothing, until `tools/ci/test_repo_tools_tests_gate.py` was written to
    sit inside the very scope it defends.

In all three the knowledge that went missing is PER-PACKAGE knowledge — *this
directory has tests, and here is what runs them* — and in all three it was stored
centrally, where its absence looked like nothing at all.

WHAT A PACKAGE DECLARES, AND WHY EACH FIELD IS THERE
====================================================
`INVARIANTS.yaml`, at the package root, next to the code it constrains:

    package:     its own repo-relative directory. Checked against where the file
                 actually is, so a copied declaration is caught rather than
                 silently governing the wrong tree.
    owns:        the globs this declaration speaks for.
    tests:       root + the runner that collects it, and HOW that runner knows
                 about it. `collected_by_kind: named` (the default) is verified
                 by requiring the runner to name the tree outside a comment;
                 `complement` — for a runner that covers by construction, "every
                 tracked test file minus what a stage already runs" — is
                 verified by EXECUTING the enumerator and requiring it to list
                 the tree. `root: NONE` is allowed and REQUIRES a `reason`: an
                 undeclared absence is the failure mode above, a declared one is
                 a decision.
    invariants:  at least one, each with an `id`, a `statement` a human reads,
                 a machine-checkable `rule`, and the `why` that earned it.

The shape deliberately mirrors `skills/<name>/compliance.yaml`, which 63 skill
packages already carry and which the suite already audits for coverage. This is
that proven shape generalised to the source tree, not a second idiom competing
with it.

WHAT FAILS
==========
Eight named failures, because each is a different way for a local rule to become
decorative:

    VIOLATED           a file breaks an invariant its own package declares.
    MISSING            a derived package has no INVARIANTS.yaml.
    ORPHANED           an INVARIANTS.yaml sits where no package is, so the file
                       set cannot be padded with declarations that bind nothing.
    MISPLACED          `package:` disagrees with the file's own location.
    NO_INVARIANTS      the list is empty. Emptying the file must not read as
                       "this package is unconstrained" — that is exactly the
                       "absence reads as clean" defect, one level up.
    ZERO_DENOMINATOR   an invariant selects no file. A rule with no subject
                       passes forever and measures nothing (vibe-ic#447, #564).
    TESTS_UNCOLLECTED  the declared test root holds no tests, or the declared
                       complement enumerator does not list it (vibe-ic#1391).
    TESTS_UNNAMED      the declared runner never names the declared test root.
    UNDECLARED_SKIP    `root: NONE` with no reason — a silent decline.

MISSING and ORPHANED are the pair that makes the declaration load-bearing in
both directions: a package cannot lose its rules by deleting the file, and it
cannot gain a clean bill by scattering files where nothing lives.

WHAT A PACKAGE IS — DERIVED, NEVER LISTED
=========================================
Discovery reads the TRACKED tree and never the INVARIANTS.yaml files, because a
gate whose population comes from the very files it audits cannot see a deletion:
remove the file and the package stops existing, and the gate reports clean.

A directory is a package when it DIRECTLY holds at least `--min-sources` tracked
source files, excluding test roots, fixtures, vendored trees and the marketplace
templates. That threshold is a judgement and it is printed on every run: below
it sit the two `programs/` sub-directories and the per-skill `tests/` trees,
which the skills' own `compliance.yaml` coverage audit already governs.

Exit: 0 = every package declares and every declaration holds
      1 = at least one failure above
      2 = NOT DETERMINED (no package discovered, or no YAML reader available)
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

_NAME = "package_invariants_check"

DECL_NAME = "INVARIANTS.yaml"

#: Files that count towards a directory being a source package.
_SOURCE_SUFFIXES = (".py", ".sh", ".js", ".mjs", ".ts")

#: A path component anywhere in the path disqualifies the directory: a test root
#: is not a package, it is a package's tests, and fixtures are neither.
_EXCLUDED_COMPONENTS = frozenset({
    "tests", "test", "fixtures", "node_modules", "__pycache__",
})

#: Trees that ship as examples or scaffolding for OTHER repositories. Holding
#: them to this repo's invariants would constrain somebody else's code.
_EXCLUDED_PREFIXES = (
    "vibe-ic-marketplace/templates/",
    "vibe-ic-marketplace/reference-plugins/",
)

#: `forbid_regex`  no selected file may match `pattern`.
#: `require_regex`  every selected file must match `pattern`.
#: `paired_regex`   a selected file that matches `pattern` must ALSO match
#:                  `requires`. This is the "if you do X here you must also do
#:                  Y" shape, and it is the one several of this repo's dearest
#:                  rules actually have: a `gh api` call that sets `per_page`
#:                  must carry `--paginate`, a `subprocess.run` that reaches the
#:                  network must carry a `timeout`.
_RULES = ("forbid_regex", "require_regex", "paired_regex")


class Failure:
    def __init__(self, kind: str, where: str, detail: str) -> None:
        self.kind = kind
        self.where = where
        self.detail = detail

    def __str__(self) -> str:
        return f"    [{self.kind}] {self.where}\n        {self.detail}"


def _tracked_files(root: Path) -> list[str]:
    """Repo-relative paths of every tracked file, or [] if this is not a repo."""
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if proc.returncode != 0:
        return []
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def _is_excluded(rel_dir: str) -> bool:
    if any(rel_dir == p.rstrip("/") or rel_dir.startswith(p)
           for p in _EXCLUDED_PREFIXES):
        return True
    parts = [] if rel_dir == "." else rel_dir.split("/")
    return any(part in _EXCLUDED_COMPONENTS for part in parts)


def discover_packages(tracked: list[str], min_sources: int) -> dict[str, int]:
    """Directories that DIRECTLY hold >= min_sources tracked source files.

    Derived from the tracked tree alone. Nothing here consults INVARIANTS.yaml,
    which is what lets a deletion be seen.
    """
    counts: dict[str, int] = {}
    for rel in tracked:
        if not rel.endswith(_SOURCE_SUFFIXES):
            continue
        parent = str(Path(rel).parent)
        if _is_excluded(parent):
            continue
        counts[parent] = counts.get(parent, 0) + 1
    return {d: n for d, n in sorted(counts.items()) if n >= min_sources}


def _select(tracked_in_pkg: list[str], globs: list[str]) -> list[str]:
    """Package-relative names matching any glob, in tracked order.

    A glob may be negated with a leading `!`, which removes matches from the
    selection. That is deliberately a CLASS selector and not a per-file
    exemption list: a package whose tests sit beside its source (`tools/ci`)
    legitimately contains the literal strings its source forbids, and the only
    alternative to excluding that class is weakening the PATTERN — which is
    strictly worse, because a weakened pattern silently stops catching real
    source violations while an excluded glob is visible in the declaration and
    is counted out of the denominator this gate prints.
    """
    keep = [g for g in globs if not g.startswith("!")]
    drop = [g[1:] for g in globs if g.startswith("!")]
    out = []
    for name in tracked_in_pkg:
        if not any(fnmatch.fnmatch(name, g) for g in keep):
            continue
        if any(fnmatch.fnmatch(name, g) for g in drop):
            continue
        out.append(name)
    return out


def _as_list(value, field: str, where: str, fails: list[Failure]) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    fails.append(Failure("SCHEMA", where,
                         f"`{field}` must be a string or a list of strings"))
    return []


def _check_tests(root: Path, decl: dict, pkg: str,
                 fails: list[Failure]) -> None:
    """The declared test root is real, holds tests, and a named runner reaches it."""
    tests = decl.get("tests")
    if not isinstance(tests, dict):
        fails.append(Failure("SCHEMA", f"{pkg}/{DECL_NAME}",
                             "`tests:` must be a mapping with `root:`"))
        return

    troot = tests.get("root")
    if not isinstance(troot, str) or not troot:
        fails.append(Failure("SCHEMA", f"{pkg}/{DECL_NAME}",
                             "`tests.root:` must be a path or the string NONE"))
        return

    if troot == "NONE":
        reason = tests.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            fails.append(Failure(
                "UNDECLARED_SKIP", f"{pkg}/{DECL_NAME}",
                "`tests.root: NONE` needs a `reason:`. A package that declines "
                "to be tested must say so out loud; a silent decline reads "
                "downstream as 'nothing needed testing'."))
        return

    tdir = root / troot
    found = sorted(p.name for p in tdir.glob("test_*.py")) if tdir.is_dir() else []
    if not found:
        fails.append(Failure(
            "TESTS_UNCOLLECTED", f"{pkg}/{DECL_NAME}",
            f"declared tests.root `{troot}` holds no test_*.py"))
        return

    runner_rel = tests.get("collected_by")
    if not isinstance(runner_rel, str) or not runner_rel:
        fails.append(Failure(
            "TESTS_UNCOLLECTED", f"{pkg}/{DECL_NAME}",
            f"tests.root `{troot}` names no `collected_by:` runner. A test tree "
            f"nothing names is the vibe-ic#1391 defect: it runs when somebody "
            f"remembers."))
        return

    runner = root / runner_rel
    if not runner.is_file():
        fails.append(Failure(
            "TESTS_UNCOLLECTED", f"{pkg}/{DECL_NAME}",
            f"`collected_by: {runner_rel}` does not resolve to a file"))
        return

    kind = tests.get("collected_by_kind", "named")
    if kind not in ("named", "complement"):
        fails.append(Failure(
            "SCHEMA", f"{pkg}/{DECL_NAME}",
            f"`collected_by_kind: {kind!r}` must be `named` or `complement`"))
        return

    if kind == "complement":
        # The runner covers by CONSTRUCTION — "every tracked test file minus
        # what a stage already runs" — so it names no tree and a text match
        # would prove nothing. Ask it what it enumerates instead.
        proc = subprocess.run(
            [sys.executable, str(runner), "--repo", str(root)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=300, check=False)
        listed = proc.stdout.decode("utf-8", "replace").splitlines()
        if proc.returncode != 0:
            fails.append(Failure(
                "TESTS_UNCOLLECTED", f"{pkg}/{DECL_NAME}",
                f"`{runner_rel}` (declared as a complement enumerator) exited "
                f"{proc.returncode}; what it covers is NOT DETERMINED, which is "
                f"never a pass"))
            return
        hits = [p for p in listed if p.strip().startswith(troot.rstrip("/") + "/")]
        if not hits:
            fails.append(Failure(
                "TESTS_UNCOLLECTED", f"{pkg}/{DECL_NAME}",
                f"`{runner_rel}` enumerates {len(listed)} test file(s) and none "
                f"of them is under `{troot}`, so it does not reach this "
                f"package's {len(found)} test file(s)"))
        return

    # `named`: full-line comments are stripped first. A tree mentioned only in
    # a comment is exactly the vibe-ic#1391 shape — prose in a checklist is not
    # automation — and a match there would be a false certificate.
    text = "\n".join(
        line for line in runner.read_text(errors="replace").splitlines()
        if not line.lstrip().startswith("#"))
    # The runner may name the tree from the repo root or from its own working
    # directory, so accept any suffix of the declared path at a path-segment
    # boundary. `run_tests.sh` cds into the plugin and names
    # `tools/phase1_engine/tests`; `gatekeeper-land.sh` walks `tools` from the
    # root. Both reach the tree.
    parts = troot.split("/")
    candidates = ["/".join(parts[i:]) for i in range(len(parts))]
    candidates += ["/".join(parts[:i]) for i in range(1, len(parts))]
    if not any(re.search(rf"(?<![\w./-]){re.escape(c)}(?![\w-])", text)
               for c in candidates if c):
        fails.append(Failure(
            "TESTS_UNNAMED", f"{pkg}/{DECL_NAME}",
            f"`{runner_rel}` never names `{troot}` (nor an ancestor of it) "
            f"outside a comment, so the declaration that it collects these "
            f"{len(found)} test file(s) is not true. NOTE: this proves the "
            f"runner NAMES the tree, not that it executed it."))


def _check_invariants(root: Path, decl: dict, pkg: str, tracked_in_pkg: list[str],
                      fails: list[Failure]) -> tuple[int, int]:
    """Evaluate every declared invariant. Returns (invariants, files_examined)."""
    invs = decl.get("invariants")
    if not isinstance(invs, list) or not invs:
        fails.append(Failure(
            "NO_INVARIANTS", f"{pkg}/{DECL_NAME}",
            "declares no invariant. An empty declaration must not read as 'this "
            "package is unconstrained' — that is the absence-reads-as-clean "
            "defect this file exists to close."))
        return 0, 0

    n_files = 0
    for idx, inv in enumerate(invs):
        where = f"{pkg}/{DECL_NAME}"
        if not isinstance(inv, dict):
            fails.append(Failure("SCHEMA", where, f"invariant #{idx} is not a mapping"))
            continue
        iid = inv.get("id") or f"#{idx}"
        where = f"{pkg}/{DECL_NAME}:{iid}"

        for field in ("id", "statement", "rule", "pattern", "why", "severity"):
            if not isinstance(inv.get(field), str) or not str(inv.get(field)).strip():
                fails.append(Failure("SCHEMA", where, f"missing or empty `{field}:`"))
        rule = inv.get("rule")
        if rule not in _RULES:
            fails.append(Failure(
                "SCHEMA", where,
                f"`rule: {rule!r}` is not one of {', '.join(_RULES)}"))
            continue
        if inv.get("severity") not in ("BLOCKING", "ADVISORY"):
            fails.append(Failure(
                "SCHEMA", where,
                "`severity:` must be BLOCKING or ADVISORY, stated here and not "
                "left to a default"))
        try:
            rx = re.compile(str(inv.get("pattern")), re.MULTILINE)
        except re.error as exc:
            fails.append(Failure("SCHEMA", where, f"`pattern:` does not compile: {exc}"))
            continue

        rq = None
        if rule == "paired_regex":
            if not isinstance(inv.get("requires"), str) or not inv["requires"].strip():
                fails.append(Failure(
                    "SCHEMA", where,
                    "`rule: paired_regex` needs a `requires:` pattern — the "
                    "thing that must accompany the trigger"))
                continue
            try:
                rq = re.compile(inv["requires"], re.MULTILINE)
            except re.error as exc:
                fails.append(Failure("SCHEMA", where,
                                     f"`requires:` does not compile: {exc}"))
                continue

        globs = _as_list(inv.get("applies_to", []), "applies_to", where, fails)
        if not globs:
            continue
        selected = _select(tracked_in_pkg, globs)
        if not selected:
            fails.append(Failure(
                "ZERO_DENOMINATOR", where,
                f"`applies_to: {globs}` selects no tracked file in this package. "
                f"A rule with no subject holds forever and measures nothing."))
            continue
        n_files += len(selected)

        offenders: list[str] = []
        for name in selected:
            try:
                text = (root / pkg / name).read_text(errors="replace")
            except OSError as exc:
                fails.append(Failure("SCHEMA", where, f"cannot read {name}: {exc}"))
                continue
            if rule == "forbid_regex":
                m = rx.search(text)
                if m:
                    line = text.count("\n", 0, m.start()) + 1
                    offenders.append(f"{name}:{line}: {m.group(0).strip()[:90]}")
            elif rule == "require_regex":
                if not rx.search(text):
                    offenders.append(name)
            else:                                        # paired_regex
                m = rx.search(text)
                if m and not rq.search(text):
                    line = text.count("\n", 0, m.start()) + 1
                    offenders.append(f"{name}:{line}: {m.group(0).strip()[:90]}")

        if offenders:
            verb = {
                "forbid_regex": "matches a forbidden pattern",
                "require_regex": "does not carry the required pattern",
                "paired_regex": "triggers the pattern without carrying what it requires",
            }[rule]
            shown = "\n            ".join(offenders[:10])
            more = ("" if len(offenders) <= 10
                    else f"\n            +{len(offenders) - 10} more")
            fails.append(Failure(
                "VIOLATED", where,
                f"{len(offenders)} of {len(selected)} file(s) {verb}\n"
                f"        {inv.get('statement')}\n"
                f"        why: {inv.get('why')}\n"
                f"            {shown}{more}"))
    return len(invs), n_files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".", help="repository root")
    ap.add_argument("--min-sources", type=int, default=4,
                    help="tracked source files a directory needs to be a package")
    ap.add_argument("--list", action="store_true",
                    help="print the derived packages and exit")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    tracked = _tracked_files(root)
    packages = discover_packages(tracked, args.min_sources)

    if args.list:
        for pkg, n in packages.items():
            print(f"{n:5d}  {pkg}")
        print(f"{_NAME}: {len(packages)} package(s) at >= {args.min_sources} "
              f"tracked source file(s)")
        return 0

    if not packages:
        print(f"{_NAME}: NOT DETERMINED — discovered 0 source package(s) in "
              f"{root} (tracked files: {len(tracked)}). Nothing was examined, so "
              f"this is not a pass.")
        return 2

    try:
        import yaml  # type: ignore
    except ImportError:
        print(f"{_NAME}: NOT DETERMINED — no YAML reader available, so the "
              f"{len(packages)} declaration(s) could not be read. A declaration "
              f"that cannot be parsed is unverified, not satisfied.")
        return 2

    by_dir: dict[str, list[str]] = {}
    for rel in tracked:
        by_dir.setdefault(str(Path(rel).parent), []).append(Path(rel).name)

    fails: list[Failure] = []

    # ORPHANED — a declaration where no package is. Checked first so that the
    # file set cannot be padded with declarations that bind nothing.
    for rel in tracked:
        if Path(rel).name != DECL_NAME:
            continue
        owner = str(Path(rel).parent)
        if owner not in packages:
            fails.append(Failure(
                "ORPHANED", rel,
                f"`{owner}` is not a source package (it holds fewer than "
                f"{args.min_sources} tracked source files, or is excluded), so "
                f"this declaration binds nothing."))

    n_inv = 0
    n_files = 0
    for pkg in packages:
        decl_path = root / pkg / DECL_NAME
        if DECL_NAME not in by_dir.get(pkg, []):
            fails.append(Failure(
                "MISSING", f"{pkg}/{DECL_NAME}",
                f"this package holds {packages[pkg]} tracked source file(s) and "
                f"declares no invariants. Add {DECL_NAME} here, beside the code "
                f"it constrains."))
            continue
        try:
            decl = yaml.safe_load(decl_path.read_text()) or {}
        except Exception as exc:                       # yaml.YAMLError et al
            fails.append(Failure("SCHEMA", f"{pkg}/{DECL_NAME}",
                                 f"does not parse: {exc}"))
            continue
        if not isinstance(decl, dict):
            fails.append(Failure("SCHEMA", f"{pkg}/{DECL_NAME}",
                                 "top level must be a mapping"))
            continue

        if decl.get("package") != pkg:
            fails.append(Failure(
                "MISPLACED", f"{pkg}/{DECL_NAME}",
                f"declares `package: {decl.get('package')!r}` but sits in "
                f"`{pkg}`. A copied declaration governing the wrong tree is "
                f"worse than none."))

        _check_tests(root, decl, pkg, fails)
        i, f = _check_invariants(root, decl, pkg, by_dir.get(pkg, []), fails)
        n_inv += i
        n_files += f

    if fails:
        order = {k: i for i, k in enumerate(
            ("VIOLATED", "MISSING", "ORPHANED", "MISPLACED", "NO_INVARIANTS",
             "ZERO_DENOMINATOR", "TESTS_UNCOLLECTED", "TESTS_UNNAMED",
             "UNDECLARED_SKIP", "SCHEMA"))}
        fails.sort(key=lambda f: (order.get(f.kind, 99), f.where))
        print(f"{_NAME}: FAIL — {len(fails)} finding(s) across "
              f"{len(packages)} discovered package(s):")
        for f in fails:
            print(str(f))
        print(f"    Examined {len(packages)} package(s) at >= {args.min_sources} "
              f"tracked source file(s); {n_inv} invariant(s) over {n_files} "
              f"file selection(s).")
        return 1

    print(f"{_NAME}: PASS — {len(packages)} source package(s) each declare "
          f"{DECL_NAME}; {n_inv} invariant(s) held over {n_files} file "
          f"selection(s). Threshold: >= {args.min_sources} tracked source "
          f"file(s) directly in a directory.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
