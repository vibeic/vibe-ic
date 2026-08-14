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
    2  argument or I/O error

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
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


def _load_deny_tokens(path: Path) -> Tuple[str, ...]:
    """Read one-token-per-line deny list (# comments and blanks ignored)."""
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
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
# Text file extensions scanned for the strict NDA panel across the WHOLE tree.
_NDA_SCAN_EXTS = (
    ".py", ".md", ".json", ".yaml", ".yml", ".tcl", ".txt",
    ".cfg", ".ini", ".sh", ".v", ".sv", ".rule", ".rules", ".lib",
)


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


def audit(plugin_root: Path,
          extra_tokens: Optional[List[str]] = None
          ) -> Tuple[str, List[TokenFinding]]:
    findings: List[TokenFinding] = []
    SCAN_CENSUS.clear()
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
    for f in targets:
        rel = f.relative_to(plugin_root)
        rel_str = str(rel)
        if _is_allowlisted(rel_str):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
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

    # STRICT NDA pass — commercial foundry SKU/name/process tokens, scanned over
    # the WHOLE plugin tree (every text file, tests/ included), with NO allowlist
    # except the single encoded home. This is the strengthened grep-0 contract.
    findings.extend(_scan_nda(plugin_root))

    return ("FAIL" if findings else "PASS"), findings


def _scan_nda(plugin_root: Path) -> List[TokenFinding]:
    """Scan the entire plugin tree for literal NDA foundry tokens. No allowlist
    (tests/ included); only the encoded home `_commercial_pdk.py` is exempt."""
    out: List[TokenFinding] = []
    nda_re = _build_nda_re()
    for f in plugin_root.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in _NDA_SCAN_EXTS:
            continue
        parts = f.parts
        if "__pycache__" in parts or ".git" in parts:
            continue
        rel_str = str(f.relative_to(plugin_root))
        if rel_str.replace("\\", "/") == _NDA_ENCODED_HOME:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
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
    if verdict == "PASS":
        print(f"PASS ({_read} file(s) scanned): "
              "no forbidden chip / vendor / SKU tokens in "
              "plugin source (programs/ skills/ commands/)")
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
