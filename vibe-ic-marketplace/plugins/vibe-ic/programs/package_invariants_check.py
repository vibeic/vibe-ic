#!/usr/bin/env python3
"""package_invariants_check.py — the rule lives in the directory it binds.

THIS GATE BLOCKS (rc=1) on a violated, vacuous, toothless, missing or
unregistered package invariant, and REFUSES (rc=2) rather than passing when it
could not establish a population.

WHY THIS EXISTS
---------------
The deepseek-harness source study measured that harness at 99f6f02fe -- 54
top-level packages, 226 leaf packages, 219 `invariant.ts` files, one beside
each package -- and split the verdict on us in two. (The study itself is
`docs/research/2026-08-19-deepseek-harness-source-study.md`, authored in a
sibling change; every upstream file:line cited here was re-read in the clone
at that revision and stands on its own.)
We are AHEAD on enforcement and BEHIND on LOCALITY: our rules live centrally,
in `programs/*_check.py` and in `tools/ci/repo_hygiene_gates.sh` and in skill
documents, so a contributor editing `mcp-eda/src/lib/pnr_antenna.mjs` cannot
see the rule that binds it without going somewhere else and knowing to look.

This checker closes the locality half WITHOUT moving a single checker. The
flat `programs/*.py` namespace stays flat -- and it is what D1/D2/D3,
`gate_discloses_denominator_check` and `checker_execution_wiring_audit` all
grep. What moves next to the code is the DECLARATION.

Design note, with the measurements and the rejected candidates:
`docs/PER_PACKAGE_INVARIANTS.md`.

THE UNIT, AND WHY OWNERSHIP IS NEAREST-ANCESTOR
------------------------------------------------
A package is a directory holding an `INVARIANTS.yaml`. A tracked file is owned
by the NEAREST declaring ancestor directory. Nearest-ancestor is single-valued
by construction, so "two packages claim one file" -- the case their
`invariants/src/index.ts:140-142` has to throw on -- cannot be expressed here.
An explicit `owns:` list would restate what `applies_to` already says and give
the two of them somewhere to disagree.

WHY `counterexample` IS MANDATORY
----------------------------------
A `require` rule that passes has matched its regex in EVERY file of a non-empty
population, so the population itself proves the regex matches real code. A
`forbid` rule that passes has matched NOTHING -- and zero matches is both the
healthy state of a prohibition and byte-identical to a typo in the regex.
Nothing in the population can tell those apart.

So every rule ships text it MUST reject, and that is re-proved on every run.
A rule that does not reject its own counterexample is TOOTHLESS and refused.
This is "an unmeasured thing reads as a measured zero" one level up: a check
that found nothing must show it was capable of finding something.

WHY EVERY SHIPPED REGEX IS COMMENT-ANCHORED
--------------------------------------------
Measured while selecting rules: `execSync(` occurs in
`mcp-eda/src/lib/shell_safety.mjs:5` -- inside the `//` block that explains the
injection bug it exists to prevent, and `git status --porcelain` occurs in
`tools/ci/*.py` only inside a `#` comment. A rule that fires on the
DOCUMENTATION of a hazard is a rule people delete, and scoping the population
to dodge those files would be shaping the rule to fit its own population. The
declarations therefore anchor with `(?m)^(?![ \t]*(?:#|//))`, which is plain
`re` and needs no language awareness in this file.

WHAT A MISSING DECLARATION MEANS
---------------------------------
Not "no constraints". `package_invariants_registry.json` lives OUTSIDE every
declared package, so deleting a package's directory cannot delete the record
that it owes a declaration; a registered package with no file is rc 1 MISSING,
and a declaration the registry does not name is rc 1 UNREGISTERED (exact-set
equality, both directions). `MIN_REGISTERED_PACKAGES` below makes SHRINKING the
registry a refusal until someone edits this file, and the test pins the exact
set. The residual is stated in the design note rather than implied: an author
willing to make all three edits can still retire a package.

WHAT ZERO MEANS
---------------
Their `scripts/package-invariants.ts:38` discovers owners with a hardcoded
depth-2 glob; an empty root yields 0 owners, the loop body never runs, and
`verify-package-invariants.ts:21` prints `0 hand-owned package companion(s)
conform.` and exits 0. Here, no git index / an unreadable registry / zero
declarations discovered is rc 2 NOT CHECKED, and the gate is wired with plain
`run`, not `run_tolerating_uncheckable`, so rc 2 fails the suite. A run that
could not run is not a pass.

EXIT CODES
----------
    0   every declared invariant held over a disclosed, non-empty population
    1   a real finding (see the table in the design note)
    2   NOT CHECKED -- no git index, unreadable registry, or zero declarations
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked
from _atomic_artefact import write_json as atomic_write_json  # vibe-ic#1082 (helper from PR #1094)

DECLARATION_NAME = "INVARIANTS.yaml"
REGISTRY_REL = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/package_invariants_registry.json"
)

# The RATCHET. Shrinking the registry below this is a refusal, so retiring a
# package costs an edit to enforcement code -- which is also what makes
# `ci_targeted_test_select` select this checker's test. Raise it when a package
# is added; lowering it is the visible, reviewable act it should be.
#
# `--min-registered-packages` overrides it, and exists for ONE caller: the test
# suite, whose synthetic repositories hold one or two packages and would
# otherwise trip a floor written for this tree. The gate wiring in
# `tools/ci/repo_hygiene_gates.sh` passes no such flag, and
# `test_the_hygiene_wiring_does_not_lower_the_ratchet` asserts it never starts
# to -- an escape hatch nobody checks is the hatch that gets used.
MIN_REGISTERED_PACKAGES = 7

MAX_DECLARATION_BYTES = 64 * 1024
MAX_SUBJECT_BYTES = 4 * 1024 * 1024

_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,79}\Z")
_REQUIRED_KEYS = ("id", "rule", "applies_to", "counterexample")


class Refusal(Exception):
    """Nothing could be certified -- rc 2, never a verdict."""


def _glob_to_regex(glob: str) -> re.Pattern:
    """Translate a package-relative glob. `*` does NOT cross `/`; `**/` does.

    `fnmatch` is not used because its `*` matches `/`, which would silently
    make `*.py` recursive and hand a package files a deeper package owns.
    """
    out = ["\\A"]
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    out.append("\\Z")
    return re.compile("".join(out))


def _tracked_files(root: Path) -> list[str]:
    """The population is the git INDEX, not the filesystem.

    A filesystem walk would sweep in untracked scratch -- the class measured at
    1078 leftovers in `_gate_dispatch.sh:69-71` -- and turn a dirty developer
    tree into a gate finding. A producer that BROKE must not reach the caller
    as "the corpus is empty", so a failed `git ls-files` is a Refusal (rc 2).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, check=False,
        )
    except OSError as exc:                                   # pragma: no cover
        raise Refusal(f"could not run git ls-files under {root}: {exc}")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise Refusal(
            f"git ls-files failed under {root} (rc {proc.returncode})"
            + (f": {err[-1]}" if err else "")
        )
    files = [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]
    if not files:
        raise Refusal(f"git ls-files listed no tracked file under {root}")
    return files


def _read_registry(root: Path) -> list[str]:
    path = root / REGISTRY_REL
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Refusal(f"registry unreadable at {REGISTRY_REL}: {exc}")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Refusal(f"registry is not valid JSON at {REGISTRY_REL}: {exc}")
    if not isinstance(doc, dict) or not isinstance(doc.get("packages"), list):
        raise Refusal(f"registry has no `packages` array at {REGISTRY_REL}")
    packages = doc["packages"]
    if not all(isinstance(p, str) and p for p in packages):
        raise Refusal(f"registry `packages` holds a non-string at {REGISTRY_REL}")
    return packages


def _load_declaration(root: Path, decl_rel: str, findings: list[str]) -> dict | None:
    import yaml

    path = root / decl_rel
    try:
        raw = path.read_bytes()
    except OSError as exc:
        findings.append(f"{decl_rel}: unreadable ({exc})")
        return None
    if len(raw) > MAX_DECLARATION_BYTES:
        findings.append(
            f"{decl_rel}: {len(raw)} bytes exceeds the {MAX_DECLARATION_BYTES} "
            "byte declaration ceiling"
        )
        return None
    try:
        doc = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        findings.append(f"{decl_rel}: not parseable as YAML ({exc})")
        return None
    if not isinstance(doc, dict):
        findings.append(f"{decl_rel}: top level is not a mapping")
        return None
    return doc


def _violating_lines(pattern: re.Pattern, text: str, forbid: bool) -> list[int]:
    """Line numbers a rule objects to. A `require` miss is reported as line 0."""
    if forbid:
        return sorted({text[: m.start()].count("\n") + 1
                       for m in pattern.finditer(text)})
    return [] if pattern.search(text) else [0]


def _check(root: Path, min_packages: int | None = None
           ) -> tuple[int, list[str], dict[str, int]]:
    floor = MIN_REGISTERED_PACKAGES if min_packages is None else min_packages
    findings: list[str] = []
    tracked = _tracked_files(root)
    registered = _read_registry(root)

    declared: dict[str, str] = {}          # package dir -> declaration path
    for rel in tracked:
        p = PurePosixPath(rel)
        if p.name == DECLARATION_NAME:
            declared[str(p.parent)] = rel
    if not declared:
        raise Refusal(
            f"no {DECLARATION_NAME} is tracked under {root}: the population is "
            "empty, which is NOT the same as clean"
        )

    # --- the register, both directions -------------------------------------
    if len(registered) < floor:
        findings.append(
            f"RATCHET: the registry names {len(registered)} package(s); "
            f"the floor is {floor}. Retiring a "
            "package is a deliberate edit to package_invariants_check.py, not a "
            "deletion that reads as 'no constraints'."
        )
    for pkg in sorted(set(registered)):
        if pkg not in declared:
            findings.append(
                f"MISSING: registry names `{pkg}` but {pkg}/{DECLARATION_NAME} "
                "is not tracked -- a package that owes a declaration and has "
                "none is a refusal, not an absence of constraints"
            )
    for pkg in sorted(declared):
        if pkg not in registered:
            findings.append(
                f"UNREGISTERED: {declared[pkg]} exists but `{pkg}` is absent "
                f"from {REGISTRY_REL}"
            )

    # --- ownership: nearest declaring ancestor ------------------------------
    owner_of: dict[str, str] = {}
    for rel in tracked:
        if PurePosixPath(rel).name == DECLARATION_NAME:
            continue
        best = ""
        for pkg in declared:
            if rel.startswith(pkg + "/") and len(pkg) > len(best):
                best = pkg
        if best:
            owner_of[rel] = best
    owned_by: dict[str, list[str]] = {pkg: [] for pkg in declared}
    for rel, pkg in owner_of.items():
        owned_by[pkg].append(rel)

    seen_ids: dict[str, str] = {}
    n_rules = 0
    n_examined = 0

    for pkg in sorted(declared):
        decl_rel = declared[pkg]
        doc = _load_declaration(root, decl_rel, findings)
        if doc is None:
            continue
        stated = doc.get("package")
        if stated != pkg:
            findings.append(
                f"{decl_rel}: `package: {stated!r}` disagrees with its own "
                f"directory `{pkg}`"
            )
        rules = doc.get("invariants")
        if not isinstance(rules, list) or not rules:
            findings.append(f"{decl_rel}: `invariants` is missing or empty")
            continue
        for idx, rule in enumerate(rules):
            n_rules += 1
            where = f"{decl_rel}[{idx}]"
            if not isinstance(rule, dict):
                findings.append(f"{where}: invariant is not a mapping")
                continue
            missing = [k for k in _REQUIRED_KEYS if not rule.get(k)]
            if missing:
                findings.append(f"{where}: missing {', '.join(missing)}")
                continue
            rid = rule["id"]
            if not isinstance(rid, str) or not _ID_RE.fullmatch(rid):
                findings.append(
                    f"{where}: id {rid!r} is not lower-kebab, 3-80 chars")
                continue
            where = f"{pkg}: {rid}"
            if rid in seen_ids:
                findings.append(
                    f"{where}: id already owned by {seen_ids[rid]} -- an id "
                    "names one rule, and two owners cannot be attributed")
                continue
            seen_ids[rid] = pkg

            has_forbid, has_require = "forbid" in rule, "require" in rule
            if has_forbid == has_require:
                findings.append(
                    f"{where}: declare exactly one of `forbid:` / `require:` "
                    f"(got forbid={has_forbid}, require={has_require})")
                continue
            forbid = has_forbid
            raw_pat = rule["forbid"] if forbid else rule["require"]
            if not isinstance(raw_pat, str) or not raw_pat:
                findings.append(f"{where}: the pattern is empty")
                continue
            try:
                pattern = re.compile(raw_pat)
            except re.error as exc:
                findings.append(f"{where}: pattern does not compile ({exc})")
                continue

            counter = rule["counterexample"]
            if not isinstance(counter, str) or not counter.strip():
                findings.append(f"{where}: counterexample is empty")
                continue
            if not _violating_lines(pattern, counter, forbid):
                findings.append(
                    f"{where}: TOOTHLESS -- the rule ACCEPTS its own "
                    "counterexample, so a passing population is no evidence "
                    "the pattern discriminates")
                continue

            applies = rule["applies_to"]
            if not isinstance(applies, list) or not all(
                    isinstance(g, str) and g for g in applies):
                findings.append(f"{where}: `applies_to` is not a list of globs")
                continue
            excludes = rule.get("excludes") or []
            if not isinstance(excludes, list) or not all(
                    isinstance(g, str) and g for g in excludes):
                findings.append(f"{where}: `excludes` is not a list of globs")
                continue
            inc = [_glob_to_regex(g) for g in applies]
            exc = [_glob_to_regex(g) for g in excludes]

            population = []
            for rel in sorted(owned_by[pkg]):
                sub = rel[len(pkg) + 1:]
                if any(r.match(sub) for r in inc) and not any(
                        r.match(sub) for r in exc):
                    population.append(rel)
            if not population:
                findings.append(
                    f"{where}: VACUOUS -- applies_to {applies} selects ZERO of "
                    f"the {len(owned_by[pkg])} file(s) this package owns")
                continue

            for rel in population:
                n_examined += 1
                try:
                    blob = (root / rel).read_bytes()
                except OSError as exc:
                    findings.append(f"{where}: {rel} unreadable ({exc})")
                    continue
                if len(blob) > MAX_SUBJECT_BYTES:
                    findings.append(
                        f"{where}: {rel} is {len(blob)} bytes, over the "
                        f"{MAX_SUBJECT_BYTES} byte ceiling -- NOT examined")
                    continue
                text = blob.decode("utf-8", "replace")
                for line in _violating_lines(pattern, text, forbid):
                    findings.append(
                        f"{where}: {rel}:{line} violates -- {rule['rule'].strip()}"
                        if line else
                        f"{where}: {rel} violates (required pattern absent) -- "
                        f"{rule['rule'].strip()}")

    counts = {
        "packages": len(declared),
        "registered": len(set(registered)),
        "invariants": n_rules,
        "owned_files": sum(len(v) for v in owned_by.values()),
        "files_examined": n_examined,
        "tracked_files": len(tracked),
    }
    return (1 if findings else 0), findings, counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".",
                    help="repository root to check (default: cwd)")
    ap.add_argument("--json", dest="json_out",
                    help="also write the machine record here")
    ap.add_argument("--min-registered-packages", type=int, default=None,
                    dest="min_packages",
                    help="override the shrink ratchet; for the test suite's "
                         "synthetic repositories only, never for the gate")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    try:
        rc, findings, counts = _check(root, args.min_packages)
    except Refusal as exc:
        print(f"package_invariants: NOT CHECKED -- {exc}", file=sys.stderr)
        print("package_invariants: rc 2 -- nothing was certified. A run that "
              "could not run is not a pass.", file=sys.stderr)
        if args.json_out:
            atomic_write_json(args.json_out,
                              {"verdict": "NOT_CHECKED", "reason": str(exc)})
        return 2

    disclosure = (
        "package_invariants: {packages} package(s), {invariants} invariant(s), "
        "{owned_files} owned file(s), {files_examined} file-rule pair(s) "
        "examined, out of {tracked_files} tracked".format(**counts)
    )
    if findings:
        for f in findings:
            print(f"  FAIL {f}")
        print(f"[FAIL] {len(findings)} finding(s). {disclosure}")
    else:
        print(f"[PASS] every declared invariant held. {disclosure}")
    if args.json_out:
        atomic_write_json(args.json_out,
                          {"verdict": "FAIL" if findings else "PASS",
                           "findings": findings, **counts})
    return rc


if __name__ == "__main__":
    sys.exit(main())
