#!/usr/bin/env python3
"""source_chip_agnostic_check.py — chip-AGNOSTIC source guard.

Scans every tracked source file under programs/, skills/, agents/, flow/,
tools/, .claude-plugin/, and docs/ for tokens listed in
tests/chip_deny_list.txt (word-bounded, case-insensitive).

A non-empty match list is a hard failure: a public-facing source file
must never contain a private IC / vendor / protocol name.

Exit codes:
  0 — clean
  1 — at least one violation
  2 — chip_deny_list.txt missing or empty

Usage:
  python3 programs/source_chip_agnostic_check.py [--root <repo-root>]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


_DEFAULT_ROOT = Path(__file__).resolve().parents[1]
_DENY_LIST_REL = "tests/chip_deny_list.txt"

# Directories scanned. Tests under tests/ are excluded because the deny-list
# file itself contains the tokens; the guard tests load it deliberately.
_SCAN_DIRS = (
    "programs",
    "skills",
    "agents",
    "flow",
    "tools",
    ".claude-plugin",
    "docs",
    "hooks",
    "commands",
)

# Files explicitly excluded (the deny-list itself, the guard test).
_EXCLUDE = {
    "tests/chip_deny_list.txt",
    "tests/test_chip_agnostic_guard.py",
    "programs/source_chip_agnostic_check.py",
}

_TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".yaml", ".yml", ".txt",
    ".sh", ".js", ".ts", ".v", ".sv", ".tcl", ".cfg",
}


def _load_deny_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    tokens: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            tokens.append(line.lower())
    return tokens


def _build_regex(tokens: list[str]) -> re.Pattern[str]:
    alternation = "|".join(re.escape(t) for t in tokens)
    return re.compile(rf"\b({alternation})\b", re.IGNORECASE)


def _iter_files(root: Path):
    for sub in _SCAN_DIRS:
        d = root / sub
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix not in _TEXT_SUFFIXES:
                continue
            rel = f.relative_to(root).as_posix()
            if rel in _EXCLUDE:
                continue
            yield f, rel


def scan(root: Path) -> list[tuple[str, int, str]]:
    deny_path = root / _DENY_LIST_REL
    tokens = _load_deny_list(deny_path)
    if not tokens:
        print(f"ERROR: deny-list missing or empty: {deny_path}", file=sys.stderr)
        sys.exit(2)
    rx = _build_regex(tokens)
    violations: list[tuple[str, int, str]] = []
    for f, rel in _iter_files(root):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = rx.search(line)
            if m:
                violations.append((rel, i, m.group(0)))
    return violations


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(_DEFAULT_ROOT), type=Path)
    args = ap.parse_args()
    root = args.root.resolve()
    violations = scan(root)
    if not violations:
        print("source_chip_agnostic_check: PASS (no violations)")
        return 0
    print(f"source_chip_agnostic_check: FAIL ({len(violations)} violations)")
    for rel, line, tok in violations[:50]:
        print(f"  {rel}:{line}  →  {tok!r}")
    if len(violations) > 50:
        print(f"  ... and {len(violations) - 50} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
