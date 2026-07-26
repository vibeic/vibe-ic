#!/usr/bin/env python3
"""checker_execution_wiring_audit.py — a checker only its own TEST runs has
zero coverage of real inputs.

THIS GATE BLOCKS (rc=1) on a NEW test-only checker.

WHY THIS GATE EXISTS
--------------------
vibe-ic#381 stated the problem precisely while arguing about a different
one:

    "If the new checker is run against benchmark-data/, main is currently
     red by its own rule. If it is NOT run there, then the check does not
     cover the artefacts the issue was about."

Both halves matter, and the second one is the silent half. A checker can
be authored, reviewed, tested, merged, and cited as the fix for an issue
while NOTHING ever invokes it on a real input. Its own unit test proves
the logic works on a fixture the author wrote. It proves nothing about
production artefacts, because it never sees one.

That is the repo's recurring shape one more time: an empty result is
indistinguishable from a clean one. Here the emptiness is upstream of the
checker — it is never handed anything to judge.

WHAT IT MEASURES
----------------
For every `*_check.py` / `*_audit.py` under `programs/`, which of these
can actually INVOKE it:

    CI     a GitHub workflow step
    FLOW   the canonical flow definition (a gate entry)
    PROG   another program (import or subprocess)
    SKILL  a skill / agent / command document an agent follows
    TOOLS  a repo tool script
    TEST   its own unit tests

A checker whose ONLY runner is TEST is the finding.

WHY `SKILL` COUNTS AS A RUNNER. An agent following a skill document does
execute the program, so counting it avoids a false positive. It is the
weakest of the runners — it depends on an agent reaching that step — and
that weakness is deliberately NOT modelled here, because grading the
strength of a reference would need a judgement call, and a gate whose
output needs triage gets ignored.

WHAT IT DELIBERATELY DOES NOT COUNT AS A RUNNER
-----------------------------------------------
`programs/INDEX.md`, the architecture docs and the community backlog
YAMLs all NAME checkers without running any. Counting a catalogue as a
runner would let a checker be "wired" by being listed, which is the exact
paper-only wiring this gate exists to find.

METHOD NOTE — THE MATCHER MUST NOT ASSUME QUOTING
--------------------------------------------------
The first version of this measurement searched for the quoted stem and
the `.py` filename. The flow definition writes gate names BARE, so that
matcher reported 12 checkers as wired NOWHERE when every one of them was
in fact wired — a false accusation produced entirely by the matcher's own
assumption. Match the stem on WORD BOUNDARIES and nothing else.

chip-AGNOSTIC: operates on this repo's own layout. No design, PDK or
vendor literal appears here.

USAGE
-----
    python3 checker_execution_wiring_audit.py [--repo-root DIR]
                                              [--json OUT] [--write-baseline]

EXIT CODES
----------
    0 = PASS      1 = FAIL (new test-only checker, or baseline not shrunk)
    2 = SKIP (layout not found)
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Set

_BASELINE_NAME = "checker_execution_wiring_baseline.json"
# Matched as path COMPONENTS, never as substrings: `".git" in path` also
# swallows `.github/`, which would empty the CI haystack and make this gate
# systematically blind to the strongest form of wiring there is — while
# still printing a confident finding for every checker CI already runs.
_SKIP_PARTS = frozenset((".claude", "node_modules", ".git", "worktrees"))


def _strip_prose(path: Path, text: str) -> str:
    """Remove COMMENTS and DOCSTRINGS — prose names a checker, it never runs one.

    This is not a nicety. Adding a docstring to THIS file that named
    `skill_doc_section_present_check` while explaining why that entry is
    hard to wire made the entry look wired, and silently removed it from a
    register that may only shrink for a real reason. Any program whose
    comments discuss another checker would do the same.

    String LITERALS are kept: `subprocess.run([..., "foo_check.py"])` is a
    real invocation. Only bare-expression strings (docstrings) are dropped.
    """
    if path.suffix == ".py":
        try:
            import ast
            import io
            import tokenize
            import warnings
            with warnings.catch_warnings():
                # Some sources carry invalid escape sequences in docstrings;
                # that is their own (separate) defect, not this gate's news.
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(text)
            drop = set()
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if not isinstance(body, list) or not body:
                    continue
                first = body[0]
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    drop.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
            lines = text.splitlines()
            kept = [("" if i + 1 in drop else ln) for i, ln in enumerate(lines)]
            src = "\n".join(kept)
            try:
                toks = tokenize.generate_tokens(io.StringIO(src).readline)
                return "\n".join(t.string for t in toks
                                 if t.type != tokenize.COMMENT)
            except (tokenize.TokenError, IndentationError, SyntaxError):
                return src
        except (SyntaxError, ValueError, RecursionError):
            # Unparseable source: keep it whole. Over-counting a reference is
            # the safe direction for an ACCUSATION, and this branch is loud
            # in the report rather than silent.
            return text
    if path.suffix in (".yml", ".yaml", ".sh"):
        return "\n".join(ln for ln in text.splitlines()
                         if not ln.lstrip().startswith("#"))
    return text


def _rel_parts(f: Path, root: Path):
    """Path components BELOW `root`.

    Third time this file has had the same bug. `_SKIP_PARTS` is meant to skip
    a nested `.claude/worktrees/` copy INSIDE the checkout; matched against
    the ABSOLUTE parts it also matches the checkout's own ancestors, so a
    repo that happens to live under `.../.claude/worktrees/<name>/` has EVERY
    haystack file skipped. Measured: every haystack empty -> `no runner at
    all: 494`, i.e. a confident false accusation against every checker in the
    repo, from a matcher's own assumption. Anchor to the scan root.
    """
    try:
        return set(f.resolve().relative_to(root).parts)
    except (ValueError, OSError):
        return set(f.parts)


def _read(paths, root: Path) -> Dict[str, str]:
    root = root.resolve()
    out: Dict[str, str] = {}
    for f in paths:
        s = str(f)
        if _SKIP_PARTS & _rel_parts(f, root):
            continue
        try:
            out[s] = _strip_prose(f, f.read_text(errors="replace"))
        except OSError:
            continue
    return out


def _haystacks(plugin: Path, repo_root: Path) -> Dict[str, Dict[str, str]]:
    programs = plugin / "programs"
    pys = list(programs.rglob("*.py"))
    is_test = lambda p: "/tests/" in str(p) or p.name.startswith("test_")
    return {
        "CI": _read(list((repo_root / ".github").rglob("*.yml"))
                    + list((repo_root / ".github").rglob("*.yaml")), repo_root),
        "FLOW": _read(list((plugin / "flow").rglob("*.yml"))
                      + list((plugin / "flow").rglob("*.yaml")), repo_root),
        "TOOLS": _read(list((repo_root / "tools").rglob("*.py"))
                       + list((repo_root / "tools").rglob("*.sh")), repo_root),
        "SKILL": _read(list((plugin / "skills").rglob("*.md"))
                       + list((plugin / "agents").rglob("*.md"))
                       + list((plugin / "commands").rglob("*.md")), repo_root),
        "PROG": _read([p for p in pys if not is_test(p)], repo_root),
        "TEST": _read([p for p in pys if is_test(p)]
                      + list((plugin / "tests").rglob("*.py")), repo_root),
    }


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def runners(stem: str, hay: Dict[str, Dict[str, str]], self_path: str) -> Set[str]:
    """Which categories contain a WORD-BOUNDARY reference to `stem`.

    Word boundaries only — never assume the reference is quoted or carries
    the `.py` suffix (the flow definition writes gate names bare).

    Implemented by tokenising each file into maximal `[A-Za-z0-9_]+` runs
    and testing membership. That is EQUIVALENT to the word-boundary regex —
    `stem` is such a token exactly when it is surrounded by characters
    outside the class — and it turns 485 x ~2900 searches into one pass.
    """
    found: Set[str] = set()
    for kind, files in hay.items():
        for path, tokens in files.items():
            if path != self_path and stem in tokens:
                found.add(kind)
                break
    return found


def _tokenise(hay: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, Set[str]]]:
    return {k: {p: set(_TOKEN_RE.findall(t)) for p, t in v.items()}
            for k, v in hay.items()}


def audit(plugin: Path, repo_root: Path) -> dict:
    programs = plugin / "programs"
    checkers = sorted([p.name for p in programs.glob("*_check.py")]
                      + [p.name for p in programs.glob("*_audit.py")])
    hay = _tokenise(_haystacks(plugin, repo_root))
    test_only: List[str] = []
    unrun: List[str] = []
    for name in checkers:
        r = runners(name[:-3], hay, str(programs / name))
        if not r:
            unrun.append(name)
        elif r == {"TEST"}:
            test_only.append(name)
    return {"program": "checker_execution_wiring_audit",
            "checkers": len(checkers),
            "test_only": sorted(test_only),
            "no_runner_at_all": sorted(unrun),
            "passed": True}


def measure_triage(programs: Path, names: List[str], timeout: int = 200) -> Dict[str, str]:
    """Run each recorded checker with NO arguments and record what happened.

    EMPIRICAL rather than static, for a reason this repo keeps re-learning.
    A first version of this annotation read `required=True` out of the
    argparse calls; `skill_doc_section_present_check` enforces `--marker`
    manually AFTER parsing (`action="append", default=[]`), so the static
    read reported only `--doc` and made the entry look one flag away from
    wireable when it is a parameterised helper. Running it says rc=2 and
    prints the real reason.

    A bare register invites the worst repair — deleting the test so the
    entry disappears — so every entry has to carry what was found when it
    was investigated, and that finding has to be REGENERABLE rather than a
    one-off someone typed in.
    """
    import subprocess
    out: Dict[str, str] = {}
    for name in names:
        p = programs / name
        try:
            r = subprocess.run([__import__("sys").executable, str(p)],
                               capture_output=True, text=True, timeout=timeout)
            rc, blob = r.returncode, (r.stderr or "") + "\n" + (r.stdout or "")
        except subprocess.TimeoutExpired:
            out[name] = f"no-arg run TIMED OUT after {timeout}s"
            continue
        except OSError as e:
            out[name] = f"no-arg run could not start: {e}"
            continue
        why = next((ln.strip() for ln in blob.splitlines()
                    if ln.strip() and not ln.strip().startswith(("usage:", "  ", "\t"))),
                   "(no output)")
        verdict = {0: "rc=0 runs green with no arguments",
                   1: "rc=1 FAILs with no design to judge",
                   2: "rc=2 SKIPs / refuses without its input"}.get(rc, f"rc={rc}")
        out[name] = f"{verdict} — {why[:180]}"
    return out


def _load_baseline(p: Path):
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    k = d.get("known") if isinstance(d, dict) else d
    return sorted({str(x) for x in k}) if isinstance(k, list) else None


def _resolve(repo_root: Path):
    plugin = repo_root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    if (plugin / "programs").is_dir():
        return plugin
    here = Path(__file__).resolve().parent.parent
    return here if (here / "programs").is_dir() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--scope-expanded", metavar="REASON",
                    help="permit a GROWING baseline for this write, because "
                         "the audit now LOOKS at more than it did (a wider "
                         "scope finds pre-existing debt; that is not a "
                         "regression). Requires a reason >=30 chars, recorded "
                         "in the baseline beside the previous size")
    ap.add_argument("--refresh-triage", action="store_true",
                    help="with --write-baseline: re-MEASURE each entry by "
                         "running it with no arguments (opt-in; it executes "
                         "every recorded program, so it is off the gate path)")
    a = ap.parse_args(argv)

    here = Path(__file__).resolve()
    root = (Path(a.repo_root).resolve() if a.repo_root
            else next((b for b in here.parents
                       if (b / "vibe-ic-marketplace").is_dir()), here.parents[3]))
    plugin = _resolve(root)
    if plugin is None:
        print("[SKIP] checker_execution_wiring_audit: plugin layout not found.")
        return 2

    rep = audit(plugin, root)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=2) + "\n")
    bl = Path(a.baseline) if a.baseline else here.parent / _BASELINE_NAME
    now = sorted(rep["test_only"] + rep["no_runner_at_all"])

    if a.write_baseline:
        if a.scope_expanded is not None and len(a.scope_expanded.strip()) < 30:
            print("[FAIL] --scope-expanded needs a real reason (>=30 chars) "
                  "naming what the audit now looks at that it did not before.")
            return 1
        prev = _load_baseline(bl)
        if (prev is not None and len(now) > len(prev)
                and a.scope_expanded is None):
            print(f"[FAIL] refusing to GROW the baseline "
                  f"({len(prev)} -> {len(now)}): a checker losing its only "
                  f"real runner is a regression, not a fact to record. If the "
                  f"audit now LOOKS at more than it did, say so with "
                  f"--scope-expanded '<why>'.")
            return 1
        prev_triage = {}
        if bl.is_file():
            try:
                prev_triage = json.loads(bl.read_text()).get("triage") or {}
            except (OSError, ValueError):
                prev_triage = {}
        if a.refresh_triage:
            prev_triage = measure_triage(plugin / "programs", now)
        bl.write_text(json.dumps(
            {"_comment": ("Checkers that NOTHING but their own unit test ever "
                          "runs (vibe-ic#381). MAY ONLY SHRINK — each entry is "
                          "a checker with zero coverage of real inputs. "
                          "`triage` records why an entry is still here; the "
                          "wrong repair is to delete the test so the entry "
                          "disappears."),
             "previous_size": None if prev is None else len(prev),
             "scope_expanded": a.scope_expanded,
             "known": now,
             "triage": {k: v for k, v in prev_triage.items() if k in now}},
            indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {bl} ({len(now)} entr(ies))")
        return 0

    print(f"checker_execution_wiring_audit: {rep['checkers']} checker(s)")
    base = _load_baseline(bl)
    new = [c for c in now if base is None or c not in set(base)]
    paid = [c for c in (base or []) if c not in set(now)]
    if rep["no_runner_at_all"]:
        print(f"  no runner at all: {len(rep['no_runner_at_all'])}")
    if paid:
        print(f"[FAIL] {len(paid)} recorded checker(s) now HAVE a real runner "
              f"— shrink the baseline so it cannot become permission:")
        for c in paid:
            print(f"   (resolved) {c}")
    if new:
        print(f"[FAIL] {len(new)} checker(s) that NOTHING but their own test "
              f"runs — a fixture the author wrote proves the logic, never the "
              f"artefacts:")
        for c in new:
            print(f"   {c}")
    if new or paid:
        return 1
    print(f"[PASS] no NEW test-only checker ({len(now)} recorded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
