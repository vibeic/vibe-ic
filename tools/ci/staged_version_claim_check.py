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
# `staged_version_claim_check` skip (both this source file AND its pytest
# harness, since the substring matches both paths): this guard's own source
# DOCUMENTS the version-shapes it gates — its docstrings/comments carry
# illustrative "bad shapes" (a bare `vX.Y.Z`, a `vibe-ic X.Y.Z` self-claim
# example) and its test harness deliberately injects fake-future versions to
# exercise the FAIL path. Both are descriptions OF the gate, never a real
# plugin-version claim, so the guard must not gate its own implementation +
# test (symmetric with how every linter exempts its own rule fixtures).
_SKIP_PATH_PATTERNS = (
    "CHANGELOG",
    "RELEASE_NOTES",
    "RELEASE-NOTES",
    "release_notes",
    "staged_version_claim_check",
    # The commit-msg version-sync hook + its pytest harness are the SAME
    # self-exemption case as this guard's own source above: their comments
    # and fixtures carry illustrative version shapes ("from v1.2.3",
    # "feat(v1.2.3)") that DESCRIBE what the hook gates, never a real
    # plugin-version claim (ORGANIC-20260606 #422).
    "check_version_sync_with_commit",
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
    # Community backlog filings are field-agent PROSE describing IC-design
    # problems — they quote external spec section numbers (e.g. "Verilog 1995
    # §3.7.5"), external-doc/tool versions ("Debug Module 0.13.2"), and section
    # headers ("1.2.3 Title"). None of these are plugin self-claims; the whole
    # tree is exempt for the same reason as the benchmark-snapshot dirs and
    # CHANGELOG/RFC docs below.
    "community/backlogs/", "community/backlogs",
    # ORGANIC #537 — benchmark RESULT reports (§6 of the methodology REQUIRES
    # a Reproduce section = real curl/docker commands embedding EXTERNAL
    # dataset/tool/image versions: upstream release tags, sim-tool versions,
    # cocotb pins). These are external-product versions, never plugin
    # self-claims — same rationale as community/backlogs above. Scoped to
    # the RESULT-report naming convention so plugin docs stay gated.
    "/RESULT_", "RESULT_v", "/RESULT.md",
    # ORGANIC #537 (same disease, second site, caught by the AID mirror's
    # own pre-commit): BENCHMARK_REGISTRY.json is the registry of EXTERNAL
    # benchmarks — upstream dataset release tags (e.g. an HF dataset
    # "v1.1.0") are inherent registry content, never plugin self-claims.
    "BENCHMARK_REGISTRY.json",
    # …and the CVDP env-preflight program + its test: their PURPOSE is the
    # official external tool-version spec table (iverilog/yosys/cocotb/
    # verilator pins from the upstream Dockerfile.sim) — external versions
    # by design, same rationale as the tool-output artefact family.
    "cvdp_env_preflight",
    # RFC / planning docs legitimately discuss target / proposed
    # versions before plugin.json bumps (same exemption rationale
    # as CHANGELOG / RELEASE_NOTES).
    "docs/architecture/RFC_",
    "docs/architecture/RENAME_MAPPING_",
    "docs/architecture/CANONICAL_FLOW_",
    # Versioned architecture summary/reference docs carry their OWN doc/flow
    # version (the vX.Y.Z doc scheme), a namespace distinct from plugin semver,
    # in their title + filename — same exemption as CANONICAL_FLOW_ above.
    "docs/architecture/ALL_STEPS_",
    "docs/architecture/FLOW_STEPS_GENERATED",
    "docs/architecture/v2_validation/",
    # External reviewer assessment / analysis archives on the FLOW
    # (Vibe-IC_v2.3.0_Assessment.md, Vibe-IC_Flow_Completeness_Analysis.md, …).
    # Their prose discusses the flow/doc version scheme (v2.2.0 / v2.3.0 / …)
    # pervasively and verbatim — archived third-party feedback is not
    # rephraseable into historical-prefix form. Same doc-version-namespace
    # rationale as ALL_STEPS_ / CANONICAL_FLOW_ above (ORGANIC-20260606).
    "docs/architecture/Vibe-IC_",
    "_PROPOSED.md",
    # Dependency LOCKFILES enumerate the versions of every npm/node package
    # in the dependency graph ("version": "0.99.0" of some dep) — none are
    # plugin self-claims. Without this skip, mirroring an mcp-eda
    # package-lock.json into opensource_repo/ produced 484 false positives
    # (2026-06-05). Same rationale as tool-banner content skips.
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
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


# A program-internal version CONSTANT in a .py file — `VERSION = "1.0.0"`,
# `__version__ = "1.0.0"`, or a report dict's `"version": "1.0.0"` — is the
# program's OWN semver, a namespace DISTINCT from the plugin's version, so it
# is never a forward plugin claim. The motivating 9d4e984a leak was a prose
# COMMENT claim (`# … added vX.Y.Z`), which does not match this assignment
# shape, so this carve-out does not reopen that hole.
_PROG_VER_CONST_RE = re.compile(
    r"""(?:^|[^.\w])(?:VERSION|__version__)\s*=\s*["']\d+\.\d+\.\d+"""
    r"""|["']version["']\s*:\s*["']\d+\.\d+\.\d+["']"""
    # lowercase attribute / dataclass-annotated field: `version = "1.1.0"`
    # or `version: str = "1.1.0"` (the program's own semver field).
    r"""|(?:^|[^.\w])version(?:\s*:\s*\w+)?\s*=\s*["']\d+\.\d+\.\d+"""
)


def _is_program_version_constant(path: str, line: str) -> bool:
    return path.endswith(".py") and bool(_PROG_VER_CONST_RE.search(line))


def _is_filename_version(body: str, match) -> bool:
    """A version embedded in a FILENAME token (e.g. `ALL_STEPS_v2.2.0.md`,
    `CANONICAL_FLOW_v2.2.0.pdf`) is a doc/file version namespace, not a
    plugin-version claim: the match is immediately followed by a file
    extension and preceded by a filename connector / alphanumeric char."""
    if not re.match(r"\.[A-Za-z]{1,6}\b", body[match.end():]):
        return False
    before_ch = body[match.start() - 1] if match.start() > 0 else ""
    return before_ch in "_-/" or before_ch.isalnum()


# Doc-artifact version namespaces. A versioned architecture/flow document carries
# its OWN vX.Y.Z (the doc-version scheme, distinct from plugin semver) in its
# basename — `ALL_STEPS_v2.2.0`, `CANONICAL_FLOW_v2.2.0`. The doc FILES are
# already path-skipped (see _SKIP_PATH_PATTERNS), but OTHER files (a guard test,
# a README) legitimately REFERENCE the doc by name in prose — sometimes without a
# trailing extension (`ALL_STEPS_v2.2.0 docs`) or with a brace-glob
# (`ALL_STEPS_v2.2.0.{md,zh-TW.md}`) that _is_filename_version's extension check
# misses. A version-triple immediately preceded by one of these UPPERCASE
# doc-artifact basename prefixes is a doc-version reference, never a plugin
# self-claim (a real self-claim like `vibe-ic 1.2.3` is not preceded by
# `<DOCNAME>_`, so this does not reopen the 9d4e984a hole).
_DOC_ARTIFACT_PREFIXES = (
    "ALL_STEPS_", "CANONICAL_FLOW_", "FLOW_STEPS_GENERATED_",
    "FLOW_STEPS_GENERATED", "RENAME_MAPPING_", "RFC_",
)


def _is_doc_artifact_version(body: str, match) -> bool:
    """True iff the version-triple is the version suffix of a known doc-artifact
    basename (`ALL_STEPS_v2.2.0`, `CANONICAL_FLOW_v2.2.0`, …), regardless of any
    trailing extension / brace-glob — i.e. a doc-version namespace reference."""
    before = body[:match.start()]
    return any(before.endswith(pfx) for pfx in _DOC_ARTIFACT_PREFIXES)


# Recognised third-party TOOL / PDK / runtime names that carry their OWN
# X.Y.Z version. A version-triple whose immediately-preceding word is one of
# these is a DEPENDENCY version (e.g. `netgen 1.5.316`, `yosys 0.40.0`,
# `sky130 1.0.0`, `cocotb 2.0.1`), not a claim of the plugin's own version.
# Distinguishing "my version" from "a dependency's version" is something every
# version linter must do; this is a structural carve-out parallel to the
# program-version-constant and filename-version ones. It does NOT reopen a
# self-claim hole: a bare `v1.5.316`, or one preceded by `plugin` / `vibe-ic`
# / `release`, is still gated (see the regression tests).
_DEPENDENCY_TOOL_NAMES = frozenset({
    # open-source EDA backends in the IIC-OSIC-TOOLS container
    "netgen", "magic", "yosys", "openroad", "klayout", "ngspice", "ngspyce",
    "xschem", "iverilog", "icarus", "verilator", "cocotb", "openlane",
    "openlane2", "gdstk", "gdspy", "padring", "volare", "antmicro", "spice",
    # runtimes / build tooling
    "python", "python3", "node", "nodejs", "npm", "pip", "tcl", "tk",
    "gcc", "clang", "llvm", "make", "cmake", "git", "bash", "docker",
    # PDKs / foundry process names
    "sky130", "sky130a", "sky130b", "gf180", "gf180mcu", "gf180mcuc",
    "gf180mcud", "skywater", "globalfoundries",
    # external dataset/platform names whose release tags appear in benchmark
    # docs ("HF v1.1.0" = the HuggingFace dataset release, #537 family)
    "hf", "huggingface",
})

# trailing alphanumeric word after stripping the usual separators that sit
# between a tool name and its version: spaces, `(`, `-`, `/`, `:`, `=`, `@`.
_TRAILING_WORD_RE = re.compile(r"([A-Za-z][A-Za-z0-9]*)$")


def _is_dependency_tool_version(body: str, match) -> bool:
    """True iff the version-triple is the version of a recognised third-party
    tool / PDK / runtime — its immediately-preceding word is in
    `_DEPENDENCY_TOOL_NAMES`. `netgen 1.5.316` -> True; `vibe-ic 1.5.316` -> the
    trailing word is `ic` (not a tool) -> False (still gated)."""
    prefix = body[:match.start()].rstrip(" \t([-/:=@")
    m = _TRAILING_WORD_RE.search(prefix)
    if not m:
        return False
    return m.group(1).lower() in _DEPENDENCY_TOOL_NAMES


# In-repo SIBLING version namespaces. The canonical flow document carries its
# OWN vX.Y.Z scheme (flow v2.3.1 — the ALL_STEPS / CANONICAL_FLOW doc version),
# distinct from plugin semver. Plugin sources legitimately cite it in comments
# ("flow v2.3.1 (review R3) — …"). A version-triple whose immediately-preceding
# word names the namespace is that namespace's version, never a plugin
# self-claim. STRICT immediate precedence (same mechanism as the dependency
# carve-out): "the plugin flow. v0.3.0 adds X" does NOT match (the period is
# not a stripped separator), so a real forward claim stays gated.
_SIBLING_NAMESPACE_WORDS = frozenset({"flow"})


def _is_sibling_namespace_version(body: str, match) -> bool:
    """True iff the version-triple is immediately preceded by a declared
    in-repo sibling-namespace word (`flow v2.3.1` -> True)."""
    prefix = body[:match.start()].rstrip(" \t([-/:=@")
    m = _TRAILING_WORD_RE.search(prefix)
    if not m:
        return False
    return m.group(1).lower() in _SIBLING_NAMESPACE_WORDS


# Pre-reset historical version bands. vibe-ic's version scheme RESET from the old
# 1.6.x development series down to the current 0.2.x series. The 1.6.x numbers now
# live on ONLY as backward provenance references in code comments / docstrings
# (e.g. "ported from v1.6.596", "v1.6.523 tightened X") — they sort numerically
# above 0.2.x but are references to a SUPERSEDED scheme, never a forward claim of
# the current artifact's version. Any version inside a declared historical band is
# exempt. The band is the 1.6.x dev series SPECIFICALLY — it does NOT cover the
# future 1.0.x release line, so a genuine forward 1.0.x claim is still caught.
_HISTORICAL_VERSION_RANGES = (
    ((1, 6, 0), (1, 6, 999)),
)


def _in_historical_band(claimed: Tuple[int, int, int],
                        plugin_version: Tuple[int, int, int]) -> bool:
    """A version is a backward provenance ref (not a forward claim) iff it falls
    in a superseded historical band AND the plugin has since reset to BELOW that
    band — so those numbers can only be backward references. When the plugin is
    still within/above the band (e.g. the plugin genuinely IS 1.6.18), a higher
    1.6.x is a real forward claim and stays flagged."""
    return any(lo <= claimed <= hi and plugin_version < lo
               for lo, hi in _HISTORICAL_VERSION_RANGES)


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
        if _is_program_version_constant(path, body):
            continue
        for m in _VER_RE.finditer(body):
            if _looks_historical(body, m.start()):
                continue
            if _is_filename_version(body, m):
                continue
            if _is_doc_artifact_version(body, m):
                continue   # doc-version namespace (ALL_STEPS_v2.2.0 …), not a claim
            if _is_dependency_tool_version(body, m):
                continue   # third-party tool / PDK / runtime version, not a claim
            if _is_sibling_namespace_version(body, m):
                continue   # in-repo sibling namespace (flow vX.Y.Z), not a claim
            # A numeric triple whose first digit is immediately preceded by
            # an ASCII letter other than v/V is an identifier or spec-section
            # anchor (e.g. `A3.1.1`, `C3.4.1`, `FR3.1` source citations in the
            # protocol-synth requirement tables), NOT a semver. The `v?`
            # prefix is consumed by _VER_RE, so a real `vX.Y.Z` is unaffected.
            before_ch = body[m.start() - 1] if m.start() > 0 else ""
            if before_ch.isalpha() and before_ch not in "vV":
                continue
            try:
                claimed = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except (TypeError, ValueError):
                continue
            if _in_historical_band(claimed, plugin_version):
                continue   # backward provenance ref to the superseded 1.6.x scheme
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
