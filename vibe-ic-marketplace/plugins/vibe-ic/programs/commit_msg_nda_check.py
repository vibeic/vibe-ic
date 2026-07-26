#!/usr/bin/env python3
"""commit_msg_nda_check.py — NDA guard for commit MESSAGE text.

WHY THIS EXISTS
---------------
`source_chip_agnostic_check.py` scans SOURCE FILES only. A commit whose *message*
carries the commercial-foundry SKU / brand / process codename therefore sails
straight through every existing gate — and one really did land on `origin/main`
AFTER the full-history NDA rewrite. The commit message is a permanent, publicly
mirrored artifact (GitHub UI, `git log`, release notes, PR titles), so a token in
it is exactly as much of a leak as a token in a `.py` file.

This program closes that surface. It is the MESSAGE-side twin of the source guard
and shares the same encoded token store, so the two can never drift apart.

DESIGN CONSTRAINTS
------------------
  * NO LITERAL TOKEN IN THIS FILE. The tokens come from `_commercial_pdk`, which
    reconstructs them at RUNTIME from base64. A detector that spelled out the SKU
    would itself be a leak `git grep` finds — and would trip the source guard.
  * MASKED REPORTING. A finding prints the token's ROLE (`<NDA-TOKEN:sku_full>`)
    plus the surrounding words, never the literal token. So the guard's own
    output is safe to paste into a CI log, an issue, or a tracked report.
  * CHIP-AGNOSTIC / DETERMINISTIC. Pure regex over text; no chip names, no
    heuristics, no network, same verdict on every host.

MODES
-----
  --message-file <path>   scan one message file        (git `commit-msg` hook)
  --rev-range <A..B>      scan every commit's message  (pre-push / CI / audit)
  --stdin                 scan a message on stdin      (ad-hoc / piping)

EXIT CODES
----------
  0  PASS  — no NDA token in any scanned message
  1  FAIL  — at least one NDA token found (the leak is blocked)
  2  ERROR — bad usage / unreadable input / git failure (fail LOUD, never silent)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _commercial_pdk as _cpdk  # noqa: E402


GATE_NAME = "commit_msg_nda_check"

# How many characters of context to keep either side of a hit. Enough to make
# the finding actionable ("which sentence?") without quoting a paragraph.
_CONTEXT_CHARS = 32


# ---------------------------------------------------------------------------
# Token table: ROLE -> token, built at runtime from the encoded store.
# ---------------------------------------------------------------------------
def token_roles() -> Dict[str, str]:
    """Map each NDA token role -> its decoded literal.

    Roles come straight from `_commercial_pdk._ENCODED_NDA`'s keys, so adding a
    token there automatically extends this guard — no edit here, no drift
    between the source guard and the message guard."""
    return {role: _cpdk._dec(role) for role in _cpdk._ENCODED_NDA}


def message_regex() -> "re.Pattern[str]":
    """Case-insensitive alternation over EVERY NDA token (SKU family + foundry
    brands + IP vendor/part), longest-first so the most specific token wins.

    Deliberately WIDER than `nda_source_regex()`: that one covers the process /
    SKU codename family, while a commit message leaks just as badly by naming
    the foundry / IP BRAND ("...built at <brand>..."). Delegates to the shared
    `_commercial_pdk.nda_content_regex()` so the message guard and the diff
    guard (`nda_diff_scan_check`) can never drift — one token store, one
    boundary rule, both scanners."""
    return _cpdk.nda_content_regex()


def _role_of(matched: str) -> str:
    """Reverse-map a matched substring to its token ROLE, for masked reporting.
    Delegates to the shared `_commercial_pdk.nda_role_of()`."""
    return _cpdk.nda_role_of(matched)


# ---------------------------------------------------------------------------
# Findings.
# ---------------------------------------------------------------------------
@dataclass
class MsgFinding:
    """One NDA hit. `context` is MASKED — the literal token is replaced by
    `<NDA-TOKEN:role>` so this record is safe to write to a tracked artifact."""
    source: str          # "message-file:<path>" | "commit:<sha>" | "stdin"
    commit: str          # short sha when known, else ""
    line: int            # 1-based line number within the message
    role: str            # NDA token role, e.g. "sku_full"
    masked_context: str  # surrounding words with the token masked out


def _mask_line(line: str, m: "re.Match[str]", role: str) -> str:
    """Return the neighbourhood of the hit with the literal token replaced by
    `<NDA-TOKEN:role>`. Never returns the token itself."""
    start = max(0, m.start() - _CONTEXT_CHARS)
    end = min(len(line), m.end() + _CONTEXT_CHARS)
    before = line[start:m.start()]
    after = line[m.end():end]
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(line) else ""
    return f"{prefix}{before}<NDA-TOKEN:{role}>{after}{suffix}".strip()


def scan_message(message: str, *, source: str, commit: str = "") -> List[MsgFinding]:
    """Scan one commit-message body. Returns every NDA hit (may be several)."""
    rx = message_regex()
    out: List[MsgFinding] = []
    for ln_no, line in enumerate(message.splitlines(), start=1):
        # A comment line in a git message template (`# Please enter...`, the
        # diff git appends under `--verbose`) is stripped by git before the
        # commit is created, so it cannot leak. Skip it to avoid a false FAIL
        # on a message file whose scissors section quotes a file path.
        if line.lstrip().startswith("#"):
            continue
        for m in rx.finditer(line):
            role = _role_of(m.group(1))
            out.append(MsgFinding(source=source, commit=commit, line=ln_no,
                                  role=role,
                                  masked_context=_mask_line(line, m, role)))
    return out


# ---------------------------------------------------------------------------
# Git access for --rev-range.
# ---------------------------------------------------------------------------
_SEP = "\x1e"  # ASCII record separator — cannot occur in a sane commit message.


def _git(repo: Path, *args: str) -> Tuple[int, str, str]:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def commits_in_range(repo: Path, rev_range: str) -> List[Tuple[str, str]]:
    """Return [(short_sha, full message)] for every commit in `rev_range`.

    `rev_range` is anything `git log` accepts and is split on whitespace into
    separate git arguments, so all of these work:
        "A..B"                     a plain range (commit-msg / PR path)
        "origin/main"              a whole branch history (audit path)
        "<sha> --not --remotes"    a new branch's own commits (pre-push path)

    Raises RuntimeError on a git failure — an unwalkable range must FAIL LOUD,
    never be reported as a clean scan (a silently-empty scan is exactly how a
    guard becomes decorative)."""
    parts = rev_range.split()
    if not parts:
        raise RuntimeError("empty --rev-range")
    rc, out, err = _git(repo, "log", f"--format=%h{_SEP}%B{_SEP}{_SEP}", *parts)
    if rc != 0:
        raise RuntimeError(f"git log {rev_range!r} failed: {err.strip()[:300]}")
    commits: List[Tuple[str, str]] = []
    for rec in out.split(_SEP + _SEP):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        sha, _, body = rec.partition(_SEP)
        commits.append((sha.strip(), body))
    return commits


def scan_rev_range(repo: Path, rev_range: str) -> Tuple[List[MsgFinding], int]:
    """Scan every commit message in the range. Returns (findings, n_commits)."""
    commits = commits_in_range(repo, rev_range)
    findings: List[MsgFinding] = []
    for sha, body in commits:
        findings.extend(scan_message(body, source=f"commit:{sha}", commit=sha))
    return findings, len(commits)


# ---------------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------------
def _print_findings(findings: List[MsgFinding], scanned: int) -> None:
    print(f"FAIL: {len(findings)} NDA token occurrence(s) in commit "
          f"message text ({scanned} message(s) scanned)", file=sys.stderr)
    print("      A commit MESSAGE is a permanent public artifact — the "
          "foundry / SKU / process name must not appear in it.", file=sys.stderr)
    for f in findings[:40]:
        loc = f"{f.source}:{f.line}"
        print(f"  {loc}  role={f.role}\n      {f.masked_context}",
              file=sys.stderr)
    if len(findings) > 40:
        print(f"  … and {len(findings) - 40} more", file=sys.stderr)
    print("      Fix: reword the message to the generic term "
          "(\"commercial PDK\" / \"commercial foundry\"), then "
          "`git commit --amend` (or rebase-reword for an older commit).",
          file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="NDA guard for commit MESSAGE text — FAILs when a commit "
                    "message names the commercial foundry / SKU / process.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--message-file",
                      help="path to a commit message file (git commit-msg hook)")
    mode.add_argument("--rev-range",
                      help="git revision range whose commit messages to scan, "
                           "e.g. origin/main..HEAD")
    mode.add_argument("--stdin", action="store_true",
                      help="read one message from stdin")
    ap.add_argument("--repo", default=None,
                    help="repo root for --rev-range (default: cwd)")
    ap.add_argument("--json", help="write a MASKED JSON report to this path")
    args = ap.parse_args(argv)

    scanned = 0
    try:
        if args.message_file:
            p = Path(args.message_file)
            if not p.is_file():
                print(f"error: no such message file: {p}", file=sys.stderr)
                return 2
            findings = scan_message(p.read_text(encoding="utf-8",
                                                errors="replace"),
                                    source=f"message-file:{p.name}")
            scanned = 1
        elif args.stdin:
            findings = scan_message(sys.stdin.read(), source="stdin")
            scanned = 1
        else:
            repo = Path(args.repo).resolve() if args.repo else Path.cwd()
            findings, scanned = scan_rev_range(repo, args.rev_range)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "gate": GATE_NAME,
            "verdict": "FAIL" if findings else "PASS",
            "messages_scanned": scanned,
            "findings_count": len(findings),
            # asdict() carries ONLY masked context — never a literal token.
            "findings": [asdict(f) for f in findings[:200]],
        }, indent=2) + "\n")

    if findings:
        _print_findings(findings, scanned)
        return 1
    if scanned == 0:
        # An EMPTY range is not a clean range (vibe-ic#447/#449). Measured
        # before wiring this into CI: `HEAD..HEAD` returned rc 0 PASS having
        # read zero commit messages, byte-indistinguishable from a real clean
        # scan of 33. A malformed or already-merged range would have silenced
        # the guard this repo added after a real SKU leak.
        #
        # The other bad ranges already refuse: an all-zero SHA (force-push /
        # first push of a branch) and an unknown ref both exit 2.
        print("NOTHING_SCANNED: the range names 0 commit(s) — a clean result "
              "over an empty range is not a clean result; check the range.",
              file=sys.stderr)
        return 2
    print(f"PASS: no NDA foundry / SKU / process token in {scanned} "
          f"commit message(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
