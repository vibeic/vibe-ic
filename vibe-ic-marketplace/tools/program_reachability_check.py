#!/usr/bin/env python3
"""Wave 81 — program reachability auditor.

Scans every ``*.py`` under ``plugins/vibe-ic/programs/`` and reports
any program that is not referenced from anywhere in the tree:

* Other Python files via ``from <name> import`` / ``import <name>``.
* ``flow/*.yaml|yml`` ``command:`` invocations.
* ``hooks/*``, ``*.sh`` and ``commands/*.md`` shell-style references.

Helpers (those whose name starts with ``_``) are only required to be
reachable via ``import`` from another Python file — YAML/shell entries
do not invoke helpers directly. Entry-point programs must be reachable
via either Python import or YAML/shell command.

A program with **zero hits** is flagged ``POTENTIALLY_UNREACHABLE``.
The catch is conservative: a single appearance of the bare module
stem (whitespace-bounded) anywhere in the tree counts as reachable.

Exit code 0 always (this is an audit / warning tool — `--strict`
makes unreachable programs FAIL).

Usage::

    python3 vibe-ic-marketplace/tools/program_reachability_check.py
    python3 vibe-ic-marketplace/tools/program_reachability_check.py --json out.json
    python3 vibe-ic-marketplace/tools/program_reachability_check.py --strict
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

#: The tree under audit. Module-level because 22 call sites read it, and
#: rebindable because WHICH CODE RUNS and WHICH TREE IT JUDGES are two
#: different questions.
#:
#: THEY WERE ONE QUESTION UNTIL 2026-08-27, AND IT COST A LANDING. This file
#: derived its tree from `__file__` and took no argument, so the hygiene gate
#: had no way to say "run THIS copy against THAT tree" and was declared as
#:
#:     run "every program is reachable" "$ROOT" python3 \
#:         "$ROOT/vibe-ic-marketplace/tools/program_reachability_check.py" --strict
#:
#: `$ROOT` is the SUBJECT (`VIBEIC_SUBJECT_ROOT`), not the runtime. So on the
#: BASE arm of an A/B verification the gate ran the BASE tree's copy — the one
#: without the indexing rewrite, which does not finish in ten minutes. Measured
#: on 8HD-7: five of them at 5000-6200 s each, load average 292, sshd unable to
#: emit a banner. The base arm never completed, so no differential existed, so
#: the change carrying the fix could not land — the repair was trapped inside
#: the verification it was repairing.
#:
#: With `--root` the gate names the runtime's program and the subject's tree
#: SEPARATELY, which is what every other gate in that lane already does through
#: `$PG` + `"$ROOT"`, and both arms then run the fast code.
ROOT = Path(__file__).resolve().parents[2]  # AI_IC_design/
PLUGIN = ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
PROGRAMS = PLUGIN / "programs"


def _bind_root(root: Path) -> None:
    """Point this audit at *root* instead of at its own location."""
    global ROOT, PLUGIN, PROGRAMS
    ROOT = Path(root).resolve()
    PLUGIN = ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    PROGRAMS = PLUGIN / "programs"
    _TEXT_CACHE.clear()


def _list_programs() -> list[Path]:
    """Every *.py program file (helpers included). Skip __init__/__main__."""
    out = []
    for p in sorted(PROGRAMS.glob("*.py")):
        if p.name in ("__init__.py", "__main__.py"):
            continue
        out.append(p)
    return out


def _is_helper(name: str) -> bool:
    return name.startswith("_")


def _python_files(skip) -> list[Path]:
    """All .py under the plugin tree except `skip` (the program being checked).

    `skip=None` returns the WHOLE corpus; `audit` takes it once and excludes
    each program from its own row by identity, which is the same exclusion done
    once instead of 1291 times."""
    out = []
    _skip = skip.resolve() if skip is not None else None
    for p in PLUGIN.rglob("*.py"):
        # don't count a program's references to itself
        if _skip is not None and p.resolve() == _skip:
            continue
        # don't count files inside __pycache__
        if "__pycache__" in p.parts:
            continue
        out.append(p)
    return out


def _yaml_files() -> list[Path]:
    out = []
    for ext in ("*.yaml", "*.yml"):
        out.extend((PLUGIN / "flow").glob(ext))
    return out


def _shell_and_md_files() -> list[Path]:
    """Every shell / markdown venue that can invoke a program.

    THE SCOPE USED TO STOP AT `PLUGIN`, AND THAT IS WHERE THE WIRING ISN'T.
    `PLUGIN.rglob("*.sh")` cannot see `tools/ci/repo_hygiene_gates.sh`, which
    lives at REPO ROOT — and that file is where the landing lane declares its
    gates, executed by `tools/gatekeeper-land.sh`. Measured on the campaign that
    took the orphan count 163 -> 0: **28 of its 30 shell closures landed in that
    one file**, so this auditor was structurally blind to the venue that carried
    most of the real wiring.

    The symptom it produced is a false ORPHAN, not a false pass, which is why it
    survived: `gatekeeper_prepare_landing` is invoked from
    `tools/gatekeeper-land.sh` and its only referrers INSIDE PLUGIN are
    `INDEX.md` and four of its own tests. An auditor that reports a wired
    program as unreachable teaches its reader to discount it.

    Repo root is derived from PLUGIN rather than from this file's own location,
    so a synthetic tree with no `tools/` simply contributes nothing.
    """
    out: list[Path] = []
    if (PLUGIN / "hooks").is_dir():
        for p in (PLUGIN / "hooks").rglob("*"):
            if p.is_file():
                out.append(p)
    out.extend(PLUGIN.rglob("*.sh"))
    if (PLUGIN / "commands").is_dir():
        out.extend((PLUGIN / "commands").rglob("*.md"))
    # The repo-root shell venues: tools/ci/*.sh (the landing lane's gate
    # declarations) and tools/*.sh (the lane runners that execute them).
    for parent in PLUGIN.parents:
        tools = parent / "tools"
        if (tools / "ci").is_dir() or (tools / "gatekeeper-land.sh").is_file():
            out.extend(sorted(tools.rglob("*.sh")))
            break
    seen, uniq = set(), []
    for f in out:
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            uniq.append(f)
    return uniq


#: One read per file for the whole run, instead of one per (program, file).
#:
#: WHY THIS IS A CORRECTNESS FIX AND NOT A TUNING. This auditor is the ONLY
#: instrument in the tree that scans all 1291 programs, and it re-read every
#: candidate file once per program: roughly 1291 x |files| opens. It does not
#: finish in ten minutes on this repo, which is why nothing ever wired it — a
#: check nobody can afford to run is a check nobody runs, and the tree's orphan
#: count went 163 -> 0 without it ever being consulted. Cached, the same
#: measurement takes seconds.
#:
#: The predicates below are BYTE-IDENTICAL to what they replaced; only the
#: source of `text` changed. A file that cannot be read still contributes
#: nothing, exactly as before.
_TEXT_CACHE: dict = {}

#: An identifier token. Every program stem is one (asserted in `audit`),
#: so "stem in tokens(text)" is exactly the `\\b<stem>\\b` match it replaced.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: The SAME line-anchored import shapes `_grep_python_import` matched,
#: captured once per file rather than re-matched once per program.
#: `glob("*_protocol_synth.py")` — a dispatcher that resolves modules by SHAPE.
#: Matching the pattern IS the wiring; the name appears nowhere.
_GLOB_DISPATCH_RE = re.compile(r"""glob\(\s*["']([^"'\n]*\*[^"'\n]*\.py)["']""")

_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([A-Za-z_][A-Za-z0-9_]*)\s+import\b"
    r"|import\s+([A-Za-z_][A-Za-z0-9_]*)\b)", re.MULTILINE)



def _text_of(f: Path) -> str:
    key = str(f)
    if key not in _TEXT_CACHE:
        try:
            _TEXT_CACHE[key] = f.read_text(errors="replace")
        except OSError:
            _TEXT_CACHE[key] = ""
    return _TEXT_CACHE[key]


def _grep_python_import(stem: str, files: Iterable[Path]) -> list[Path]:
    """Files that import `stem` (Python-style)."""
    pat = re.compile(
        rf"^\s*(?:from\s+{re.escape(stem)}\s+import\b|"
        rf"import\s+{re.escape(stem)}\b)",
        re.MULTILINE,
    )
    return [f for f in files if pat.search(_text_of(f))]


def _grep_word(stem: str, files: Iterable[Path]) -> list[Path]:
    """Whole-word match of stem (used for YAML/shell — covers
    `command: foo` and `tools/foo.py`)."""
    pat = re.compile(rf"\b{re.escape(stem)}\b")
    return [f for f in files if pat.search(_text_of(f))]


def audit() -> dict:
    programs = _list_programs()
    yaml_files = _yaml_files()
    shell_files = _shell_and_md_files()

    # ONE PASS OVER THE CORPUS, NOT ONE PER PROGRAM.
    #
    # `_python_files(p)` re-walked `PLUGIN.rglob("*.py")` inside the loop, once
    # per program, and `_grep_word` then ran a fresh regex over every one of
    # them: ~1291 directory walks and ~5 million regex searches. It does not
    # finish in ten minutes on this repo, and that is why nothing ever wired it
    # — a check nobody can afford to run is a check nobody runs, and the tree's
    # orphan count went 163 -> 0 without this instrument ever being consulted.
    #
    # THE PREDICATE IS UNCHANGED. `\b<stem>\b` over a text is exactly "stem is
    # one of the text's identifier tokens" when the stem is identifier-shaped,
    # and all 1291 are (asserted below, so a future non-identifier name breaks
    # the run rather than silently changing the ruler). Imports are collected
    # with the SAME line-anchored regex, applied once per file instead of once
    # per (file, program).
    for _p in programs:
        assert _IDENT_RE.fullmatch(_p.stem), (
            f"{_p.stem!r} is not identifier-shaped, so token membership is no "
            f"longer equivalent to the `\\b...\\b` match this replaced")

    all_py = _python_files(None)
    py_tokens = {f: set(_IDENT_RE.findall(_text_of(f))) for f in all_py}
    py_imports = {f: {n for m in _IMPORT_RE.findall(_text_of(f))
                     for n in m if n} for f in all_py}
    # THE FIFTH VENUE: A DISPATCHER THAT GLOBS.
    #
    # `phase1_doc_one_shot_runner.py:63803` walks
    # `sorted(_here.glob("*_protocol_synth.py"))` and runs every module it
    # finds. The module name is written NOWHERE — matching the glob IS the
    # wiring — so a name-based scan reports all 14 of them unreachable. They
    # are not. Before this venue existed the instrument printed
    # `[WARN] 14 POTENTIALLY_UNREACHABLE`, every one a false positive, and a
    # gate that always names fourteen innocents teaches its reader to discount
    # it. That is the state it shipped in, and the reason it was never wired.
    #
    # Derived from the SOURCE, never hard-coded: the globs are read out of the
    # corpus, so a new dispatcher is picked up and a retired one stops
    # counting. Only a dispatcher that is itself reachable may confer
    # reachability — otherwise a cluster of programs could bootstrap each
    # other. That check is applied after the first pass, below.
    glob_dispatch: dict = {}
    for f in all_py:
        for pat in _GLOB_DISPATCH_RE.findall(_text_of(f)):
            if pat.count("*") == 1 and len(pat) > 5:
                glob_dispatch.setdefault(pat, set()).add(f)

    yaml_tokens = {f: set(_IDENT_RE.findall(_text_of(f))) for f in yaml_files}
    shell_tokens = {f: set(_IDENT_RE.findall(_text_of(f))) for f in shell_files}

    rows: list[dict] = []
    for p in programs:
        stem = p.stem
        is_helper = _is_helper(stem)
        self_r = p.resolve()

        py_import_hits = [f for f in all_py
                          if f.resolve() != self_r and stem in py_imports[f]]
        # registry / dispatcher mention: any whole-word appearance in a
        # peer Python file. Catches `_STRUCTURAL_RTL_GATES = ("foo_check", ...)`
        # tuples and dynamic dispatch tables that don't `import foo_check`.
        py_word_hits = ([f for f in all_py
                         if f.resolve() != self_r and stem in py_tokens[f]]
                        if not is_helper else [])
        yaml_hits = ([f for f in yaml_files if stem in yaml_tokens[f]]
                     if not is_helper else [])
        shell_hits = ([f for f in shell_files if stem in shell_tokens[f]]
                      if not is_helper else [])

        # de-duplicate: word_hits is a superset of import_hits; subtract.
        py_word_only = [f for f in py_word_hits if f not in py_import_hits]
        total = (
            len(py_import_hits) + len(py_word_only)
            + len(yaml_hits) + len(shell_hits)
        )
        status = "REACHABLE" if total > 0 else "POTENTIALLY_UNREACHABLE"
        rows.append({
            "name": stem,
            "is_helper": is_helper,
            "status": status,
            "python_import_hits": [str(f.relative_to(ROOT)) for f in py_import_hits],
            "python_registry_hits": [str(f.relative_to(ROOT)) for f in py_word_only],
            "yaml_command_hits": [str(f.relative_to(ROOT)) for f in yaml_hits],
            "shell_or_md_hits": [str(f.relative_to(ROOT)) for f in shell_hits],
        })

    # A dispatcher confers reachability only when something reaches the
    # DISPATCHER. Checked here, against the rows just computed, so a cluster of
    # mutually-globbing modules cannot bootstrap itself into "wired".
    import fnmatch
    reached_names = {r["name"] for r in rows if r["status"] == "REACHABLE"}
    live_globs = {pat for pat, owners in glob_dispatch.items()
                  if any(o.stem in reached_names for o in owners)}
    for r in rows:
        if r["status"] != "POTENTIALLY_UNREACHABLE":
            continue
        hit = next((pat for pat in live_globs
                    if fnmatch.fnmatch(r["name"] + ".py", pat)), None)
        if hit:
            r["status"] = "REACHABLE"
            r["glob_dispatch_hits"] = sorted(
                str(o.relative_to(ROOT)) + f' glob("{hit}")'
                for o in glob_dispatch[hit] if o.stem in reached_names)

    # HOW STRONGLY IS IT REACHED? "Reachable" is one bit and it hides the
    # thing worth knowing.
    #
    # The campaign that took this tree's orphan count 163 -> 0 closed 34
    # programs onto flow clauses, and all 34 went in as
    # `advisory_program_exit_zero` — a clause `flow_compliance_check` RUNS and
    # then IGNORES ("RECORDS the verdict and NEVER fails the step", :7968).
    # Zero were blocking. Every one of those closures is real by the letter of
    # this audit, and the count moved without any step gaining the power to
    # refuse. An orphan closed onto a clause that cannot fail is a weaker
    # closure than the number suggests, and a one-bit verdict cannot say so.
    #
    # So the tier is REPORTED, never enforced: this program's exit code still
    # turns on reachability alone. Naming the tier is what lets a reader ask
    # "wired where?" without re-deriving it; deciding what each tier is worth
    # belongs to whoever reads the answer.
    blocking = _flow_blocking_stems()
    for r in rows:
        if r["status"] != "REACHABLE":
            r["tier"] = "unreached"
        elif r["name"] in blocking:
            r["tier"] = "blocking"          # a clause that can fail its step
        elif r["yaml_command_hits"] or r.get("glob_dispatch_hits"):
            r["tier"] = "advisory_or_dispatched"
        elif r["shell_or_md_hits"]:
            r["tier"] = "shell_or_doc"
        else:
            r["tier"] = "code_only"

    unreachable = [r for r in rows if r["status"] == "POTENTIALLY_UNREACHABLE"]
    tiers: dict = {}
    for r in rows:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    return {
        "programs_total": len(rows),
        "unreachable_count": len(unreachable),
        "unreachable": [r["name"] for r in unreachable],
        "tiers": tiers,
        "rows": rows,
    }


def _flow_blocking_stems() -> set:
    """Stems named by a flow clause that CAN fail its step.

    `program_exit_zero` fails the step on a non-zero exit.
    `optional_program_exit_zero` is blocking too — an unmet condition denies the
    step its PASS tier — but only when its condition can be met, which this
    program cannot know, so it is NOT counted here and lands in the advisory
    tier. That understates the blocking count rather than overstating it, which
    is the safe direction for a number a reader will use to judge a campaign.
    """
    out: set = set()
    for f in _yaml_files():
        try:
            import yaml  # noqa: PLC0415
            doc = yaml.safe_load(_text_of(f))
        except Exception:
            continue
        for step in (doc or {}).get("steps", []) or []:
            for clause in (step.get("gate", {}) or {}).get("all_of", []) or []:
                if not isinstance(clause, dict):
                    continue
                val = clause.get("program_exit_zero")
                if isinstance(val, dict):
                    val = val.get("command")
                if isinstance(val, str) and val.strip():
                    out.add(val.split()[0].removesuffix(".py"))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=None,
                   help=("audit this tree instead of the one this file lives "
                         "in — lets a gate run the RUNTIME's copy against the "
                         "SUBJECT's tree, which is what an A/B verification "
                         "needs and what `$ROOT` alone cannot express"))
    p.add_argument("--json", type=Path, default=None,
                   help="Write the full audit report as JSON.")
    p.add_argument("--strict", action="store_true",
                   help="Exit 1 if any POTENTIALLY_UNREACHABLE program found.")
    args = p.parse_args(argv)

    if args.root is not None:
        if not args.root.is_dir():
            print(f"ERROR: --root is not a directory: {args.root}",
                  file=sys.stderr)
            return 2
        _bind_root(args.root)

    report = audit()

    print(f"program_reachability_check: scanned {report['programs_total']} program(s)")
    # The tier line is the denominator this verdict is about. A PASS that does
    # not say WHERE its programs are reached cannot be told apart from a PASS
    # that counted everything as reached by a doc line.
    t = report.get("tiers") or {}
    print("  reached at: "
          + ", ".join(f"{k}={t[k]}" for k in sorted(t) if k != "unreached")
          + (f"  |  unreached={t['unreached']}" if t.get("unreached") else ""))
    if not report["unreachable"]:
        print("[PASS] every program is reachable from at least one Python "
              "import / YAML command / shell-or-md reference")
    else:
        print(f"[WARN] {report['unreachable_count']} POTENTIALLY_UNREACHABLE:")
        for name in report["unreachable"]:
            print(f"  - {name}")

    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")
        print(f"wrote {args.json}")

    if args.strict and report["unreachable"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
