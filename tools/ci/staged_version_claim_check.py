#!/usr/bin/env python3
"""
staged_version_claim_check.py — catch "version claim ahead of bump" in
newly staged additions.

Companion to Wave 93's commit-msg `check_version_sync_with_commit.sh`,
which only validates a vX.Y.Z mentioned in the commit SUBJECT line.
That guard misses the mirror-leak pattern observed in commit 9d4e984a:

    Code comments add `v1.6.19` markers in 5 places, but neither
    plugin.json nor marketplace.json nor the commit subject mention
    a version. Both existing hooks remain silent — the pre-commit
    `marketplace_version_sync_check` only verifies plugin.json ↔
    marketplace.json drift (both still 1.6.18, so they're "in sync"),
    and the commit-msg hook skips because the subject has no version.
    Net effect: 1632 lines of feature code lands as "1.6.18" while
    its own comments call it "1.6.19".

This check fires at pre-commit. It walks the STAGED diff (`git diff
--cached --unified=0`), pulls every NEWLY ADDED line that mentions
`vX.Y.Z` (or bare `X.Y.Z` adjacent to "version"/"plugin"/"marketplace"
context), filters historical references (supersedes / was / fixes /
from / since / pre- / prior to / before), and FAILs if any remaining
candidate is strictly greater than the version declared in
`vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json`.

Design notes
------------
* Scans STAGED additions only — does NOT enforce repo-wide consistency.
  This means historical comments left over in HEAD never re-trigger;
  the guard only blocks NEW commits that introduce a forward-looking
  version claim without bumping plugin.json + marketplace.json.
* Equal versions PASS. We're catching "ahead", not "stale".
* Glob-skips a small allow-list (CHANGELOG, RELEASE_NOTES — these
  legitimately list future versions during release planning).

Usage:
    python3 tools/ci/staged_version_claim_check.py
    python3 tools/ci/staged_version_claim_check.py --plugin-json <path>
    python3 tools/ci/staged_version_claim_check.py --diff-from-stdin
        (read unified=0 diff text from stdin instead of `git diff
        --cached`; used by the pytest harness)

Exit codes:
    0 — no violation (or no version claims at all)
    1 — at least one newly added line claims a version > plugin.json.version
    2 — usage / IO error
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple


# Match a semver-ish triple, with optional `v` prefix. We constrain to
# 1-3 digit components so noise like an IPv4 address (`<lan-ip>`)
# or a date (`2026.05.08`) does not parse as a version.
# Negative-lookahead guards: not preceded by `.<digit>` (catches the
# trailing 3 octets of an IPv4 like <lan-ip>) and not followed by
# `.<digit>` (catches the first 3 octets). Both ends pinned so a real
# semver `1.6.18` matches but `<lan-ip>` and `2026.05.08.x` do not.
_VER_RE = re.compile(
    r"(?<![\d.])v?(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?!\.?\d)"
)

# Substrings (case-insensitive) that mark the version mention as a
# HISTORICAL reference rather than a forward claim. If any of these
# appears within ~30 chars BEFORE the version mention, we skip it.
_HISTORICAL_PREFIXES = (
    "supersedes", "was ", "(was", "fixes ", "from ", "from-", "since ",
    "pre-", "pre v", "prior to ", "before ", "earlier ", "old ", "old-",
    "previous ", "previously", "introduced in ", "added in ", "added v",
    "see ", "ref ", "ref:", "regression ",
    # `git log` / commit hash refs
    "commit ", "sha ", "rev ",
)

# Path globs we never gate. CHANGELOG / RELEASE_NOTES intentionally list
# the version they ANNOUNCE (which by definition is the about-to-bump
# value). Without this skip the hook would block release-prep commits.
# `test_staged_version_claim_check` skip: this hook's own pytest harness
# deliberately injects fake-future versions (vX.Y.Z fixtures, far above
# the current release) to verify the FAIL path; without the skip the
# hook would block its own test file every time the harness is touched.
_SKIP_PATH_PATTERNS = (
    "CHANGELOG",
    "RELEASE_NOTES",
    "RELEASE-NOTES",
    "release_notes",
    "test_staged_version_claim_check",
    # Tool-output artefacts — these embed third-party tool versions
    # (Yosys, Quartus, gcc, OpenSTA, ...) which are NOT plugin version
    # claims. Skip the entire tool-output families so they don't trip
    # the gate during recovery / large benchmark-snapshot commits.
    ".flow.rpt",
    ".map.rpt",
    ".fit.rpt",
    ".sta.rpt",
    ".asm.rpt",
    ".tcl.log",
    "/synth/",
    "/pnr/",
    "/sta/",
    "/sim/",
    "/input_doc/",
    "/output_files/",
    "/incremental_db/",
    "phase2/stage1/sim/",
    "phase2/stage2/synth/",
    "phase3/stage3/",
    "phase3/stage4/",
    "/training_runs/",
    "/multi_ic_validation_",
    "/benchmark/", "benchmark/phase",
    # Top-level benchmark snapshot dirs (Nth_benchmark*/ at repo root)
    # carry verbatim vendor documentation that legitimately contains
    # NIST/IEEE section numbers (e.g. pre-existing standards anchors)
    # and chapter version markers which are not plugin claims. Without
    # this skip the
    # gate blocks every benchmark-snapshot commit.
    "1st_benchmark", "2nd_banchmark", "3rd_benchmark", "4th_benchmark",
    ".qsf",
    ".qpf",
    ".sdc",
    "/formal/",
    "/fpga/",
    "/debug/",
    "/drc_lvs/",
    "/synth_m18/",
    "/gl_sim/",
    "design.log",
    "yosys_stat.txt",
    "/extracted/",
    "/eda_logs/",
    "/scratch_sim_gate_level/",
    "/cov_work/",
    "/sim_unit/",
    "/generated_docs/",
    "/human_docs/",
    "/phase1/",
    "/extracted_text/",
    "/work/",
    "/reports/",
    # RFC / planning docs legitimately discuss target / proposed
    # versions before plugin.json bumps (same exemption rationale
    # as CHANGELOG / RELEASE_NOTES).
    "docs/architecture/RFC_",
    "docs/architecture/RENAME_MAPPING_",
    "docs/architecture/CANONICAL_FLOW_",
    "docs/architecture/v2_validation/",
    "_PROPOSED.md",
)


def _parse_version(ver: str) -> Tuple[int, int, int]:
    m = _VER_RE.search(ver)
    if not m:
        raise ValueError(f"not a version: {ver}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _read_plugin_version(plugin_json_path: Path) -> Tuple[int, int, int]:
    if not plugin_json_path.is_file():
        raise FileNotFoundError(plugin_json_path)
    data = json.loads(plugin_json_path.read_text(encoding="utf-8"))
    return _parse_version(data["version"])


def _looks_historical(line: str, match_start: int) -> bool:
    """Check if the version mention is preceded by a historical-reference
    keyword within a short look-back window. Cheap heuristic; accepts
    some false-positives in comment prose to avoid false-negatives in
    real version claims."""
    look_back = line[max(0, match_start - 40): match_start].lower()
    for pfx in _HISTORICAL_PREFIXES:
        if pfx in look_back:
            return True
    return False


def _diff_unified_zero(repo_root: Path) -> str:
    """Capture `git diff --cached --unified=0 -- .` from the repo root.
    Decodes with errors='replace' so a single binary blob in the diff
    (e.g. a .sof / .gds / .vvp file) doesn't crash the whole gate."""
    cp = subprocess.run(
        ["git", "diff", "--cached", "--unified=0", "--no-color"],
        cwd=str(repo_root),
        capture_output=True, timeout=60,
    )
    if cp.returncode != 0:
        stderr_txt = cp.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"git diff --cached failed (rc={cp.returncode}): {stderr_txt}"
        )
    return cp.stdout.decode("utf-8", errors="replace")


def _walk_added_lines(diff_text: str):
    """Yield (path, lineno, line_body) for every `+ ...` addition.

    Tracks `+++ b/<path>` headers and `@@ -... +start,N @@` hunks so we
    can attribute each `+` line to a real file path + line number."""
    cur_path: Optional[str] = None
    cur_lineno = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            cur_path = raw[len("+++ b/"):]
            cur_lineno = 0
            continue
        if raw.startswith("+++ ") or raw.startswith("--- "):
            # File header (we only care about `+++ b/`).
            continue
        if raw.startswith("@@"):
            # Hunk header: @@ -a,b +c,d @@ ...
            m = re.match(r"@@\s+-\S+\s+\+(\d+)(?:,\d+)?\s+@@", raw)
            cur_lineno = int(m.group(1)) if m else 0
            continue
        if cur_path is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            yield cur_path, cur_lineno, raw[1:]
            cur_lineno += 1
            continue
        if raw.startswith("-") or raw.startswith("---"):
            # deletion — does not advance the +side line number
            continue
        # context line (with --unified=0 these only appear inside binary
        # diff hunks; harmless): advance + side too
        cur_lineno += 1


def _path_skipped(path: str) -> bool:
    return any(pat in path for pat in _SKIP_PATH_PATTERNS)


# Content-based skip: lines containing these tokens are clearly tool
# banners or build-environment strings, not plugin version claims.
_TOOL_BANNER_TOKENS = (
    "Yosys", "Quartus", "OpenSTA", "OpenROAD", "KLayout", "Magic",
    "Verilator", "iverilog", "ngspice", "xschem", "Calibre",
    "Synopsys", "Cadence", "Mentor", "Altera", "Intel(R)",
    "ubuntu", "Ubuntu", "Linux", "Darwin", "Windows",
    "gcc", "g++", "clang", "rustc", "node", "python3",
    "Generated by", "Compiler version", "Build version",
    "git sha1", "Tool flow", "vivado", "altera",
    "ORIGINAL_QUARTUS_VERSION", "QUARTUS_VERSION",
    "Analyzing design", "Executing", "pre-parsed AST",
    "decision trees", "async resets", "register",
)


# Section-number pattern: a line starting with `<digit>.<digit>.<digit>.`
# (note the trailing dot) is a section number in tool logs, not a
# semver. Pre-screen before running _VER_RE on the line body.
_SECTION_NUMBER_RE = re.compile(r"^\s*\d+\.\d+\.\d+\.")


def _content_skipped(line: str) -> bool:
    if any(tok in line for tok in _TOOL_BANNER_TOKENS):
        return True
    if _SECTION_NUMBER_RE.match(line):
        return True
    return False


def check(diff_text: str,
          plugin_version: Tuple[int, int, int]
          ) -> List[Tuple[str, int, str, Tuple[int, int, int]]]:
    """Return a list of `(path, lineno, line, claimed_version)` violations
    where `claimed_version > plugin_version`. Empty list = no violation."""
    violations = []
    for path, lineno, body in _walk_added_lines(diff_text):
        if _path_skipped(path):
            continue
        if _content_skipped(body):
            continue
        for m in _VER_RE.finditer(body):
            if _looks_historical(body, m.start()):
                continue
            try:
                claimed = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except (TypeError, ValueError):
                continue
            if claimed > plugin_version:
                violations.append((path, lineno, body.rstrip("\n"), claimed))
    return violations


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument(
        "--plugin-json", type=Path,
        default=None,
        help="Path to plugin.json (default: vibe-ic-marketplace/plugins/"
             "vibe-ic/.claude-plugin/plugin.json relative to repo root)",
    )
    p.add_argument(
        "--repo-root", type=Path, default=None,
        help="Repo root for `git diff --cached`. Default: current dir.",
    )
    p.add_argument(
        "--diff-from-stdin", action="store_true",
        help="Read the unified-0 diff from stdin (test harness use).",
    )
    args = p.parse_args(argv)

    repo_root = (args.repo_root or Path.cwd()).resolve()
    plugin_json = args.plugin_json or (
        repo_root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
        / ".claude-plugin" / "plugin.json"
    )

    try:
        plugin_ver = _read_plugin_version(plugin_json)
    except FileNotFoundError:
        print(f"  SKIP: plugin.json not at {plugin_json}", file=sys.stderr)
        return 0
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"  ERROR: cannot parse plugin.json: {exc}", file=sys.stderr)
        return 2

    if args.diff_from_stdin:
        diff_text = sys.stdin.read()
    else:
        try:
            diff_text = _diff_unified_zero(repo_root)
        except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
            print(f"  ERROR: git diff failed: {exc}", file=sys.stderr)
            return 2

    violations = check(diff_text, plugin_ver)

    plugin_ver_str = ".".join(str(x) for x in plugin_ver)
    if not violations:
        print(f"  PASS: no staged addition claims a version > plugin.json "
              f"({plugin_ver_str})")
        return 0

    print(f"  FAIL: {len(violations)} staged addition(s) claim a version "
          f"AHEAD of plugin.json ({plugin_ver_str}):")
    for path, lineno, line, claimed in violations[:10]:
        cv = ".".join(str(x) for x in claimed)
        print(f"    {path}:{lineno}: claimed v{cv} > plugin {plugin_ver_str}")
        print(f"      {line.strip()[:120]}")
    if len(violations) > 10:
        print(f"    … and {len(violations) - 10} more.")
    print()
    print("  → Either bump plugin.json + marketplace.json BEFORE this commit "
          "lands, or rephrase the comment to be a historical reference "
          "(prefix with `was`, `supersedes`, `since`, `pre-`, `from`, …).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
