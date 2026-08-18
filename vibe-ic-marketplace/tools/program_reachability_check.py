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

ROOT = Path(__file__).resolve().parents[2]  # AI_IC_design/
PLUGIN = ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
PROGRAMS = PLUGIN / "programs"


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


def _python_files(skip: Path) -> list[Path]:
    """All .py under the plugin tree except `skip` (the program being checked)."""
    out = []
    for p in PLUGIN.rglob("*.py"):
        # don't count a program's references to itself
        if p.resolve() == skip.resolve():
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
    out: list[Path] = []
    if (PLUGIN / "hooks").is_dir():
        for p in (PLUGIN / "hooks").rglob("*"):
            if p.is_file():
                out.append(p)
    out.extend(PLUGIN.rglob("*.sh"))
    if (PLUGIN / "commands").is_dir():
        out.extend((PLUGIN / "commands").rglob("*.md"))
    return out


def _grep_python_import(stem: str, files: Iterable[Path]) -> list[Path]:
    """Files that import `stem` (Python-style)."""
    pat = re.compile(
        rf"^\s*(?:from\s+{re.escape(stem)}\s+import\b|"
        rf"import\s+{re.escape(stem)}\b)",
        re.MULTILINE,
    )
    hits = []
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        if pat.search(text):
            hits.append(f)
    return hits


def _grep_word(stem: str, files: Iterable[Path]) -> list[Path]:
    """Whole-word match of stem (used for YAML/shell — covers
    `command: foo` and `tools/foo.py`)."""
    pat = re.compile(rf"\b{re.escape(stem)}\b")
    hits = []
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        if pat.search(text):
            hits.append(f)
    return hits


def audit() -> dict:
    programs = _list_programs()
    yaml_files = _yaml_files()
    shell_files = _shell_and_md_files()

    rows: list[dict] = []
    for p in programs:
        stem = p.stem
        is_helper = _is_helper(stem)
        py_files = _python_files(p)

        py_import_hits = _grep_python_import(stem, py_files)
        # registry / dispatcher mention: any whole-word appearance in a
        # peer Python file. Catches `_STRUCTURAL_RTL_GATES = ("foo_check", ...)`
        # tuples and dynamic dispatch tables that don't `import foo_check`.
        py_word_hits = (
            _grep_word(stem, py_files) if not is_helper else []
        )
        yaml_hits = _grep_word(stem, yaml_files) if not is_helper else []
        shell_hits = _grep_word(stem, shell_files) if not is_helper else []

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

    unreachable = [r for r in rows if r["status"] == "POTENTIALLY_UNREACHABLE"]
    return {
        "programs_total": len(rows),
        "unreachable_count": len(unreachable),
        "unreachable": [r["name"] for r in unreachable],
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", type=Path, default=None,
                   help="Write the full audit report as JSON.")
    p.add_argument("--strict", action="store_true",
                   help="Exit 1 if any POTENTIALLY_UNREACHABLE program found.")
    args = p.parse_args(argv)

    report = audit()

    print(f"program_reachability_check: scanned {report['programs_total']} program(s)")
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
