#!/usr/bin/env python3
"""organic_issue_body_lint.py — deterministic FILING-TIME lint for
ORGANIC-form backlog issue bodies (flow #489, the #485 coverage gap).

WHY
---
The #485 filing-side warning lives in ``regression_issue_intake_check``,
which is (a) network-only and (b) gated behind the picker-regression
TEMPLATE validation — ORGANIC-form issues (the backlog's dominant shape,
filed straight via ``gh issue create``) never reach it. This standalone
lint gives the acceptance-section convention a deterministic hook at the
moment it matters: BEFORE the issue is filed (draft → lint → create).

WHAT IT CHECKS (named findings, all chip-AGNOSTIC)
---------------------------------------------------
* ``MISSING_ACCEPTANCE``          — no '## 驗收'/acceptance section at all.
* ``ACCEPTANCE_NARRATIVE_ONLY``   — the acceptance section carries no
  fenced/command-shaped executable command (the deterministic
  acceptance-evidence gate then cannot bite; flow #485).
* ``NO_DEFECT_ARTIFACT``          — the body names no path-like defect
  artifact; reminds the filer of the #487 snapshot convention
  (``defect_artifact_snapshot.py`` at filing time).

Extractors are REUSED from ``acceptance_evidence_in_fix_comment_check``
(single source of the section/command grammar — no drift).

USAGE
-----
    python3 programs/organic_issue_body_lint.py <body.md>
    echo "<body>" | python3 programs/organic_issue_body_lint.py -
    ... [--json out.json] [--strict]

EXIT CODES
----------
  0  PASS (no findings) or findings present WITHOUT --strict (the lint
     is advisory at filing time — exit 0 leaves an auditable trace).
  1  findings present AND --strict was given (automation hook).
  2  usage / I/O error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance_evidence_in_fix_comment_check import (  # noqa: E402
    extract_acceptance_section,
    extract_commands,
)

# A path-like token: contains a '/' and ends in a short extension, OR a
# backtick-quoted bare filename with an artifact-ish extension. Structural
# only — no chip/vendor names.
_PATH_RE = re.compile(
    r"[\w.\-]+(?:/[\w.\-]+)+\.\w{1,8}\b"           # a/b/c.ext
    r"|`[\w.\-]+\.(?:rpt|log|json|def|gds|spef|v|sv|sp|lef|lib|xml|txt)`"
)


def lint(body: str) -> List[dict]:
    findings: List[dict] = []
    section = extract_acceptance_section(body)
    if section is None:
        findings.append({
            "rule": "MISSING_ACCEPTANCE",
            "severity": "WARNING",
            "message": ("issue body has no '## 驗收'/acceptance section — "
                        "filing convention requires one with >=1 fenced "
                        "executable command (flow #485/#489)"),
        })
    else:
        commands, _criteria = extract_commands(section)
        if not commands:
            findings.append({
                "rule": "ACCEPTANCE_NARRATIVE_ONLY",
                "severity": "WARNING",
                "message": ("'## 驗收' carries no fenced executable command "
                            "— the deterministic acceptance-evidence gate "
                            "cannot bite (flow #485); add >=1 concrete "
                            "command in fenced code"),
            })
    if not _PATH_RE.search(body):
        findings.append({
            "rule": "NO_DEFECT_ARTIFACT",
            "severity": "WARNING",
            "message": ("issue body names no path-like defect artifact — "
                        "name the artifact(s) and snapshot them at filing "
                        "time via defect_artifact_snapshot.py (flow #487) "
                        "so verification never depends on a mutable run "
                        "dir"),
        })
    return findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Filing-time lint for ORGANIC-form backlog issue "
                    "bodies (acceptance + artifact conventions).")
    ap.add_argument("body", help="issue-body markdown file, or '-' for stdin")
    ap.add_argument("--json", default=None,
                    help="write the findings report to this path")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any finding is present")
    args = ap.parse_args(argv)

    try:
        if args.body == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.body).read_text(encoding="utf-8")
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if not text.strip():
        print("ERROR: empty issue body", file=sys.stderr)
        return 2

    findings = lint(text)
    report = {
        "program": "organic_issue_body_lint",
        "version": "1.0.0",
        "verdict": "PASS" if not findings else "WARNINGS",
        "findings": findings,
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    if not findings:
        print("PASS: issue body meets the filing conventions "
              "(acceptance commands + named defect artifact).")
        return 0
    for f in findings:
        print(f"WARNING: {f['rule']} — {f['message']}")
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
