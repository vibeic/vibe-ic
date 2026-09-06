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
    kind: str = "command"   # "command" (must sit in TCL command position)
                            # or "flag" (an option word, never in command
                            # position -- position tells us nothing).


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
        kind="flag",
    ),
    Deprecation(
        token="-top_routing_layer",
        pattern=re.compile(r"(?<![\w\-])-top_routing_layer\b"),
        version="OpenROAD 2024+",
        replacement=(
            "use `set_routing_layers -signal <bottom>-<top>` OR "
            "`global_route -congestion_iterations` (flag removed)"
        ),
        kind="flag",
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


# A deprecated token that is a COMPLETE quoted string used as a dict key or a
# subscript index is a DATA FIELD NAME, never a TCL command. Measured
# 2026-09-03 on live main 637cdf091 (v1.16.82): commit 4277b34a1 gave the
# dummy-fill spec a dict field literally named `write_gds` (`{"write_gds":
# gds[...]}`, `lay["write_gds"]`), and this gate reported 9 hits over it. That
# FAIL is a P0 structural gate, so phase 2's `final_audit` failed, the
# orchestrator halted at phase 2, and NO design on main reached phase 3 — on a
# tree with no OpenROAD TCL problem at all. The gate already carried the sibling
# exclusion for Python call/def syntax (`write_gds(`, added 1910a37ca); this is
# the same class it missed.
#
# The rule is deliberately NARROW: quote, token, the SAME quote, then `]` or
# `:`. That is Python/JSON subscript-or-key grammar and nothing else.
# It cannot mask a real emission —
#   `write_gds $out`            no quotes           -> still flagged
#   `f"write_gds {out}"`        no closing quote    -> still flagged
#   `["write_gds", $out]`       followed by `,`     -> still flagged
# — so the gate keeps its full power over every shape that actually reaches an
# OpenROAD interpreter. chip/PDK/vendor-AGNOSTIC: pure source grammar.
_DATA_KEY_TAIL = re.compile(r"\s*[\]:]")


def _is_data_key(line: str, start: int, end: int) -> bool:
    """Is the match at [start:end) a quoted dict key / subscript index?"""
    if start == 0 or end >= len(line):
        return False
    q = line[start - 1]
    if q not in ("'", '"') or line[end] != q:
        return False
    return bool(_DATA_KEY_TAIL.match(line, end + 1))


# ---------------------------------------------------------------------------
# CONTEXT, NOT BASENAME.
#
# MEASURED 2026-09-07 on main 4fc47b3ef (v1.18.13), host 8HD-8. v1.18.9 added
# `programs/tests/test_the_technology_answers_the_precheck_not_the_declaration.py`,
# whose line 59 is the continuation of a plain Python import:
#
#     from test_general_precheck import (
#         write_gds, _rect, _project, _step, _NEVER_RAN)
#
# `write_gds` there is a PYTHON IDENTIFIER -- a name bound in a sibling test
# module. This gate read it as a deprecated OpenROAD TCL command, so the P0
# structural umbrella FAILED, `flow_compliance_check` returned rc=1, phase 2
# halted and NO design on main reached phase 3. That is the THIRD file of this
# class (after `write_gds(` call/def syntax, 1910a37ca, and the quoted dict key
# `{"write_gds": ...}`, 2026-09-03); each previous repair added the offending
# FILE to a basename allowlist, which by construction cannot see the fourth
# file. This repair is by CONTEXT instead, so there is no fourth file to add.
#
# The distinction the gate now makes:
#
#   * a `.tcl` file  -- every line is TCL source. Scanned whole, exactly as
#                       before. No power is given up.
#   * a `.py` file   -- TCL can only reach an OpenROAD interpreter from a
#                       STRING LITERAL (the shape the runners emit into their
#                       scripts). Python identifiers, imports, attributes,
#                       keywords, argument names and comments are tokenized
#                       and are never TCL.
#   * `.md`/`.yaml`/`.yml`/`.js`
#                    -- no reliable grammar to tokenize; unchanged line scan.
#
# Inside a `.py` string literal a COMMAND token additionally has to sit in TCL
# COMMAND POSITION -- start of the string's content, start of a line inside a
# triple-quoted / escaped-newline string, or straight after `;`, `[` or `{`.
# That is where a TCL interpreter looks for a command word and nowhere else, so
# the token named mid-expression inside a regex is not a call while
# `f"write_gds {out}"` still is. A `kind="flag"` token is an OPTION word which
# by definition never occupies command position, so for flags the
# string-literal restriction is the whole rule.
#
# chip / PDK / vendor-AGNOSTIC: pure source grammar, no design literals.
# ---------------------------------------------------------------------------

# Opening prefix + quote of a Python string token, e.g. rb\"\"\", f', ".
_PY_STR_OPEN = re.compile(r"^[A-Za-z]*('''|\"\"\"|'|\")")


def _py_string_content_mask(text: str) -> Dict[int, List[Tuple[int, int]]]:
    """Map 1-based line number -> the column spans that are the CONTENT of a
    Python string literal on that line (quotes and prefix excluded).

    Raises whatever ``tokenize`` raises on an unparsable file; the caller then
    falls back to the plain line scan rather than silently exempting it -- an
    unparsable file must never become a blind spot.
    """
    import io
    import tokenize as _tk

    spans: Dict[int, List[Tuple[int, int]]] = {}

    lines = text.splitlines()

    def _linelen(row: int) -> int:
        return len(lines[row - 1]) if 1 <= row <= len(lines) else 0

    def _add(row: int, c0: int, c1: int) -> None:
        if c1 > c0:
            spans.setdefault(row, []).append((c0, c1))

    def _add_range(srow, scol, erow, ecol):
        if srow == erow:
            _add(srow, scol, ecol)
        else:
            _add(srow, scol, _linelen(srow))
            for r in range(srow + 1, erow):
                _add(r, 0, _linelen(r))
            _add(erow, 0, ecol)

    fstring_middle = getattr(_tk, "FSTRING_MIDDLE", None)
    for tok in _tk.generate_tokens(io.StringIO(text).readline):
        if fstring_middle is not None and tok.type == fstring_middle:
            # Python 3.12+ hands back the f-string's literal text directly,
            # already free of prefix and quotes.
            _add_range(tok.start[0], tok.start[1], tok.end[0], tok.end[1])
            continue
        if tok.type != _tk.STRING:
            continue
        m = _PY_STR_OPEN.match(tok.string)
        if not m:
            continue
        open_len = m.end()
        close_len = len(m.group(1))
        (srow, scol), (erow, ecol) = tok.start, tok.end
        if srow == erow:
            _add(srow, scol + open_len, ecol - close_len)
        else:
            _add(srow, scol + open_len, _linelen(srow))
            for r in range(srow + 1, erow):
                _add(r, 0, _linelen(r))
            _add(erow, 0, ecol - close_len)
    return spans


def _in_span(spans: List[Tuple[int, int]], start: int, end: int) -> bool:
    """Is [start, end) wholly inside one string-literal content span?"""
    return any(c0 <= start and end <= c1 for c0, c1 in spans)


def _col_in_span(spans: List[Tuple[int, int]], col: int) -> bool:
    return any(c0 <= col < c1 for c0, c1 in spans)


def _is_tcl_command_position(line: str, spans: List[Tuple[int, int]],
                             start: int) -> bool:
    """Does the match at column ``start`` sit where a TCL interpreter reads a
    COMMAND WORD? True at the start of the enclosing string literal's content
    on this physical line (which is also the start of every line of a
    triple-quoted script), after a source-level newline escape, or straight
    after ``;``, ``[`` or ``{``."""
    j = start - 1
    while j >= 0 and line[j] in " \t":
        j -= 1
    if j < 0:
        return True
    if not _col_in_span(spans, j):
        # Walked out of the string literal: everything to the left on this
        # line is the opening quote/prefix, so this IS the content start.
        return True
    if line[j] in ";[{":
        return True
    if line[j] == "n" and j >= 1 and line[j - 1] == "\\":
        return True
    return False


def _self_exempt(path_str: str) -> bool:
    """The two files that CONTEXT CANNOT DECIDE, and only those two.

    Both must spell the deprecated tokens as ordinary Python string literals in
    positions byte-for-byte identical to a real emission, so no grammar rule
    can separate them from one:

      * ``programs/openroad_tcl_deprecation_check.py`` -- this program. Its
        rule table declares ``token=`` <the token>; that literal is the same
        string a runner would emit as a one-word TCL command. Matched by FILE
        IDENTITY (``samefile``), not by name, so a copy placed elsewhere is
        still judged and an unrelated file that happens to share the name is
        not exempt.
      * ``programs/tests/test_openroad_tcl_deprecation_check.py`` -- this
        program's own test. Its fixtures exist precisely to prove the gate
        still flags a real emission, so they MUST look like one. Matched on
        the full relative path ``programs/tests/<name>``, not the bare
        basename, so a new file elsewhere cannot inherit the exemption by
        choosing a name.

    Nothing else is exempt. A fourth file of this class is now judged by
    grammar, which is what the previous three repairs each failed to do.
    """
    try:
        if os.path.samefile(path_str, os.path.abspath(__file__)):
            return True
    except OSError:
        pass
    norm = os.path.normpath(path_str).replace(os.sep, "/")
    return norm.endswith(
        "programs/tests/test_openroad_tcl_deprecation_check.py")


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
        # A .py file is TCL only inside a string literal (see "CONTEXT, NOT
        # BASENAME" above). str_spans is None for every other suffix, and
        # also for a .py file we could not tokenize -- in which case we fall
        # back to the unrestricted line scan, because an unparsable file must
        # stay VISIBLE to the gate rather than become a silent blind spot.
        str_spans: Optional[Dict[int, List[Tuple[int, int]]]] = None
        if suffix == ".py":
            try:
                str_spans = _py_string_content_mask("".join(lines))
            except Exception as exc:   # noqa: BLE001 - see below
                # Deliberately broad: tokenize raises SyntaxError,
                # IndentationError AND tokenize.TokenError ("unexpected EOF in
                # multi-line statement"), and a NEW failure mode must degrade
                # to the unrestricted line scan, never to an unhandled
                # traceback and never to a silent exemption.
                print(f"[openroad_tcl_deprecation_check] WARN: cannot "
                      f"tokenize {fpath} ({exc}); scanning it line-wise "
                      f"without Python context", file=sys.stderr)
                str_spans = None
        for idx, raw in enumerate(lines, start=1):
            line = raw.rstrip("\n")
            if _is_in_comment(line, suffix):
                continue
            if _is_documentary(line):
                # Line is discussing the removal (docstring, SKILL.md prose,
                # changelog entry) — not a live invocation. Skip.
                continue
            spans = None if str_spans is None else str_spans.get(idx, [])
            for dep in _DEPRECATIONS:
                m = next(
                    (mm for mm in dep.pattern.finditer(line)
                     if not _is_data_key(line, mm.start(), mm.end())
                     and (spans is None or (
                         _in_span(spans, mm.start(), mm.end())
                         and (dep.kind != "command"
                              or _is_tcl_command_position(
                                  line, spans, mm.start()))))),
                    None)
                if m is not None:
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
