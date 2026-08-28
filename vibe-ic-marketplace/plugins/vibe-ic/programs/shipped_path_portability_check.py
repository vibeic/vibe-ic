#!/usr/bin/env python3
"""
shipped_path_portability_check.py — shipped-source path-portability guard.

Doctrine: **a shipped default must never be a personal absolute path.**

This is the regression guard for a user-facing defect in which the plugin
carried one developer's home directory baked into runtime code:

  * a benchmark scorer defaulted its host designs root to that home directory
    and then `mkdir(parents=True)`-ed it into existence — so a CLEAN install
    materialised a workspace directory the user never asked for;
  * the MCP server's last-resort programs dir pointed at that same tree (and at
    a plugin name that no longer exists), so on any other machine it silently
    resolved to nothing;
  * a runner's search list "probed" absolute paths that exist on exactly one
    machine on earth.

A wrong path that silently "works" is how this stayed hidden, so the rule is
resolve-or-FAIL: a runtime path must come from an env var, from a path derived
from the plugin's own location, or from the caller's project argument — never
from an invented constant.

Two rules, applied to shipped plugin source:

  R1 — PERSONAL USERNAME (every file type).
       `/home/<name>/`, `/Users/<name>/` or `C:\\Users\\<name>\\` FAILs unless
       <name> is a recognised PLACEHOLDER (angle-bracketed like `<your-user>`,
       a shell expansion like `$USER`, or an ellipsis) or is on the short,
       explicit synthetic-name allow-list below. A real person's username is on
       neither list, so it FAILs.

  R2 — ABSOLUTE HOME PATH AS A VALUE (executable source only, excluding tests).
       In .py/.js/.sh sources outside test trees, an absolute home path may not
       appear in a *string literal* at all — not even `/home/user/...`. Whose
       home directory it is does not matter: it cannot be a correct shipped
       value on someone else's machine. Comments and docstrings are stripped
       before this rule runs (they are cosmetic, and R1 still covers them).

Allow-list rationale (deliberately narrow — every entry is justified):
  * placeholder forms  — genuine documentation examples the reader must
    substitute (`/home/<your-user>/...`); they cannot be mistaken for a value.
  * synthetic names    — short non-name tokens used as FIXTURE DATA by the
    path-detector tests and by detector docstrings that must *show* the bad
    shape in order to describe it.
  * `runner`           — the GitHub Actions CI home; referenced when explaining
    why a test skips on CI.
Nothing here whitelists a directory, a file, or a real account name.

Usage:
    python3 shipped_path_portability_check.py <plugin_root> [--json <out>]
                                              [--allow-user NAME]...

Exit codes:
    0  PASS
    1  FAIL — at least one non-portable path in shipped source
    2  argument or I/O error

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import _published_tree as _pt


# --------------------------------------------------------------------------
# What counts as a home path
# --------------------------------------------------------------------------
# The username charclass deliberately excludes backslash and regex metachars so
# that a DETECTOR PATTERN (e.g. a source line containing the literal regex
# "/home/" followed by a backslash-w) is not itself flagged as a path.
_USER_CHARS = r"[A-Za-z0-9._-]+"

_HOME_PAT = re.compile(
    r"(?:/home/(?P<u1>" + _USER_CHARS + r")/"
    r"|/Users/(?P<u2>" + _USER_CHARS + r")/"
    r"|[Cc]:\\+Users\\+(?P<u3>" + _USER_CHARS + r")\\+)"
)

# Placeholder usernames: structurally impossible to mistake for a real value.
_PLACEHOLDER_PAT = re.compile(
    r"^(?:<.*>|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|%[A-Za-z_]+%|\.\.\.|~)$"
)

# Synthetic fixture / example names. See "Allow-list rationale" above.
_SYNTHETIC_USERS = frozenset({
    "user",       # generic doc placeholder; R2 still bans it as a VALUE
    "youruser", "your-user", "username", "someuser", "testuser",
    "me", "x", "u", "foo", "bar",
    "runa", "run-7",  # netlist src-coord canonicalisation fixtures
    "runner",         # GitHub Actions CI home
})

_SCAN_EXTS = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash",
    ".json", ".yaml", ".yml", ".md", ".txt", ".tcl", ".ys", ".example",
    ".template",
})

# R2 applies to executable source only.
_CODE_EXTS = frozenset({".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash"})

_SKIP_DIR_NAMES = frozenset({
    ".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".ruff_cache",
})


def _is_test_path(rel: Path) -> bool:
    """Test trees carry deliberate fixture paths; R2 does not apply to them."""
    parts = {p.lower() for p in rel.parts}
    if parts & {"tests", "test", "testdata", "fixtures"}:
        return True
    return rel.name.startswith("test_") or rel.name.endswith("_test.py")


def _user_allowed(name: str, extra_allowed: Iterable[str] = ()) -> bool:
    if _PLACEHOLDER_PAT.match(name):
        return True
    low = name.lower()
    return low in _SYNTHETIC_USERS or low in {e.lower() for e in extra_allowed}


# --------------------------------------------------------------------------
# Comment / docstring stripping (for R2)
# --------------------------------------------------------------------------
def _py_code_strings(text: str) -> List[str]:
    """Return every Python string-literal VALUE that is not a docstring.

    Uses the AST so that a `#` inside a string, or a `/home/...` inside a
    module/class/function docstring, is classified correctly rather than by a
    brittle line regex.
    """
    try:
        # Some scanned sources contain regex/format literals that make the
        # compiler emit SyntaxWarning ("invalid escape sequence"). That is the
        # scanned file's business, not this guard's — keep our output clean.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            out.append(node.value)
    return out


_JS_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_SH_COMMENT_RE = re.compile(r"(?m)(?<!\$)#[^\n]*")


def _strip_comments(text: str, ext: str) -> str:
    if ext in {".js", ".mjs", ".cjs", ".ts"}:
        return _JS_COMMENT_RE.sub(" ", text)
    if ext in {".sh", ".bash"}:
        return _SH_COMMENT_RE.sub(" ", text)
    return text


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------
@dataclass
class Finding:
    file: str
    line: int
    rule: str
    path: str
    reason: str


def _line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def scan_file(path: Path, rel: Path,
              extra_allowed: Sequence[str] = ()) -> List[Finding]:
    ext = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    findings: List[Finding] = []

    # ---- R1: personal username, anywhere in the file -----------------------
    for m in _HOME_PAT.finditer(text):
        name = m.group("u1") or m.group("u2") or m.group("u3")
        if _user_allowed(name, extra_allowed):
            continue
        findings.append(Finding(
            file=str(rel), line=_line_of(text, m.start()), rule="R1",
            path=m.group(0),
            reason=(f"personal home path (user {name!r}) in shipped source. "
                    f"Resolve from an env var, from a path derived from the "
                    f"plugin's own location, or from the caller's project "
                    f"argument — and FAIL with a named env var if none "
                    f"resolves. If this is a documentation example, write the "
                    f"user as a placeholder such as <your-user>."),
        ))

    # ---- R2: absolute home path as a VALUE in executable source ------------
    if ext in _CODE_EXTS and not _is_test_path(rel):
        if ext == ".py":
            haystacks = _py_code_strings(text)
        else:
            haystacks = [_strip_comments(text, ext)]
        seen = set()
        for hay in haystacks:
            for m in _HOME_PAT.finditer(hay):
                frag = m.group(0)
                if frag in seen:
                    continue
                seen.add(frag)
                # locate it in the original text for a useful line number
                at = text.find(frag)
                findings.append(Finding(
                    file=str(rel),
                    line=_line_of(text, at) if at >= 0 else 0,
                    rule="R2", path=frag,
                    reason=("absolute home path used as a VALUE in executable "
                            "source. No home directory is a correct shipped "
                            "default on someone else's machine — resolve from "
                            "$ENV, from the plugin's own location, or from the "
                            "caller's argument, and FAIL loudly naming the env "
                            "var when nothing resolves."),
                ))
    return findings


def iter_source_files(root: Path) -> Iterable[Path]:
    """The population is what the COMMIT carries, not what this disk holds.

    SHIPPED means committed. A walk answers "what is on this machine", and the
    two diverge the moment anyone runs the suite: generated fixtures under
    `programs/tests/fixtures/` are ignored by `.gitignore`, so `git status
    --untracked-files=all` does not show them, and they entered this scan
    silently. Measured at the commit that landed this, same commit both sides:

        working checkout    3654 file(s) scanned
        fresh worktree      3595

    59 files, all of them generated, none of them shipped. The verdict happened
    to agree — but a fixture written with an absolute path would have made this
    gate FAIL on its author's machine and PASS in CI, for a file that is in
    neither commit. `_published_tree` was built for exactly this class and
    already records three earlier instances; this is the fourth.

    `_SKIP_DIR_NAMES` stays as the fallback's filter, and is no longer the only
    thing standing between the scan and `__pycache__`: it was a hand-maintained
    approximation of `.gitignore`, which is a second copy of a value it cannot
    see. Asking git makes it redundant rather than adding a mechanism beside it.
    """
    walked = [p for p in sorted(root.rglob("*"))
              if p.is_file()
              and not any(part in _SKIP_DIR_NAMES for part in p.parts)
              and p.suffix.lower() in _SCAN_EXTS]
    # `None` is "not a published tree", NEVER "published and empty" — a user's
    # own project directory publishes nothing, and there presence on disk is
    # the honest answer. Collapsing the two would turn "I could not look" into
    # "I looked and there is nothing".
    if _pt.published_paths(root) is None:
        SCAN_CENSUS["enumeration"] = "filesystem-walk"
        return walked
    SCAN_CENSUS["enumeration"] = "git-tracked"
    return _pt.filter_to_published(root, walked)


# Filled by `scan_tree` on every call: how many files this guard actually read.
# A PASS with no denominator cannot be told apart from a PASS that scanned
# NOTHING (vibe-ic#447), and the repo's own empty-tree probe refuses to let a
# gate be wired into CI without one — it caught this program when it was
# wired, which is the probe working.
SCAN_CENSUS: dict = {}


def scan_tree(root: Path, extra_allowed: Sequence[str] = ()) -> List[Finding]:
    findings: List[Finding] = []
    SCAN_CENSUS.clear()
    SCAN_CENSUS["files_read"] = 0
    for p in iter_source_files(root):
        SCAN_CENSUS["files_read"] += 1
        findings.extend(scan_file(p, p.relative_to(root), extra_allowed))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fail if shipped plugin source carries a personal absolute "
                    "home path where it could be used as a value.")
    ap.add_argument("plugin_root")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--allow-user", action="append", default=[],
                    help="additional synthetic username to allow (narrow use)")
    args = ap.parse_args(argv)

    root = Path(args.plugin_root).expanduser()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 2

    findings = scan_tree(root, args.allow_user)

    if args.json:
        try:
            Path(args.json).write_text(
                json.dumps({"plugin_root": str(root),
                            "verdict": "FAIL" if findings else "PASS",
                            "count": len(findings),
                            "findings": [asdict(f) for f in findings]},
                           indent=2) + "\n", encoding="utf-8")
        except OSError as e:
            print(f"ERROR: cannot write --json: {e}", file=sys.stderr)
            return 2

    _read = SCAN_CENSUS.get("files_read", 0)
    # NAMED IN THE VERDICT, not merely recorded. A fallback nobody can see is
    # how the defect this fixes stayed invisible: the walk and the tracked set
    # give the same sentence, so the only way to tell which one answered is for
    # the sentence to say. `filesystem-walk` is legitimate — it is what a user's
    # own project gets — but it must never be indistinguishable from the other.
    _how = SCAN_CENSUS.get("enumeration", "unknown")
    if not findings and _read == 0:
        # Scanning nothing and finding nothing is what a WRONG ROOT looks like.
        print(f"shipped_path_portability_check: NOTHING_SCANNED — read 0 "
              f"scannable file(s) under {root}. A clean result over an empty "
              f"scan is not a clean result; check the plugin_root argument.",
              file=sys.stderr)
        return 2
    if not findings:
        print(f"shipped_path_portability_check: PASS ({_read} file(s) scanned, "
              f"{_how}) — no personal absolute paths in shipped source")
        return 0

    print(f"shipped_path_portability_check: FAIL — {len(findings)} "
          f"non-portable path(s) in {_read} file(s) scanned ({_how})")
    for f in findings:
        print(f"  {f.file}:{f.line} [{f.rule}] {f.path}\n      {f.reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
