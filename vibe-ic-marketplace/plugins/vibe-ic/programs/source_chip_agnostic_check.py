#!/usr/bin/env python3
"""
source_chip_agnostic_check.py — anti-fabrication gate (v1.6.38).

Doctrine: plugin source code (programs/, skills/, commands/) must be
chip-AGNOSTIC. No vendor / IC / SKU / product-name strings, no
foundry-specific PDK names, no chip-specific filenames hardcoded.

`backlog_sanitize_check.py` already enforces this for community-
backlog YAML; this gate extends the same discipline to plugin source.
The v1.6.37 escape (`emit_em_report` had `j_max_ma_per_um = 2.0  #
commercial-PDK SOA M1-M4 @ 110C / 10-yr`) violated chip-AGNOSTIC in code
without ever touching a backlog file.

The list of forbidden tokens is bootstrapped from the existing
`backlog_sanitize_check.py` source (so adding a vendor name there
auto-extends this gate) plus a small explicit hardcoded set for the
benchmarks already in this monorepo.

Allowlist:
  - File paths under `plugins/vibe-ic/skills/community-backlog-submit/`
    (the skill itself describes the rule, so it MUST mention what's
    forbidden).
  - Files under `programs/_facts_yaml.py` if they reference template
    placeholders like `<vendor>`.
  - String literals INSIDE quoted regex patterns matching input docs
    (these are functional, not chip-specific code) — detected by
    surrounding `re.compile(...)` or `r"..."` raw-string syntax.

Usage:
    python3 source_chip_agnostic_check.py <plugin_root>
                                           [--json <out>]
                                           [--extra-tokens FILE]

Exit codes:
    0  PASS
    1  FAIL — at least one forbidden token in plugin source
    2  argument or I/O error, and the two states that carry NO verdict:
       NOTHING_SCANNED (the walk read zero files) and COULD_NOT_LOOK
       (vibe-ic#1476 — one or more files could not be read, so they were
       never scanned; that is not a clean bill of health for them).

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Set, Tuple

try:  # NDA tokens live encoded here; the guard reconstructs them at runtime
    import _commercial_pdk as _cpdk
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _commercial_pdk as _cpdk


# Tokens forbidden in plugin source code. Match is case-INsensitive at
# word boundaries. The canonical list lives in
# `plugins/vibe-ic/programs/tests/chip_deny_list.txt` so the same data feeds
# both this source-side gate and the CI deny-list test.
#
# Add new vendor / SKU / IC / foundry names by editing that .txt file;
# this loader will pick them up at runtime.
_DENY_PATH = (
    Path(__file__).resolve().parent
    / "tests" / "chip_deny_list.txt"
)


# ---------------------------------------------------------------------------
# vibe-ic#1476 — "could not read it" and "read it and found nothing" must never
# be recorded the same way.
#
# Every read in this gate used to be a STRICT utf-8 decode. One truncated
# multi-byte character — the byte `\xe2` with its continuation bytes cut off,
# which is what `cut -c` on an em-dash leaves behind — made that decode raise,
# and each caller turned the raise into either a silent `continue` or an
# uncaught traceback:
#
#   * `_scan_nda` caught `UnicodeDecodeError` and skipped the file. The whole
#     file left the scan, with no counter, no message and no exit code. A file
#     carrying an NDA SKU **and** one bad byte was certified clean — the exact
#     "a check that could not look reports what a check that looked and found
#     nothing reports" shape this gate exists to prevent.
#   * `audit`'s main loop caught only `OSError`, so the same byte in
#     `programs/` aborted the run with a traceback BEFORE the NDA panel below
#     it ever executed — one byte could blind the whole gate.
#
# The decode is now deliberately LOSSY, and that direction is safe by
# construction: every forbidden and every NDA token is ASCII, and
# `errors="replace"` preserves every ASCII byte verbatim while turning only
# the undecodable ones into U+FFFD. A lossy decode can therefore only ever add
# noise AROUND a match; it can never hide one, so it cannot buy a green.
# (The three sibling NDA gates already read this way — `nda_tracked_tree_scan`
# line 328, `nda_diff_scan_check` (vibe-ic#640) and `commit_msg_nda_check`.
# This file was the last strict-decoding holdout in the family.)
#
# `None` is reserved for a genuine I/O failure — the bytes themselves could not
# be obtained. That is NOT clean and NOT a violation; callers record it and the
# gate exits 2, the same "no verdict" channel `NOTHING_SCANNED` already uses.
# ---------------------------------------------------------------------------
def _read_for_scan(path: Path) -> Optional[str]:
    """Return `path`'s text for scanning, or None if its BYTES are unreadable.

    Never raises `UnicodeDecodeError`: undecodable bytes become U+FFFD rather
    than removing the file from the scan.
    """
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None


def _load_deny_tokens(path: Path) -> Tuple[str, ...]:
    """Read one-token-per-line deny list (# comments and blanks ignored)."""
    # vibe-ic#1476 — lossy decode: one truncated byte in the deny list used to
    # raise here, at import time, from a module-level initialiser. The panel
    # this list feeds must not be emptied by a byte.
    try:
        raw = path.read_bytes().decode("utf-8", errors="replace").splitlines()
    except OSError:
        # Loader is best-effort — if the deny list is missing we fall
        # back to an empty tuple and the gate reports PASS, matching
        # historical behaviour for a stripped install.
        return tuple()
    tokens = []
    for ln in raw:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        tokens.append(s)
    return tuple(tokens)


_FORBIDDEN_TOKENS: Tuple[str, ...] = (
    _load_deny_tokens(_DENY_PATH)
    # A genuinely sensitive internal project codename is NOT stored in the deny
    # list as a literal (that would be the leak). Its real value(s) come from
    # the PRIVATE config at runtime and EXTEND the forbidden set here, so a
    # re-added codename in plugin source is still caught on a configured host —
    # public/default is empty (inert), same shape as the NDA + PDK-id config.
    + tuple(_cpdk.project_codenames())
)


# ---------------------------------------------------------------------------
# STRICT NDA panel — the commercial foundry SKU / name / process tokens.
#
# These are NOT stored as plaintext anywhere (that would itself be a
# `git grep`-visible leak); they live base64-ENCODED in `_commercial_pdk.py`
# and are reconstructed at runtime here. Unlike the `_FORBIDDEN_TOKENS` panel
# above, the NDA panel has NO allowlist of any kind (no file-level, no
# line-level): a literal NDA token ANYWHERE under the plugin tree — including
# tests/ — FAILS, EXCEPT the single sanctioned encoded home (`_commercial_pdk.py`,
# which contains only the base64 forms, never a literal). This is the strengthened
# contract that guarantees `git grep <SKU>` stays 0 forever.
# ---------------------------------------------------------------------------
_NDA_TOKENS: Tuple[str, ...] = tuple(_cpdk.nda_tokens())
# The ONE file allowed to carry the (encoded) NDA tokens — its literals are
# base64, so it never actually matches, but we exempt it explicitly for clarity.
_NDA_ENCODED_HOME = "programs/_commercial_pdk.py"
# THE NDA PANEL HAD A FILE-LEVEL ALLOWLIST AND ITS OWN CONTRACT SAYS IT HAS
# NONE. Fourteen lines above: "the NDA panel has NO allowlist of any kind (no
# file-level, no line-level): a literal NDA token ANYWHERE under the plugin tree
# ... FAILS ... This is the strengthened contract that guarantees
# `git grep <SKU>` stays 0 forever."
#
# `_NDA_SCAN_EXTS` was a file-level allowlist. MEASURED 2026-08-22: 51 files
# under the plugin tree were never opened by this panel, among them the EDA
# formats most able to carry a foundry name — 7 `.rpt`, 7 `.spef`, 4 `.log`,
# 3 `.drc`, 1 `.ys`. `git grep` does not filter by extension, so a token in any
# of them would have been grep-visible while the gate promising otherwise never
# read the file. The guarantee was stated more strongly than it was delivered.
#
# NONE OF THE 51 MATCHED, checked with this panel's own regex before the change,
# so this closes a LATENT hole and reports no live leak — which is the cheapest
# moment to close it and the only one where the closing is not also an argument
# about a finding.
#
# The panel now reads EVERY file under the tree. Cost measured: 4711 -> 4762
# files, 73.7 MiB total, exactly two files over 2 MiB and both were already
# scanned. Binary content decodes lossily to noise and the tokens are
# distinctive ASCII, so a match inside one is a thing to investigate rather than
# a false alarm to design around. The extension tuple is kept ONLY as the
# census's "text-shaped" tally, so the disclosure can still say how much of what
# it read was source.
_NDA_TEXT_EXTS = (
    ".py", ".md", ".json", ".yaml", ".yml", ".tcl", ".txt",
    ".cfg", ".ini", ".sh", ".v", ".sv", ".rule", ".rules", ".lib",
)



#: Directories that are GENERATED, never committed, and therefore not part of a
#: denominator that claims to be a property of the commit.
#:
#: THIS WAS A LIST OF THREE NAMES AND THE LIST WENT OUT OF DATE — the same
#: failure it was written to fix. The comment below records
#: `.pytest_cache/README.md` making this gate report 4343 files on one arm and
#: 4342 on the other. MEASURED again 2026-08-22: 4710 vs 4766, a 56-file gap
#: from `programs/tests/fixtures/synthetic_benchmark_phase1/`, which
#: `.gitignore:127` calls "Test-generated synthetic fixtures (rebuilt by
#: build_synthetic_benchmark_phase1)". A third generator was added and the
#: hardcoded triple did not follow it, so `gates are host-independent` reported
#: HOST_DEPENDENT_VERDICT for this gate in any checkout a test had run in.
#:
#: The set is now ASKED OF GIT rather than remembered. A file git ignores is by
#: construction absent from the commit; a merely UNTRACKED file is still
#: scanned, because a forbidden token in a file about to be committed is exactly
#: what this gate is for.
_GENERATED_DIR_NAMES = ("__pycache__", ".pytest_cache", ".git")


def _git_ignored_prefixes(root: Path) -> Optional[Set[str]]:
    """Repo-relative paths git ignores, or None if git could not be asked.

    None is NOT an empty set: "git says nothing is ignored" is a measurement and
    "there is no git here" is a fallback the census has to disclose, and folding
    them together is the substitution this repository refuses everywhere else.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--ignored",
             "--exclude-standard", "--directory"],
            capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return {ln.strip().rstrip("/") for ln in out.stdout.splitlines() if ln.strip()}


def _build_nda_re() -> re.Pattern:
    # SUBSTRING match (no word boundaries) — the NDA tokens are distinctive
    # enough to never false-positive, and substring matching makes this guard
    # exactly as strict as the `git grep <SKU>` gate it enforces (so e.g.
    # `<SKU>_typ.lib` and `Calibre_<SKU>_DRC.rule` are both caught).
    toks = sorted(set(_NDA_TOKENS), key=len, reverse=True)
    if not toks:
        # No tokens (should never happen) -> a never-matching pattern.
        return re.compile(r"(?!x)x")
    escaped = [re.escape(t) for t in toks]
    return re.compile("(" + "|".join(escaped) + ")", re.IGNORECASE)


# File / directory patterns whose content is allowed to mention the
# above tokens (because the file IS the documentation about them, or
# is a regex-pattern store keyed on these tokens for input-doc parsing).
#
# RATIONALE for each entry:
#   - `skills/community-backlog-submit/` — the skill explains the
#     forbidden-token rule, so it MUST mention what's forbidden.
#   - `skills/backlog-sanitize/` — same as above (backlog sanitization
#     SKILL.md describes the redaction patterns).
#   - `programs/backlog_sanitize_check.py` — the YAML-side companion
#     of this gate; its source enumerates the forbidden tokens.
#   - `programs/source_chip_agnostic_check.py` — this file itself
#     enumerates the forbidden tokens.
#   - `programs/tests/` — test fixtures. Several test programs
#     exercise redaction logic (test_practical_notes_*, test_backlog_*,
#     test_source_chip_agnostic_check.py) and MUST contain the tokens
#     to verify detection. Other tests use realistic-looking fixture
#     IC ids (e.g. ic_id="ic-a") as inert test data; treating those
#     as gate violations would force every test fixture to invent
#     synthetic chip names, which provides no chip-AGNOSTIC value.
#   - `programs/INDEX.md` — auto-generated by tools/gen_programs_index.py
#     from program docstrings. After source docstrings are clean, the
#     index regenerates clean too; flagging it directly is redundant.
_ALLOWLIST_PATTERNS: Tuple[str, ...] = (
    "skills/community-backlog-submit/",
    "skills/backlog-sanitize/",
    "programs/backlog_sanitize_check.py",
    "programs/source_chip_agnostic_check.py",
    "programs/tests/",
    "programs/INDEX.md",
)


@dataclass
class TokenFinding:
    file: str
    line: int
    token: str
    context: str
    rule: str = "FORBIDDEN_VENDOR_TOKEN"


def _is_allowlisted(rel_path: str) -> bool:
    rel_norm = rel_path.replace("\\", "/")
    return any(p in rel_norm for p in _ALLOWLIST_PATTERNS)


def _build_token_re(extra: Optional[List[str]] = None) -> re.Pattern:
    tokens = list(_FORBIDDEN_TOKENS)
    if extra:
        tokens.extend(extra)
    # Word-boundary-ish match: token must be preceded / followed by a
    # non-alphanumeric char or string boundary. Hyphens count as part
    # of the token (so a hyphenated SKU matches as a unit).
    escaped = [re.escape(t) for t in sorted(set(tokens), key=len, reverse=True)]
    pattern = r"(?<![A-Za-z0-9_])(" + "|".join(escaped) + r")(?![A-Za-z0-9_])"
    return re.compile(pattern, re.IGNORECASE)


# Filled by `audit` on every call: how much this gate actually looked at.
# A PASS with no denominator cannot be told apart from a PASS that scanned
# NOTHING, and this repo has now hit that defect in four separate programs
# (nda_tracked_tree_scan on 21 of 20143 blobs; l4_systemrdl_export on 0 of
# 201 documents; cross_layer_reference_check on 46 vs 23; and this one).
SCAN_CENSUS: Dict[str, int] = {}

# vibe-ic#1476 — the paths whose BYTES this run could not obtain, in the order
# met. A count alone cannot be acted on; the reader needs the names. Reset by
# `audit` alongside SCAN_CENSUS, so a stale list cannot make a healthy run
# refuse (and, more importantly, a stale EMPTY list cannot make a blind run
# certify).
UNREADABLE: List[str] = []


def audit(plugin_root: Path,
          extra_tokens: Optional[List[str]] = None
          ) -> Tuple[str, List[TokenFinding]]:
    findings: List[TokenFinding] = []
    SCAN_CENSUS.clear()
    UNREADABLE.clear()
    if not plugin_root.is_dir():
        return "VACUOUS_PASS", []

    token_re = _build_token_re(extra_tokens)

    # Walk plugins/vibe-ic/{programs, skills, commands}
    targets: List[Path] = []
    for sub in ("programs", "skills", "commands"):
        d = plugin_root / sub
        if d.is_dir():
            for ext in ("*.py", "*.md", "*.json", "*.yaml", "*.tcl"):
                targets.extend(d.rglob(ext))

    SCAN_CENSUS["files_found"] = len(targets)
    for sub in ("programs", "skills", "commands"):
        d = plugin_root / sub
        SCAN_CENSUS[f"dir_{sub}"] = (
            sum(1 for _ in d.rglob("*") if _.is_file()) if d.is_dir() else -1)

    scanned = 0
    unreadable: List[str] = []
    for f in targets:
        rel = f.relative_to(plugin_root)
        rel_str = str(rel)
        if _is_allowlisted(rel_str):
            continue
        # vibe-ic#1476 — see `_read_for_scan`. Strict decoding used to raise
        # out of this loop entirely; an OSError used to `continue` unrecorded.
        text = _read_for_scan(f)
        if text is None:
            unreadable.append(rel_str)
            continue
        scanned += 1
        for ln_no, line in enumerate(text.splitlines(), start=1):
            for m in token_re.finditer(line):
                tok = m.group(1)
                # Extract context — short snippet around the match
                start = max(0, m.start() - 20)
                end = min(len(line), m.end() + 20)
                ctx = line[start:end].strip()
                findings.append(TokenFinding(
                    file=rel_str,
                    line=ln_no,
                    token=tok,
                    context=ctx,
                ))

    SCAN_CENSUS["files_read"] = scanned
    SCAN_CENSUS["files_unreadable"] = len(unreadable)
    UNREADABLE.extend(unreadable)

    # STRICT NDA pass — commercial foundry SKU/name/process tokens, scanned over
    # the WHOLE plugin tree (every text file, tests/ included), with NO allowlist
    # except the single encoded home. This is the strengthened grep-0 contract.
    findings.extend(_scan_nda(plugin_root))

    # One path can be met by BOTH walks (the source walk over
    # programs/skills/commands, and the tree-wide NDA walk). Report it once:
    # a doubled count would MISSTATE the exposure, and a number that overstates
    # is no more trustworthy than one that understates.
    UNREADABLE[:] = list(dict.fromkeys(UNREADABLE))
    SCAN_CENSUS["unreadable_unique"] = len(UNREADABLE)

    if findings:
        return "FAIL", findings
    # vibe-ic#1476 — a file whose BYTES could not be obtained leaves this run
    # with no verdict over it. Reporting PASS would be the defect this issue is
    # about, one level up: a gate that could not look, answering like a gate
    # that looked and found nothing. Ranked BELOW FAIL, because a leak that was
    # actually seen is the more actionable answer.
    if UNREADABLE:
        return "COULD_NOT_LOOK", findings
    return "PASS", findings


def _scan_nda(plugin_root: Path) -> List[TokenFinding]:
    """Scan the entire plugin tree for literal NDA foundry tokens. No allowlist
    (tests/ included); only the encoded home `_commercial_pdk.py` is exempt.

    Writes its denominator into `SCAN_CENSUS` and any unreadable path into
    `UNREADABLE`; `audit` owns the reset of both, exactly as it already did for
    the census.
    """
    out: List[TokenFinding] = []
    nda_re = _build_nda_re()
    found = 0
    read = 0
    # Asked ONCE per scan and DISCLOSED: a denominator computed with git
    # consulted and one computed without it are different measurements.
    text_shaped = 0
    _ignored = _git_ignored_prefixes(plugin_root)
    ignored_prefixes = _ignored if _ignored is not None else set()
    SCAN_CENSUS["nda_ignore_source"] = (
        "git" if _ignored is not None else "names-only (git could not be asked)")
    SCAN_CENSUS["nda_ignored_prefixes"] = len(ignored_prefixes)
    for f in plugin_root.rglob("*"):
        if not f.is_file():
            continue
        parts = f.parts
        # Runtime caches are not source and are deliberately absent from a
        # fresh worktree at the same commit.  Counting their README/metadata
        # files makes this gate's denominator depend on whether pytest happened
        # to run in the checkout first (measured: 4343 vs 4342 files solely
        # because ``.pytest_cache/README.md`` existed on one arm).
        if any(n in parts for n in _GENERATED_DIR_NAMES):
            continue
        rel_str = str(f.relative_to(plugin_root))
        rel_posix = rel_str.replace("\\", "/")
        if any(rel_posix == p or rel_posix.startswith(p + "/")
               for p in ignored_prefixes):
            continue
        if rel_str.replace("\\", "/") == _NDA_ENCODED_HOME:
            continue
        found += 1
        if f.suffix.lower() in _NDA_TEXT_EXTS:
            text_shaped += 1
        # vibe-ic#1476 — THE instance. `except (OSError, UnicodeDecodeError):
        # continue` dropped the entire file from the strictest gate in this
        # repo, silently. Measured on this tree: a file carrying an NDA SKU
        # scanned FAIL; the byte-identical file plus ONE bare 0xE2 scanned
        # PASS. Now the bytes are decoded lossily (ASCII tokens survive
        # intact), and only an I/O failure can remove a file — which is
        # counted, named, and turned into exit 2 by `audit` / `main`.
        text = _read_for_scan(f)
        if text is None:
            UNREADABLE.append(rel_str)
            continue
        read += 1
        for ln_no, line in enumerate(text.splitlines(), start=1):
            for m in nda_re.finditer(line):
                start = max(0, m.start() - 20)
                end = min(len(line), m.end() + 20)
                out.append(TokenFinding(
                    file=rel_str,
                    line=ln_no,
                    token=m.group(1),
                    context=line[start:end].strip(),
                    rule="FORBIDDEN_NDA_SKU",
                ))
    # The NDA panel's own denominator. It had none: a panel that walked zero
    # files and a panel that walked the whole tree both returned `[]`, and
    # `audit` turned both into the same PASS line.
    SCAN_CENSUS["nda_files_found"] = found
    SCAN_CENSUS["nda_text_shaped"] = text_shaped
    SCAN_CENSUS["nda_files_read"] = read
    SCAN_CENSUS["nda_files_unreadable"] = found - read
    return out


# ---------------------------------------------------------------------------
# Lightweight public API used by tests/test_chip_agnostic_guard.py.
#
# `scan` returns a flat list of (rel_path, line_no, token) triples — the
# minimal shape the CI guard test consumes — by delegating to `audit`.
# `_load_deny_list` is a thin alias for `_load_deny_tokens` (the test
# imports it under the externalized-deny-list name).
# ---------------------------------------------------------------------------
def _load_deny_list(path: Path) -> Tuple[str, ...]:
    """Alias for `_load_deny_tokens` — externalized deny-list loader."""
    return _load_deny_tokens(path)


def scan(plugin_root: Path,
         extra_tokens: Optional[List[str]] = None
         ) -> List[Tuple[str, int, str]]:
    """Scan plugin source and return (rel_path, line_no, token) triples
    for every forbidden-token occurrence. Empty list == clean tree."""
    _verdict, findings = audit(Path(plugin_root), extra_tokens=extra_tokens)
    return [(f.file, f.line, f.token) for f in findings]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Anti-fabrication: detect chip / vendor / SKU "
                    "names hardcoded in plugin source.")
    ap.add_argument("plugin_root")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--extra-tokens",
                    help="comma-separated extra forbidden tokens")
    args = ap.parse_args(argv)

    root = Path(args.plugin_root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    extra = []
    if args.extra_tokens:
        extra = [t.strip() for t in args.extra_tokens.split(",")
                 if t.strip()]

    verdict, findings = audit(root, extra_tokens=extra)
    report = {
        "gate": "source_chip_agnostic_check",
        "verdict": verdict,
        "plugin_root": str(root),
        "forbidden_tokens": list(_FORBIDDEN_TOKENS) + extra,
        "findings_count": len(findings),
        "scan_census": dict(SCAN_CENSUS),
        # vibe-ic#1476 — machine-readable too, so a consumer of the JSON is not
        # left inferring "clean" from an absent field.
        "unreadable": list(UNREADABLE[:200]),
        "findings": [asdict(f) for f in findings[:200]],
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print("VACUOUS_PASS: plugin_root not a directory")
        return 0
    _read = SCAN_CENSUS.get("files_read", 0)
    if verdict == "PASS" and _read == 0:
        # NOT a PASS. Scanning nothing and finding nothing is what a WRONG
        # ROOT looks like, and the output was previously byte-identical to a
        # real clean scan of a thousand files.
        print("NOTHING_SCANNED: this gate read 0 files under "
              f"{root}/{{programs,skills,commands}} — "
              f"per-dir file counts {{{', '.join(f'{k}={v}' for k, v in sorted(SCAN_CENSUS.items()) if k.startswith('dir_'))}}}. "
              "A clean result over an empty scan is not a clean result; check "
              "the plugin_root argument.", file=sys.stderr)
        return 2
    if verdict == "COULD_NOT_LOOK":
        # vibe-ic#1476 — NOT a PASS. These files were never scanned, so this
        # run carries no verdict over them. Exit 2 is the same "no verdict"
        # channel NOTHING_SCANNED above already uses, and it is deliberately
        # not 0: "I could not read it" must never print what "I read it and
        # found nothing" prints.
        print(f"COULD_NOT_LOOK: {len(UNREADABLE)} file(s) under {root} could "
              "not be read, so they were NOT scanned. This run is not a clean "
              "bill of health for them.", file=sys.stderr)
        for p in sorted(UNREADABLE)[:15]:
            print(f"  {p}", file=sys.stderr)
        if len(UNREADABLE) > 15:
            print(f"  … and {len(UNREADABLE) - 15} more", file=sys.stderr)
        return 2
    if verdict == "PASS":
        print(f"PASS ({_read} file(s) scanned): "
              "no forbidden chip / vendor / SKU tokens in "
              "plugin source (programs/ skills/ commands/); "
              f"NDA panel read {SCAN_CENSUS.get('nda_files_read', 0)} of "
              f"{SCAN_CENSUS.get('nda_files_found', 0)} file(s) tree-wide")
        return 0
    print(f"FAIL: {len(findings)} forbidden-token occurrence(s):",
          file=sys.stderr)
    by_file: dict = {}
    for f in findings:
        by_file.setdefault(f.file, 0)
        by_file[f.file] += 1
    for fp, cnt in sorted(by_file.items())[:15]:
        print(f"  {fp}: {cnt} hit(s)", file=sys.stderr)
    if len(by_file) > 15:
        print(f"  … and {len(by_file) - 15} more files", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
