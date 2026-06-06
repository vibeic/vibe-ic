#!/usr/bin/env python3
"""programs/acceptance_evidence_in_fix_comment_check.py — v0.2.97

Deterministic pre-close gate for the core-agent loop (issue #478, Bucket A
half 1).

WHY THIS EXISTS
---------------
`skills/core-agent-loop/compliance.yaml` rule R5 only pattern-matches that
a fix comment CONTAINS a "**本機驗證**：" section header. It does NOT verify
that the section actually ran the issue's own end-to-end "## 驗收"
(acceptance) commands. That gap is the shared root cause of the #460/#466
reopens: those fix comments' 本機驗證 only reported the NEW code's
intermediate products (new tests N/N green, full suite green) but never
executed the issue's own acceptance commands — and the field agent flipped
the moment it ran them.

This program closes that gap deterministically. It parses the issue body for
a "## 驗收" / acceptance section, extracts its concrete command/criterion
lines, and asserts that the fix comment's 本機驗證 section both (a) quotes
those commands verbatim (whitespace-normalised, near-verbatim allowed) AND
(b) carries end-state output evidence near them. Missing → exit 1 with a
list of exactly what is missing; the core agent must NOT close the issue
until it re-runs the acceptance commands and pastes the end state.

Issues that have NO acceptance section are vacuous — there is nothing to
replay — so the gate exits 0 with a SKIP note.

This program is chip-AGNOSTIC: it parses prose/markdown structure only and
contains no chip / vendor / SKU literals in its detection logic.

INTERFACES
----------
Two mutually-exclusive input modes, mirroring the CLI style of
`regression_issue_intake_check.py`:

  1. Network mode (used by the live loop):
       --issue-number N [--repo OWNER/REPO] [--token-file PATH]
       --comment-file PATH        # the candidate fix-comment body
     The issue body is fetched from the GitHub REST API; the comment body
     is read from the local file the core agent is about to post.

  2. Offline mode (used by tests + air-gapped pre-close gating; no network):
       --issue-body-file PATH --comment-file PATH

DETECTION RULES (documented so they are auditable)
--------------------------------------------------
* Acceptance section: the first markdown heading whose text matches
  `## 驗收` or contains the word "acceptance" (case-insensitive), up to the
  next same-or-higher-level heading or EOF.
* Command/criterion lines extracted from that section:
    - lines inside fenced code blocks (```...```), one command per line;
    - inline-code spans (`...`) that look like a shell command
      (contain a space or a path separator or a known runner verb);
    - bullet lines beginning with `- ` / `* ` whose text carries an
      inline-code span or a recognisable command token — kept as a
      *criterion* the comment must address.
  A "command token" is heuristic and chip-AGNOSTIC: any of python /
  python3 / pytest / make / bash / sh / gh / git / a `*.py`/`*.sh` path /
  a `./` or `programs/` relative path / an `--flag`.
* Quoting test: each extracted COMMAND must appear in the fix comment's
  本機驗證 section, compared after whitespace normalisation (collapse runs
  of whitespace, strip). Near-verbatim is allowed: a command counts as
  quoted if its normalised form is a substring of the normalised comment
  section, OR if a high token-overlap (>= 0.85 of the command's
  non-trivial tokens) line exists in the section.
* End-state evidence test: the 本機驗證 section must additionally carry
  output evidence — at least one line that is NOT itself one of the
  acceptance commands and that looks like a result/verdict line
  (PASS/FAIL/exit/rc/=>/N/N/Step .. = .. / a fenced output block / etc.).
  Quoting a command but pasting no result is the exact #460/#466 failure
  mode, so this is required.

EXIT CODES
----------
  0  PASS  — no acceptance section (SKIP), or all acceptance commands are
            quoted AND end-state evidence is present.
  1  FAIL  — acceptance section present but the comment does not quote every
            command, or has no end-state evidence near them.
  2  usage / I/O error (bad args, missing file, no token, empty body).

OPTIONAL OUTPUT
---------------
  --json PATH   write a machine-readable verdict report.

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# --------------------------------------------------------------------------
# GitHub fetch (network mode only) — mirrors regression_issue_intake_check.
# --------------------------------------------------------------------------
def _read_token(token_file: Optional[str]) -> str:
    """Read a GitHub PAT from --token-file, $GITHUB_TOKEN, or
    ~/.config/github/token (in that order)."""
    if token_file:
        p = Path(os.path.expanduser(token_file))
        if p.is_file():
            return p.read_text().strip()
    env = os.environ.get("GITHUB_TOKEN")
    if env:
        return env.strip()
    default = Path("~/.config/github/token").expanduser()
    if default.is_file():
        return default.read_text().strip()
    raise RuntimeError(
        "no GitHub token found (tried --token-file, $GITHUB_TOKEN, "
        "~/.config/github/token)"
    )


def _fetch_issue_body(repo: str, issue_number: int, token: str) -> str:
    """Return the body string for a GitHub issue."""
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        d = json.loads(r.read())
    return d.get("body") or ""


# --------------------------------------------------------------------------
# Acceptance-section extraction
# --------------------------------------------------------------------------
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
# Acceptance heading: literal "驗收", or the English word "acceptance"
# anywhere in the heading text. chip-AGNOSTIC structural cue only.
_ACCEPTANCE_HEADING_TOKEN_RE = re.compile(r"驗收|acceptance", re.IGNORECASE)

# Heuristic command tokens (chip-AGNOSTIC: tool/runner verbs + path shapes).
_RUNNER_VERBS = (
    "python3", "python", "pytest", "make", "bash", "sh", "gh", "git",
)
_CMD_HINT_RE = re.compile(
    r"(?:^|\s)(?:" + "|".join(re.escape(v) for v in _RUNNER_VERBS) + r")\b"
    r"|(?:\./|programs/|tools/|scripts/)"
    r"|\.(?:py|sh)\b"
    r"|(?:^|\s)--[A-Za-z][\w-]*",
)


def extract_acceptance_section(body: str) -> Optional[str]:
    """Return the text of the first acceptance section, or None.

    The section spans from an acceptance heading to the next heading of
    the same or higher level (smaller or equal '#' count), or EOF.
    """
    headings = list(_HEADING_RE.finditer(body))
    for i, m in enumerate(headings):
        level = len(m.group(1))
        title = m.group(2)
        if not _ACCEPTANCE_HEADING_TOKEN_RE.search(title):
            continue
        start = m.end()
        end = len(body)
        for j in range(i + 1, len(headings)):
            nxt = headings[j]
            if len(nxt.group(1)) <= level:
                end = nxt.start()
                break
        return body[start:end].strip()
    return None


def _looks_like_command(text: str) -> bool:
    return bool(_CMD_HINT_RE.search(text))


def extract_commands(section: str) -> Tuple[List[str], List[str]]:
    """From an acceptance section, return (commands, criteria).

    commands  — concrete shell/runner invocations that the fix comment
                MUST quote verbatim (fenced-code lines + command-shaped
                inline-code spans).
    criteria  — softer bullet criteria carrying an inline-code token; the
                comment should address them but they are reported
                separately (advisory).
    """
    commands: List[str] = []
    criteria: List[str] = []

    # 1. Fenced code blocks → every non-blank line is a command.
    fence_re = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.DOTALL)
    fenced_spans: List[Tuple[int, int]] = []
    for fm in fence_re.finditer(section):
        fenced_spans.append((fm.start(), fm.end()))
        block = fm.group(1)
        for ln in block.splitlines():
            s = ln.strip()
            if not s:
                continue
            # Drop a leading shell prompt marker if present.
            s = re.sub(r"^\$\s+", "", s)
            if s:
                commands.append(s)

    def _in_fence(pos: int) -> bool:
        return any(a <= pos < b for a, b in fenced_spans)

    # 2. Inline-code spans outside fences that look like commands.
    inline_re = re.compile(r"`([^`\n]+)`")
    for im in inline_re.finditer(section):
        if _in_fence(im.start()):
            continue
        span = im.group(1).strip()
        if span and _looks_like_command(span):
            commands.append(span)

    # 3. Bullet criteria carrying any inline-code or command token.
    for ln in section.splitlines():
        s = ln.strip()
        if not (s.startswith("- ") or s.startswith("* ")):
            continue
        body_txt = s[2:].strip()
        # Already captured the inline-code commands above; record the
        # bullet itself as a criterion for transparency.
        if "`" in body_txt or _looks_like_command(body_txt):
            criteria.append(body_txt)

    # De-duplicate while preserving order.
    commands = _dedup(commands)
    criteria = _dedup(criteria)
    return commands, criteria


def _dedup(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for it in items:
        key = _norm_ws(it)
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


# --------------------------------------------------------------------------
# 本機驗證 section extraction from the fix comment
# --------------------------------------------------------------------------
# The comment uses a bold marker "**本機驗證**：" per compliance.yaml R5,
# and may optionally use an English "Local verification" header. Capture
# from that marker to the next bold-marker section "**X**：" or EOF.
_LOCAL_VERIF_MARKERS = (
    "**本機驗證**",
    "本機驗證：",
    "Local verification",
    "Local Verification",
)
_BOLD_SECTION_RE = re.compile(r"^\s*\*\*[^*\n]+\*\*[：:]", re.MULTILINE)


def extract_local_verification(comment: str) -> Optional[str]:
    """Return the text of the 本機驗證 section of the fix comment, or None.

    Falls back to the entire comment body when no explicit marker is
    found AND the comment is short — but the canonical loop always emits
    the marker, so the primary path keys on it.
    """
    idx = -1
    marker_len = 0
    for mk in _LOCAL_VERIF_MARKERS:
        pos = comment.find(mk)
        if pos != -1 and (idx == -1 or pos < idx):
            idx = pos
            marker_len = len(mk)
    if idx == -1:
        return None
    start = idx + marker_len
    # Find the next bold section marker AFTER this one.
    end = len(comment)
    for bm in _BOLD_SECTION_RE.finditer(comment, start):
        end = bm.start()
        break
    return comment[start:end].strip()


# --------------------------------------------------------------------------
# Quoting + end-state-evidence matching
# --------------------------------------------------------------------------
def _norm_ws(s: str) -> str:
    """Collapse all whitespace runs to single spaces and strip."""
    return re.sub(r"\s+", " ", s).strip()


_TOKEN_SPLIT_RE = re.compile(r"\s+")
_TRIVIAL_TOKENS = {"&&", "||", "|", ";", "cd", "&"}


def _significant_tokens(cmd: str) -> List[str]:
    toks = [t for t in _TOKEN_SPLIT_RE.split(cmd.strip()) if t]
    return [t for t in toks if t not in _TRIVIAL_TOKENS]


def _command_is_quoted(cmd: str, section_norm: str,
                       section_lines_norm: List[str]) -> bool:
    """True if cmd is quoted verbatim or near-verbatim in the section."""
    cmd_norm = _norm_ws(cmd)
    if not cmd_norm:
        return True
    # Verbatim (whitespace-normalised) substring match.
    if cmd_norm in section_norm:
        return True
    # Near-verbatim: high token overlap with some line in the section.
    cmd_tokens = _significant_tokens(cmd_norm)
    if not cmd_tokens:
        # All-trivial command (e.g. just "cd x"): require exact-ish.
        return cmd_norm in section_norm
    cmd_set = set(cmd_tokens)
    for ln in section_lines_norm:
        ln_set = set(_significant_tokens(ln))
        if not ln_set:
            continue
        overlap = len(cmd_set & ln_set) / len(cmd_set)
        if overlap >= 0.85:
            return True
    return False


# An end-state / verdict / output-evidence line. chip-AGNOSTIC structural
# cues only: pass/fail verdicts, exit/return codes, N/N counts, arrows,
# "Step .. = ..", or a fenced output block.
_EVIDENCE_RE = re.compile(
    r"\bPASS\b|\bFAIL\b|\bOK\b|\berror\b"
    r"|exit\s*(?:code)?\s*[:=]?\s*\d"
    r"|\brc\s*[:=]\s*-?\d"
    r"|return\s*code"
    r"|\d+\s*/\s*\d+"               # N/N
    r"|=>|->|→"
    r"|Step\s+\d+\s*=|\bStep\b.*=\s*\w"
    r"|passed|failed|all green|綠|通過|端態|端到端"
    r"|\bSKIP\b|VACUOUS",
    re.IGNORECASE,
)


def _has_end_state_evidence(section: str, commands: List[str]) -> bool:
    """True if the section has at least one output/verdict line that is
    not itself one of the acceptance commands."""
    cmd_norms = {_norm_ws(c) for c in commands}
    has_fence_output = False
    fence_re = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.DOTALL)
    for fm in fence_re.finditer(section):
        for ln in fm.group(1).splitlines():
            s = _norm_ws(ln)
            if not s:
                continue
            if s in cmd_norms:
                continue
            # Any non-command line inside a fenced block is treated as
            # captured output evidence.
            has_fence_output = True
            if _EVIDENCE_RE.search(ln):
                return True
    for ln in section.splitlines():
        s = _norm_ws(ln)
        if not s or s in cmd_norms:
            continue
        if _EVIDENCE_RE.search(ln):
            return True
    return has_fence_output


# --------------------------------------------------------------------------
# Core verdict
# --------------------------------------------------------------------------
@dataclass
class Verdict:
    verdict: str                       # PASS | FAIL | SKIP
    has_acceptance: bool
    commands: List[str] = field(default_factory=list)
    criteria: List[str] = field(default_factory=list)
    unquoted_commands: List[str] = field(default_factory=list)
    end_state_evidence: bool = False
    notes: List[str] = field(default_factory=list)


def evaluate(issue_body: str, comment_body: str) -> Verdict:
    section = extract_acceptance_section(issue_body)
    if section is None:
        return Verdict(
            verdict="SKIP",
            has_acceptance=False,
            notes=["issue has no '## 驗收'/acceptance section — "
                   "nothing to replay (vacuous PASS)"],
        )

    commands, criteria = extract_commands(section)
    if not commands:
        # Acceptance section exists but carries no concrete command —
        # treat as SKIP (cannot deterministically demand a quote) but
        # record the criteria for transparency.
        return Verdict(
            verdict="SKIP",
            has_acceptance=True,
            criteria=criteria,
            notes=["acceptance section present but no concrete command "
                   "lines extractable — only narrative criteria; "
                   "deterministic command-quote check is vacuous"],
        )

    local = extract_local_verification(comment_body)
    if local is None:
        return Verdict(
            verdict="FAIL",
            has_acceptance=True,
            commands=commands,
            criteria=criteria,
            unquoted_commands=list(commands),
            end_state_evidence=False,
            notes=["fix comment has no '**本機驗證**：' section — "
                   "R5 would already flag this; acceptance commands "
                   "cannot be verified as run"],
        )

    section_norm = _norm_ws(local)
    section_lines_norm = [_norm_ws(ln) for ln in local.splitlines()
                          if ln.strip()]
    unquoted = [c for c in commands
                if not _command_is_quoted(c, section_norm,
                                          section_lines_norm)]
    has_evidence = _has_end_state_evidence(local, commands)

    notes: List[str] = []
    if unquoted:
        notes.append(
            f"{len(unquoted)} acceptance command(s) not quoted in 本機驗證")
    if not has_evidence:
        notes.append(
            "本機驗證 quotes commands but carries no end-state output "
            "evidence near them (the #460/#466 failure mode)")

    verdict = "PASS" if (not unquoted and has_evidence) else "FAIL"
    return Verdict(
        verdict=verdict,
        has_acceptance=True,
        commands=commands,
        criteria=criteria,
        unquoted_commands=unquoted,
        end_state_evidence=has_evidence,
        notes=notes,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _load_inputs(args: argparse.Namespace) -> Tuple[str, str]:
    """Return (issue_body, comment_body). Raises on usage / I/O error."""
    # Comment file is mandatory in both modes.
    if not args.comment_file:
        raise ValueError("--comment-file is required")
    cpath = Path(args.comment_file)
    if not cpath.is_file():
        raise FileNotFoundError(f"--comment-file not found: {cpath}")
    comment_body = cpath.read_text(encoding="utf-8")

    if args.issue_body_file:
        # Offline mode.
        ipath = Path(args.issue_body_file)
        if not ipath.is_file():
            raise FileNotFoundError(
                f"--issue-body-file not found: {ipath}")
        issue_body = ipath.read_text(encoding="utf-8")
        if not issue_body.strip():
            raise ValueError("--issue-body-file is empty")
        return issue_body, comment_body

    if args.issue_number is not None:
        # Network mode.
        token = _read_token(args.token_file)
        issue_body = _fetch_issue_body(args.repo, args.issue_number, token)
        if not issue_body.strip():
            raise ValueError(
                f"issue #{args.issue_number} has an empty body")
        return issue_body, comment_body

    raise ValueError(
        "provide either --issue-body-file (offline) or --issue-number "
        "(network) — neither was given")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Refuse a core-agent fix comment that does not "
                    "quote AND show end-state output for the issue's "
                    "own ## 驗收 acceptance commands.")
    # Network mode args (mirror regression_issue_intake_check.py).
    ap.add_argument("--issue-number", type=int, default=None)
    ap.add_argument("--repo", default="reyerchu/AI_IC_design")
    ap.add_argument("--token-file", default=None)
    # Offline mode arg.
    ap.add_argument("--issue-body-file", default=None)
    # Common.
    ap.add_argument("--comment-file", default=None,
                    help="the candidate fix-comment body")
    ap.add_argument("--json", default=None,
                    help="write a JSON verdict report to this path")
    args = ap.parse_args(argv)

    try:
        issue_body, comment_body = _load_inputs(args)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    v = evaluate(issue_body, comment_body)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(asdict(v), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")

    if v.verdict == "SKIP":
        print("SKIP (PASS): " + "; ".join(v.notes))
        return 0

    if v.verdict == "PASS":
        print("PASS: 本機驗證 quotes all "
              f"{len(v.commands)} acceptance command(s) and carries "
              "end-state output evidence.")
        return 0

    # FAIL
    print("FAIL: fix comment does not satisfy the acceptance-execution "
          "doctrine.", file=sys.stderr)
    if v.unquoted_commands:
        print("  Acceptance commands NOT quoted in 本機驗證:",
              file=sys.stderr)
        for c in v.unquoted_commands:
            print(f"    - {c}", file=sys.stderr)
    if not v.end_state_evidence:
        print("  No end-state output evidence found near the commands "
              "(quoting a command but pasting no result is the "
              "#460/#466 failure mode).", file=sys.stderr)
    for n in v.notes:
        print(f"  note: {n}", file=sys.stderr)
    print("\n  Re-run the issue's ## 驗收 commands end-to-end and paste "
          "their end-state output into 本機驗證 before closing.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
