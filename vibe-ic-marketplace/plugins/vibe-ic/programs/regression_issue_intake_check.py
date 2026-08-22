#!/usr/bin/env python3
"""programs/regression_issue_intake_check.py — v1.6.63

Issue-#5 lesson-learned enforcement: before a debug agent attempts a
fix on a Phase 1 regression issue, this program verifies the issue
body carries every mandatory field — verbatim input snippet, expected
output, actual output, plugin version observed — AND auto-emits the
drop-in fixture under `tests/phase1_fixtures/<project>/`.

Mandatory fields (parsed from the GitHub issue body produced by
`.github/ISSUE_TEMPLATE/picker-or-extractor-regression.yml`):

  * Project name
  * Affected layer
  * Specific JSON field
  * Verbatim input snippet (≥4 lines, fenced)
  * Filename of the snippet
  * Expected output
  * Actual output
  * Plugin version where the bug was observed

Issues missing any of these fields exit 1 with a list of what's
missing — the debug agent must NOT start the fix until the verifier
agent posts a follow-up comment that fills the gaps.

Issues that pass the check get a fixture file written to
`tests/phase1_fixtures/<project>/<filename>` AND a one-line append
to `tests/phase1_fixtures/_pending.json` carrying
`{project, layer, field, expected, actual, version, issue_number}`.
The debug agent's first action is then `pytest -k <project>` to
confirm the fixture FAILS on current code.

Usage:
  python3 regression_issue_intake_check.py \\
      --issue-number 5 \\
      [--repo vibeic/vibe-ic] \\
      [--token-file ~/.config/github/token] \\
      [--repo-root <path>] \\
      [--no-emit-fixture]   # validate only, don't write files
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Mapping from issue-template label → key used in the parsed dict.
# Keep aligned with `.github/ISSUE_TEMPLATE/picker-or-extractor-regression.yml`
_FIELD_LABELS: Dict[str, str] = {
    "Project name": "project",
    "Affected layer": "layer",
    "Specific JSON field": "field_path",
    "Verbatim input snippet (MANDATORY)": "input_snippet",
    "Filename of the snippet": "input_filename",
    "Expected output (MANDATORY)": "expected",
    "Actual output (MANDATORY)": "actual",
    "Plugin version where the bug was observed": "version_observed",
    "Last-known-good version (optional)": "version_lkg",
    "Failure-mode hypothesis (optional)": "hypothesis",
    "Drop-in fixture (optional but strongly recommended)": "drop_in",
    "Other failures observed in the same benchmark run (optional)":
        "other_failures",
}

# Mandatory field keys (subset — the rest are optional).
_MANDATORY_KEYS = (
    "project", "layer", "field_path",
    "input_snippet", "input_filename",
    "expected", "actual", "version_observed",
)


def _fetch_issue_body(repo: str, issue_number: int,
                      token: str) -> Tuple[str, dict]:
    """Return (body, full-issue-json) for a GitHub issue."""
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    return d.get("body") or "", d


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


# GitHub form-issue bodies use H3 headers ("### <Label>") followed by
# the response value. Parse heuristically.
_H3_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)


def _parse_form_issue(body: str) -> Dict[str, str]:
    """Walk H3 headers and capture the text up to the next H3 (or EOF)
    as the value for that label."""
    parsed: Dict[str, str] = {}
    matches = list(_H3_RE.finditer(body))
    for i, m in enumerate(matches):
        label = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        raw = body[start:end].strip()
        # Drop the "_No response_" / "_No response_." sentinel.
        if raw.lower().rstrip(".") == "_no response_":
            raw = ""
        # Strip enclosing fenced-code markers if present (for
        # snippet fields).
        m_fence = re.match(
            r"^```[a-zA-Z]*\n(.*?)\n```\s*$", raw, re.DOTALL,
        )
        if m_fence:
            raw = m_fence.group(1)
        for human, key in _FIELD_LABELS.items():
            if label == human or label.startswith(human.split(" (")[0]):
                parsed[key] = raw
                break
    return parsed


def _validate(parsed: Dict[str, str]) -> List[str]:
    missing: List[str] = []
    for k in _MANDATORY_KEYS:
        v = parsed.get(k, "").strip()
        if not v:
            missing.append(k)
            continue
        # Verbatim-snippet sanity: ≥4 non-empty lines.
        if k == "input_snippet":
            non_empty = [ln for ln in v.splitlines() if ln.strip()]
            if len(non_empty) < 4:
                missing.append(
                    f"input_snippet (only {len(non_empty)} non-empty "
                    f"lines; need ≥4 for context)"
                )
        # Project name sanity: lowercase alnum / underscore, no path.
        if k == "project":
            if not re.fullmatch(r"[a-z0-9_]+", v):
                missing.append(
                    f"project (must be lowercase alphanumeric / "
                    f"underscore; got {v!r})"
                )
        # Filename sanity: no path separators.
        if k == "input_filename":
            if "/" in v or "\\" in v or ".." in v:
                missing.append(
                    f"input_filename (must be a bare filename; "
                    f"got {v!r})"
                )
    return missing


def _emit_fixture(repo_root: Path, parsed: Dict[str, str],
                  issue_number: int) -> Path:
    project = parsed["project"]
    fname = parsed["input_filename"]
    snippet = parsed["input_snippet"]
    fixtures_dir = (repo_root
                    / "vibe-ic-marketplace/plugins/vibe-ic/tests"
                    / "phase1_fixtures" / project)
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = fixtures_dir / fname
    fixture_path.write_text(
        snippet if snippet.endswith("\n") else snippet + "\n",
        encoding="utf-8",
    )
    # Append a pending-record sidecar entry.
    pending_path = (repo_root
                    / "vibe-ic-marketplace/plugins/vibe-ic/tests"
                    / "phase1_fixtures" / "_pending.json")
    pending: List[dict] = []
    if pending_path.is_file():
        try:
            pending = json.loads(pending_path.read_text())
        except Exception:
            pending = []
    pending.append({
        "issue": issue_number,
        "project": project,
        "layer": parsed.get("layer", ""),
        "field": parsed.get("field_path", ""),
        "expected": parsed.get("expected", ""),
        "actual": parsed.get("actual", ""),
        "version_observed": parsed.get("version_observed", ""),
        "version_lkg": parsed.get("version_lkg", ""),
        "fixture_path": str(fixture_path.relative_to(repo_root)),
    })
    pending_path.write_text(
        json.dumps(pending, indent=2, ensure_ascii=False) + "\n"
    )
    return fixture_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue-number", type=int, required=True)
    ap.add_argument("--repo", default="vibeic/vibe-ic")
    ap.add_argument("--token-file", default=None)
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--no-emit-fixture", action="store_true")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root \
        else Path(__file__).resolve().parents[4]

    try:
        token = _read_token(args.token_file)
    except RuntimeError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    body, _ = _fetch_issue_body(args.repo, args.issue_number, token)
    if not body.strip():
        print(
            f"FAIL: issue #{args.issue_number} has empty body",
            file=sys.stderr,
        )
        return 1

    parsed = _parse_form_issue(body)
    missing = _validate(parsed)
    if missing:
        print(
            f"FAIL: issue #{args.issue_number} does not meet the "
            f"regression-issue intake template.",
            file=sys.stderr,
        )
        print("Missing or invalid mandatory fields:", file=sys.stderr)
        for k in missing:
            print(f"  - {k}", file=sys.stderr)
        print(
            "\nUse the template at "
            ".github/ISSUE_TEMPLATE/picker-or-extractor-regression.yml "
            "and post a follow-up comment that fills the gaps.",
            file=sys.stderr,
        )
        return 1

    # flow #485 — filing-side acceptance convention check (non-fatal):
    # an issue whose '## 驗收' section carries NO fenced executable
    # command leaves the deterministic acceptance-evidence gate unable
    # to bite (named ACCEPTANCE_NARRATIVE_ONLY there). Warn at filing
    # time so the author adds >=1 concrete command.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import acceptance_evidence_in_fix_comment_check as _acc
        _sec = _acc.extract_acceptance_section(body)
        if _sec is not None:
            _cmds, _ = _acc.extract_commands(_sec)
            if not _cmds:
                print(
                    "WARNING: ACCEPTANCE_NARRATIVE_ONLY — the issue's "
                    "'## 驗收' section carries no fenced executable "
                    "command; filing convention requires >=1 so the "
                    "acceptance-evidence gate can bite (flow #485).",
                    file=sys.stderr,
                )
    except Exception:  # noqa: BLE001 — advisory only, never blocks intake
        pass

    print(f"PASS: issue #{args.issue_number} meets intake template.")
    print(f"  project          = {parsed['project']}")
    print(f"  layer            = {parsed['layer']}")
    print(f"  field            = {parsed['field_path']}")
    print(f"  expected         = {parsed['expected']!r}")
    print(f"  actual           = {parsed['actual']!r}")
    print(f"  version_observed = {parsed['version_observed']}")

    if args.no_emit_fixture:
        return 0

    fixture_path = _emit_fixture(repo_root, parsed, args.issue_number)
    print(f"  fixture          = {fixture_path}")
    print(
        f"\nNext step (debug agent):\n"
        f"  cd vibe-ic-marketplace/plugins/vibe-ic && "
        f"python3 -m pytest tests/test_phase1_fixtures_regression.py "
        f"-k {parsed['project']}\n"
        f"  → must FAIL on current code "
        f"(actual={parsed['actual']!r}); a fix is then warranted."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
