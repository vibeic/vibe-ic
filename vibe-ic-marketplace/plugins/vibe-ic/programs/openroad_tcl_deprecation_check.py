#!/usr/bin/env python3
"""
openroad_tcl_deprecation_check.py — Recursively scan a plugin tree for
OpenROAD TCL usages that have been removed or renamed in recent OpenROAD
releases, so a skill / program that still emits the old form fails its gate
instead of silently producing a broken flow.

Background (v0.69 Item 4): OpenROAD 2023+ removed ``write_gds`` (replaced by
the def2gds / KLayout merge flow), and 2024+ removed the legacy global-route
flags ``-bottom_routing_layer`` / ``-top_routing_layer`` (now expressed via
``set_routing_layers`` or ``global_route -congestion_iterations``). Any TCL
left over from a pre-2023 tutorial silently breaks on a fresh OpenROAD build.

This program is a static grep — it does not invoke OpenROAD. It walks
``--search-dir`` (default: the ``plugins/`` directory containing the
unified ``vibe-ic/`` plugin), inspects every
``*.tcl`` file AND every ``*.py`` / ``*.js`` / ``*.md`` / ``*.yaml`` / ``*.yml``
file (for embedded TCL snippets in heredocs, docstrings, or skill docs), and
flags occurrences of any deprecated token.

Usage::

    python3 openroad_tcl_deprecation_check.py
    python3 openroad_tcl_deprecation_check.py --search-dir plugins/
    python3 openroad_tcl_deprecation_check.py --json report.json

Exit codes::

    0 — no deprecated tokens found.
    1 — at least one hit; per-file per-line report on stdout + optional JSON.
    2 — argument or I/O error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# File extensions we descend into. *.tcl is the primary target; the others
# catch TCL fragments embedded in Python heredocs, JS template literals,
# markdown code fences, and YAML gate specs.
SCANNED_SUFFIXES = {".tcl", ".py", ".js", ".md", ".yaml", ".yml"}

# Directories we never enter.
SKIP_DIRS = {
    "__pycache__", ".git", "node_modules", ".mypy_cache", ".pytest_cache",
    "dist", "build",
}


@dataclass(frozen=True)
class Deprecation:
    """One deprecated-token rule."""
    token: str          # exact token the pattern looks for (for reporting)
    pattern: re.Pattern # compiled regex; must use a word boundary
    version: str        # OpenROAD version where the token was removed
    replacement: str    # human-readable replacement hint


# v0.69 Item 4 commission specified two mandatory entries and invited "up to
# 2 more if you see clear candidates". We add two well-sourced extras:
#   - `write_gds`   (removed from OpenROAD 2023+; canonical v0.69 replacement
#                    is the `def2gds` skill that merges DEF+cell GDS via
#                    KLayout).
#   - `set_global_routing_layer_adjustment` (OpenROAD renamed this to the
#     shorter `set_routing_layer_adjustment` around 2023; the long form emits
#     a deprecation warning but does not hard-error yet — belt-and-braces).
# Both are narrow, documentary-sourced, and avoid over-reach into DRC decks
# that are still valid for KLayout.
_DEPRECATIONS: Tuple[Deprecation, ...] = (
    Deprecation(
        token="-bottom_routing_layer",
        pattern=re.compile(r"(?<![\w\-])-bottom_routing_layer\b"),
        version="OpenROAD 2024+",
        replacement=(
            "use `set_routing_layers -signal <bottom>-<top>` OR "
            "`global_route -congestion_iterations` (flag removed)"
        ),
    ),
    Deprecation(
        token="-top_routing_layer",
        pattern=re.compile(r"(?<![\w\-])-top_routing_layer\b"),
        version="OpenROAD 2024+",
        replacement=(
            "use `set_routing_layers -signal <bottom>-<top>` OR "
            "`global_route -congestion_iterations` (flag removed)"
        ),
    ),
    Deprecation(
        token="write_gds",
        # `(?!\s*\()` — a TCL command is never invoked with parentheses, so a
        # `write_gds(` is Python function-DEF or CALL syntax (e.g. a test's own
        # raw-GDS-writer helper named write_gds), NOT the deprecated OpenROAD TCL
        # command. Real TCL emission (`write_gds $out`, an f-string
        # `write_gds {path}`) is still flagged — only Python paren-call/def is
        # excluded, so the gate keeps full power without the false positive.
        pattern=re.compile(r"(?<![\w\-])write_gds\b(?!\s*\()"),
        version="OpenROAD 2023+",
        replacement=(
            "OpenROAD no longer streams GDS; use the `def2gds` skill "
            "(plugins/vibe-ic/skills/def2gds) to merge routed.def + "
            "cell GDS via KLayout"
        ),
    ),
    Deprecation(
        token="set_global_routing_layer_adjustment",
        pattern=re.compile(r"(?<![\w\-])set_global_routing_layer_adjustment\b"),
        version="OpenROAD 2023+ (renamed)",
        replacement=(
            "rename to `set_routing_layer_adjustment` (the original long "
            "name still works but emits a deprecation warning that trips "
            "eda_log_check)"
        ),
    ),
)


# A single-line line-comment pattern per extension; when the match sits after
# a comment marker we suppress it (so this very file doesn't self-flag).
_COMMENT_PATTERNS = {
    ".tcl":  re.compile(r"^\s*#"),
    ".py":   re.compile(r"^\s*#"),
    ".yaml": re.compile(r"^\s*#"),
    ".yml":  re.compile(r"^\s*#"),
    ".js":   re.compile(r"^\s*//"),
    ".md":   None,  # markdown: flag everywhere except within explicit
                    # "do-not-scan" blocks (handled below)
}


@dataclass
class Finding:
    file: str          # relative path from search_dir
    line: int          # 1-based
    token: str
    version: str
    replacement: str
    excerpt: str       # the offending line, trimmed


def _iter_scan_files(root: Path):
    """Yield every file under ``root`` whose suffix is in SCANNED_SUFFIXES,
    skipping SKIP_DIRS and symlinks that would escape the tree."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Mutate in-place so os.walk prunes the skip set.
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in SCANNED_SUFFIXES:
                yield p


def _is_in_comment(line: str, suffix: str) -> bool:
    """Best-effort check: is the *entire* line a line-comment?

    We intentionally don't try to handle inline comments like
    ``some_cmd  # deprecated: write_gds``. A deprecated token inside such a
    comment is still a warning because someone might un-comment it later,
    and false-positives-on-comments are safer than false-negatives-on-code.
    """
    pat = _COMMENT_PATTERNS.get(suffix)
    if pat is None:
        return False
    return bool(pat.match(line))


# Phrases that, when present on the same line as a deprecated token, mark
# the occurrence as documentary (discussing the removal) rather than a live
# invocation. Covers both English prose and short code-comment fragments.
# Kept intentionally short & conservative — a line that *invokes* the
# deprecated command while also containing one of these phrases is rare.
_DOCUMENTARY_MARKERS = (
    "removed",
    "removal",
    "deprecat",    # deprecated / deprecation
    "no longer",
    "replaces",
    "replaced by",
    "replacement",
    "do not use",
    "don't use",
    "was removed",
    "removes ",
    "obsolete",
    "legacy",
)


def _is_documentary(line: str) -> bool:
    """True if the line appears to be discussing the deprecated token rather
    than using it. Case-insensitive substring match against a small fixed
    vocabulary. Used to suppress false positives in SKILL.md / module
    docstrings that cite the removed API by name."""
    low = line.lower()
    return any(m in low for m in _DOCUMENTARY_MARKERS)


def _self_exempt(path_str: str) -> bool:
    """This program's own source file + its test fixtures both necessarily
    mention the deprecated tokens. Exempt them so the plugin self-check
    passes."""
    basename = os.path.basename(path_str)
    return basename in (
        "openroad_tcl_deprecation_check.py",
        "test_openroad_tcl_deprecation_check.py",
    )


def scan(search_dir: Path) -> Tuple[List[Finding], int]:
    """Walk search_dir and collect every deprecation hit, WITH the file count.

    The count is returned, not derived by the caller, because a clean scan and
    a scan of nothing produced the same sentence and the same exit code:

        $ openroad_tcl_deprecation_check.py --search-dir <empty dir>
        ok: no OpenROAD TCL deprecations found.          rc=0

    identical to the answer over the whole plugin tree.  Nothing in the output
    let a reader tell "I looked and it is clean" from "I looked at nothing".

    Non-recoverable read errors on a single file are logged but do not abort
    the walk; a file that could not be read is NOT counted as examined."""
    findings: List[Finding] = []
    examined = 0
    search_dir_abs = search_dir.resolve()
    for fpath in _iter_scan_files(search_dir_abs):
        if _self_exempt(str(fpath)):
            continue
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError as exc:
            print(f"[openroad_tcl_deprecation_check] WARN: cannot read "
                  f"{fpath}: {exc}", file=sys.stderr)
            continue
        examined += 1
        suffix = fpath.suffix.lower()
        for idx, raw in enumerate(lines, start=1):
            line = raw.rstrip("\n")
            if _is_in_comment(line, suffix):
                continue
            if _is_documentary(line):
                # Line is discussing the removal (docstring, SKILL.md prose,
                # changelog entry) — not a live invocation. Skip.
                continue
            for dep in _DEPRECATIONS:
                if dep.pattern.search(line):
                    findings.append(Finding(
                        file=str(fpath.relative_to(search_dir_abs)),
                        line=idx,
                        token=dep.token,
                        version=dep.version,
                        replacement=dep.replacement,
                        excerpt=line.strip()[:200],
                    ))
    return findings, examined


def _format_report(findings: List[Finding], examined: int = -1) -> str:
    if not findings:
        if examined == 0:
            # Not "ok". Zero files examined means the search directory was
            # empty, filtered away by SCANNED_SUFFIXES/SKIP_DIRS, or wrong.
            return ("NOTHING EXAMINED: 0 files matched under the search "
                    "directory, so this is not a clean result")
        return (f"ok: no OpenROAD TCL deprecations found "
                f"(examined {examined} file(s))")
    out = [f"FAIL: {len(findings)} OpenROAD TCL deprecation hit(s):"]
    for f in findings:
        out.append(
            f"  {f.file}:{f.line}  {f.token}  "
            f"(removed in {f.version}) — {f.replacement}"
        )
        out.append(f"      > {f.excerpt}")
    return "\n".join(out)


def _default_search_dir() -> Path:
    """Default: the plugins/ directory that contains this program's tree
    (i.e. two levels up from programs/). This matches the commission:
    scan the unified plugin's skills + programs in one shot."""
    here = Path(__file__).resolve()
    # here = .../plugins/vibe-ic/programs/openroad_tcl_deprecation_check.py
    #        parents[0]=programs parents[1]=<plugin> parents[2]=plugins
    return here.parents[2]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Recursively grep for deprecated OpenROAD TCL tokens. Default "
            "--search-dir is the plugin tree that contains this program, "
            "so running it with no args performs the v0.70 plugin "
            "self-check."
        )
    )
    ap.add_argument("--search-dir", default=None,
                    help="Root directory to scan (recursively). Default: "
                         "this plugin's plugins/ directory.")
    ap.add_argument("--json", default=None,
                    help="Optional path to write a JSON report.")
    args = ap.parse_args(argv)

    if args.search_dir is None:
        search_dir = _default_search_dir()
    else:
        search_dir = Path(args.search_dir)
    if not search_dir.is_dir():
        print(f"error: --search-dir is not a directory: {search_dir}",
              file=sys.stderr)
        return 2

    try:
        findings, examined = scan(search_dir)
    except OSError as exc:
        print(f"error: scan failed: {exc}", file=sys.stderr)
        return 2

    report = _format_report(findings, examined)
    if findings or examined == 0:
        print(report, file=sys.stderr)
    else:
        print(report)

    if args.json:
        try:
            Path(args.json).write_text(json.dumps({
                "search_dir": str(search_dir),
                "deprecations_scanned": [d.token for d in _DEPRECATIONS],
                "findings": [asdict(f) for f in findings],
                "total": len(findings),
                # A consumer reading `total: 0` has no way to tell a clean
                # scan from a scan of nothing without this.
                "files_examined": examined,
            }, indent=2))
        except OSError as exc:
            print(f"error: cannot write JSON report: {exc}", file=sys.stderr)
            return 2

    # `examined == 0` is not clean. The message already says so; leaving rc=0
    # would let every caller that reads the exit code — which is most of
    # them — record a scan of nothing as a pass, which is the whole defect
    # this disclosure was added for, surviving one layer down.
    return 1 if (findings or examined == 0) else 0


if __name__ == "__main__":
    sys.exit(main())
