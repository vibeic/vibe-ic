#!/usr/bin/env python3
"""nda_diff_scan_check.py — NDA guard for a PR's DIFF CONTENT (added lines +
added/renamed file PATHS), across the WHOLE change-set.

WHY THIS EXISTS
---------------
Two NDA surfaces were already guarded:
  * `source_chip_agnostic_check.py` scans the plugin SOURCE TREE
    (`programs/ skills/ commands/`) — but ONLY the plugin tree, so a leak in a
    repo-ROOT config file (`.image-version-ignore`), a doc, a template, or any
    path outside that tree sails straight through.
  * `commit_msg_nda_check.py` scans commit MESSAGES — not file content.

A landed PR (#247) proved the gap from BOTH sides: it added a commercial-PDK
SKU + an IP-vendor part number inside a TEST FIXTURE's content AND inside a
FIXTURE FILENAME (`<part>_M3.lef`), and named them in the commit body. The
message guard caught the body; nothing caught the fixture content or the
filename. This gate closes that: it scans the exact CONTENT a PR adds — every
`+` line and every added/renamed file PATH in `base..head` — regardless of
where in the repo the file lives.

It is the DIFF-scoped complement to the two existing guards, and it shares the
SAME encoded token store (`_commercial_pdk`), so the three can never drift.

DESIGN CONSTRAINTS (identical to the message guard)
---------------------------------------------------
  * NO LITERAL TOKEN IN THIS FILE. Tokens are reconstructed at runtime from
    `_commercial_pdk`'s base64 store — a detector that spelled out the SKU would
    itself be the leak `git grep` finds.
  * MASKED REPORTING. A finding prints the token's ROLE (`<NDA-TOKEN:role>`)
    plus surrounding words, never the literal token — safe in a CI log / PR
    comment.
  * CHIP-AGNOSTIC / DETERMINISTIC. Pure regex over diff text; no chip names, no
    network, same verdict on every host. Reads only the diff (design/change
    INPUT) — never an oracle or golden.

MODES
-----
  --rev-range <A..B>   diff `git diff A..B` of a repo   (gatekeeper / pre-push)
  --diff-file <path>   scan a raw unified diff file       (ad-hoc / CI artifact)
  --stdin              scan a unified diff on stdin        (piping)

EXIT CODES
----------
  0  PASS  — no NDA token in any added line or added path
  1  FAIL  — at least one NDA token found (the leak is blocked)
  2  ERROR — bad usage / unreadable input / git failure (fail LOUD, never silent)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _commercial_pdk as _cpdk  # noqa: E402

GATE_NAME = "nda_diff_scan_check"

# Characters of context kept either side of a hit — enough to be actionable
# without quoting a whole line.
_CONTEXT_CHARS = 32


@dataclass
class DiffFinding:
    """One NDA hit in a diff. `masked_context` never contains the literal
    token, so this record is safe to write to a tracked artifact."""
    kind: str            # "added-line" | "added-path"
    path: str            # file the hit is in / the offending path itself
    role: str            # NDA token role, e.g. "sku_full" / "ip_vendor"
    masked_context: str  # surrounding text with the token masked out


def _mask(text: str, start: int, end: int, role: str) -> str:
    """Neighbourhood of a hit with EVERY literal token in it replaced by
    `<NDA-TOKEN:role>`. Never returns a token itself.

    Masked ONLY the reported hit until 2026-08-29, so an added line carrying two
    different tokens echoed each one in the other's finding. See
    `_commercial_pdk.nda_mask_neighbourhood` for the measurement."""
    return _cpdk.nda_mask_neighbourhood(text, start, end, role, _CONTEXT_CHARS)


def _scan_text(text: str) -> List[Tuple[str, int, int]]:
    """Return [(role, start, end)] for every NDA token in `text`."""
    rx = _cpdk.nda_content_regex()
    out: List[Tuple[str, int, int]] = []
    for m in rx.finditer(text):
        out.append((_cpdk.nda_role_of(m.group(1)), m.start(1), m.end(1)))
    return out


def scan_unified_diff(diff: str) -> List[DiffFinding]:
    """Scan a unified diff. Flags a token in either:
      * an ADDED content line (`+…`, but never the `+++ ` file header), or
      * an added / renamed / current file PATH (`+++ b/<path>`,
        `rename to <path>`, `copy to <path>`) — a leak can be the FILENAME.

    Removed lines (`-…`) and context lines are ignored: this gate is about what
    a PR ADDS to the landed tree, not what it deletes (deleting a leak is the
    fix, and a scrub commit's removed `-` lines legitimately still show the
    token)."""
    findings: List[DiffFinding] = []
    cur_path = "(unknown)"
    for raw in diff.splitlines():
        # File-path carriers. `+++ b/<path>` names the post-image path; the
        # rename/copy headers name a new path even when no content line changes.
        if raw.startswith("+++ "):
            p = raw[4:].strip()
            if p.startswith("b/"):
                p = p[2:]
            cur_path = p if p and p != "/dev/null" else cur_path
            for role, s, e in _scan_text(cur_path):
                findings.append(DiffFinding("added-path", cur_path, role,
                                            _mask(cur_path, s, e, role)))
            continue
        if raw.startswith(("rename to ", "copy to ")):
            p = raw.split(" to ", 1)[1].strip()
            for role, s, e in _scan_text(p):
                findings.append(DiffFinding("added-path", p, role,
                                            _mask(p, s, e, role)))
            continue
        if raw.startswith("--- ") or raw.startswith("+++"):
            continue
        # Added content line (exactly one leading '+', not the '+++' header).
        if raw.startswith("+") and not raw.startswith("+++"):
            content = raw[1:]
            for role, s, e in _scan_text(content):
                findings.append(DiffFinding("added-line", cur_path, role,
                                            _mask(content, s, e, role)))
    return findings


# ---------------------------------------------------------------------------
# Git access for --rev-range.
# ---------------------------------------------------------------------------
#: Bound every git call. vibe-ic#640: `git diff <sha> --not --remotes` does not
#: REJECT the rev-list selectors — it BLOCKS, reading stdin, with zero output and
#: empty stderr. Unbounded, the scan simply never returned; the caller's own
#: timeout then surfaced as a non-zero exit that `run_gate` rendered as a
#: positive NDA finding. 55 s stays under the 60 s inner ceiling this repo
#: enforces, and a real `git diff` over a branch runs in well under a second.
_GIT_TIMEOUT_S = 55


def _git(repo: Path, *args: str) -> Tuple[int, str, str]:
    try:
        # errors="replace" (vibe-ic#640 follow-on). `text=True` decodes git's
        # stdout as strict UTF-8, and a diff that touches a non-UTF-8 file —
        # `status.sqlite`, `design_aiger.aig`, any binary artefact an evidence
        # landing routinely carries — raises UnicodeDecodeError inside
        # `subprocess`. The traceback exits 1, and `run_gate` reads exit 1 as a
        # POSITIVE NDA FINDING: the same "a failed question wearing a finding's
        # clothes" shape as the rev-list range, by a different route, on the one
        # gate this repo cannot afford to get wrong.
        #
        # MEASURED on PR #645 (352 files, an IC evidence cell):
        #   before  UnicodeDecodeError at byte 0x96, rc 1 -> reported as a leak
        #   after   the scan runs and answers
        #
        # A replaced byte cannot manufacture a token: U+FFFD appears in no
        # pattern, so substitution can only ever remove a match, never add one —
        # and the bytes it replaces are, by construction, not text a token could
        # be spelled in.
        proc = subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True,
                              errors="replace",
                              timeout=_GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        # An honest error, never a finding and never a clean scan.
        return 124, "", (f"git {' '.join(args)[:120]} did not return within "
                         f"{_GIT_TIMEOUT_S}s")
    return proc.returncode, proc.stdout, proc.stderr


#: Selectors `git rev-list`/`git log` accept and `git diff` does not. A range
#: carrying one of these is a COMMIT-SET expression, not a diff endpoint pair.
_REVLIST_ONLY = ("--not", "--remotes", "--branches", "--tags", "--all",
                 "--glob", "--exclude")


def resolve_diffable_range(repo: Path, rev_range: str) -> List[str]:
    """The `git diff` arguments that cover what `rev_range` selects.

    vibe-ic#640. `pre-push` builds a NEW branch's range as a rev-list
    expression — `<sha> --not --remotes`, "commits not already on a remote" —
    and handed it straight to `git diff`, which blocks on it. So on every
    new-branch push this gate scanned NOTHING, and the hang was reported as an
    NDA violation: the worst combination, because it both cried wolf and left
    the rule it protects unenforced.

    A commit-set expression is resolved with the tool that understands it:
    `git rev-list` gives the commits, oldest-last, and the diff that covers them
    is `<oldest>^..<newest>`. A root commit has no parent, so the empty tree is
    used as the base rather than refusing — a first-ever commit is exactly when
    an added path most needs scanning.

    Ranges git diff already understands are returned untouched.
    """
    parts = rev_range.split()
    if not any(p in _REVLIST_ONLY or p.startswith("--glob=")
               or p.startswith("--exclude=") for p in parts):
        return parts
    rc, out, err = _git(repo, "rev-list", *parts)
    if rc != 0:
        raise RuntimeError(f"git rev-list {rev_range!r} failed: {err.strip()[:300]}")
    commits = out.split()
    if not commits:
        # Not a clean scan — an empty commit set means the range selected
        # nothing, which `main` already treats as rc 2.
        raise RuntimeError(f"rev-range {rev_range!r} selects no commit")
    newest, oldest = commits[0], commits[-1]
    rc, _o, _e = _git(repo, "rev-parse", "--verify", f"{oldest}^")
    if rc == 0:
        return [f"{oldest}^..{newest}"]
    # Root commit: diff against the empty tree so the whole first commit is seen.
    rc, empty, _e = _git(repo, "hash-object", "-t", "tree", "/dev/null")
    if rc != 0:
        raise RuntimeError("cannot resolve the empty tree for a root commit")
    return [empty.strip(), newest]


def diff_for_range(repo: Path, rev_range: str) -> str:
    """`git diff <range>` unified text. Raises RuntimeError on git failure — an
    unwalkable range must FAIL LOUD, never be reported as a clean scan (a
    silently-empty scan is exactly how a guard becomes decorative)."""
    parts = rev_range.split()
    if not parts:
        raise RuntimeError("empty --rev-range")
    parts = resolve_diffable_range(repo, rev_range)
    # --no-color / -U0-ish not needed; default unified is fine. Include renames
    # so a renamed-in leaked filename is visible as `rename to <path>`.
    rc, out, err = _git(repo, "diff", "--find-renames", *parts)
    if rc != 0:
        raise RuntimeError(f"git diff {rev_range!r} failed: {err.strip()[:300]}")
    return out


# ---------------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------------
def _print_findings(findings: List[DiffFinding]) -> None:
    print(f"FAIL: {len(findings)} NDA token occurrence(s) in the diff "
          f"(added content / added paths)", file=sys.stderr)
    print("      A landed diff is permanent public content — the foundry / SKU "
          "/ process / IP-vendor name must not appear in it.", file=sys.stderr)
    for f in findings[:40]:
        print(f"  {f.kind} {f.path}  role={f.role}\n      {f.masked_context}",
              file=sys.stderr)
    if len(findings) > 40:
        print(f"  … and {len(findings) - 40} more", file=sys.stderr)
    print("      Fix: reword to the generic term (\"commercial PDK\" / "
          "\"commercial foundry\" / \"a commercial OTP vendor\") and rename any "
          "offending file, then re-commit.", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="NDA guard for a PR's DIFF content — FAILs when an added "
                    "line or an added/renamed path names the commercial "
                    "foundry / SKU / process / IP vendor.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rev-range",
                      help="git revision range to diff, e.g. origin/main..HEAD")
    mode.add_argument("--diff-file", help="path to a raw unified-diff file")
    mode.add_argument("--stdin", action="store_true",
                      help="read a unified diff from stdin")
    ap.add_argument("--repo", default=None,
                    help="repo root for --rev-range (default: cwd)")
    ap.add_argument("--json", help="write a MASKED JSON report to this path")
    args = ap.parse_args(argv)

    try:
        if args.rev_range:
            repo = Path(args.repo).resolve() if args.repo else Path.cwd()
            diff = diff_for_range(repo, args.rev_range)
        elif args.diff_file:
            p = Path(args.diff_file)
            if not p.is_file():
                print(f"error: no such diff file: {p}", file=sys.stderr)
                return 2
            diff = p.read_text(encoding="utf-8", errors="replace")
        else:
            diff = sys.stdin.read()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        findings = scan_unified_diff(diff)
    except _cpdk.NoNdaLiterals as exc:
        # THE `except RuntimeError -> return 2` ABOVE DOES NOT COVER THIS. It
        # guards the diff ACQUISITION; the token store is not consulted until
        # `scan_unified_diff`, one statement outside that block. MEASURED
        # 2026-08-29 with the store emptied: `NoNdaLiterals` escaped as an
        # uncaught traceback and the process exited 1 — and rc 1 on this gate
        # is a MEASURED REFUSE, so `build_push_preflight_receipt` recorded
        # verdict=REFUSE with a Python traceback as the finding's summary line.
        # A failed question wearing a finding's clothes: the same shape as
        # vibe-ic#640 (rev-list blocking) and #645 (UnicodeDecodeError), by a
        # third route. rc 2 is the honest channel — NORECORD, not REFUSE.
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "gate": GATE_NAME,
            "verdict": "FAIL" if findings else "PASS",
            "findings_count": len(findings),
            # asdict() carries ONLY masked context — never a literal token.
            "findings": [asdict(f) for f in findings[:200]],
        }, indent=2) + "\n")

    if findings:
        _print_findings(findings)
        return 1
    if args.rev_range and not diff.strip():
        # An EMPTY diff is not a clean diff (vibe-ic#447/#449). Measured before
        # wiring this into CI: `HEAD..HEAD` returned rc 0 PASS having scanned
        # nothing, byte-indistinguishable from a real clean scan of a 33-commit
        # range. A malformed or already-merged range would have silenced the
        # guard this repo added after a real SKU leak.
        #
        # Scoped to `--rev-range` on purpose: `--diff-file` / `--stdin` with an
        # empty input is a caller who genuinely has no diff, and refusing there
        # would fire on legitimate use.
        print(f"NOTHING_SCANNED: the range {args.rev_range!r} produces an "
              f"EMPTY diff — a clean result over an empty scan is not a clean "
              f"result; check the range.", file=sys.stderr)
        return 2
    print("PASS: no NDA foundry / SKU / process / IP-vendor token in the "
          "diff's added content or paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
