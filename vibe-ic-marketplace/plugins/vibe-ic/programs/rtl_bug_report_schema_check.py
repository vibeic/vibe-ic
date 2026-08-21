#!/usr/bin/env python3
"""rtl_bug_report_schema_check.py — v0.54 plugin gate

Forces "RTL bug" claims to carry traceable spec evidence so an agent
cannot self-attest both the spec AND the bug ("I think the spec means
X; the RTL doesn't do X; therefore the RTL has a silicon-blocking
bug").

The v0.53 fresh-agent run claimed two "silicon-blocking bugs":
  1. Lock-bit not enforced — `mac.v` E0 handler doesn't gate writes
     on EngineerMode.
  2. TestMode pattern matcher is stub — RTL enters TestMode via the
     0xEC HID command instead of HV + CC_I + ID_BUS serial pattern.

Both might be real bugs, but they might also be the spec's intended
behaviour (engineer mode is supposed to bypass lock; the HID-only
TestMode entry might be a deliberate FPGA-only shortcut). Without
verbatim spec text plus a doc citation, the claim is just an opinion.

This gate validates that every entry in `reports/rtl_bugs.json` (or
a path passed by `--bugs`) carries:

  - `id`             unique short identifier
  - `severity`       one of {info, warning, error, silicon-blocking}
  - `module`         RTL module / file under test
  - `observed`       what the RTL actually does (≥ 30 chars)
  - `expected`       what the bug-claimer says it should do (≥ 30 chars)
  - `spec_evidence`  (the load-bearing field — see below)
  - `repro`          how to reproduce (testbench file or sim hook)

`spec_evidence` schema:
  - `doc`            path to the spec doc this bug is derived from
                     (must exist on disk under `input/docs/` or
                     `generated_docs/`, or the user must opt in via
                     `--allow-external-docs`)
  - `locator`        page / line / section / table reference
  - `quote`          verbatim quote (≥ 20 chars, no ellipsis on its own)
  - `interpretation` one sentence — why the quote means the RTL is wrong

A `silicon-blocking` claim additionally requires:
  - `expected_behaviour_unambiguous: true`
    (the agent must affirm that the spec quote is unambiguous;
    a `false` value downgrades severity to `warning` automatically
    by the gate's report — but the gate fails so the agent re-thinks)
  - At least 1 of: `vendor_sample_test`, `independent_review`

Usage:
    python3 rtl_bug_report_schema_check.py <project_dir>
        [--bugs <path>]                    (default: <proj>/reports/rtl_bugs.json)
        [--allow-external-docs]            (skip the input/docs/ existence check)
        [--json <path>]                    (default: <proj>/reports/gates/rtl_bug_schema.json)
        [--out <path>]                     (deprecated alias of --json)
        [--strict]                          (default behaviour; flag is a no-op for now)

Exit codes:
    0 — every bug entry is well-formed, with traceable spec evidence
    1 — one or more entries fail the schema
    2 — input file missing / malformed JSON

WHY `--json` EXISTS ALONGSIDE `--out`
-------------------------------------
Step 2 of ``flow/phase1_phase2_phase3.yaml`` declares this gate as::

    rtl_bug_report_schema_check . --json reports/phase2/gates/rtl_bug_schema.json

and 112 of the flow's 114 gate commands spell the audit-trail option
``--json``. This program declared only ``--out``, so argparse REFUSED the
flow's own invocation::

    $ rtl_bug_report_schema_check . --json reports/phase2/gates/rtl_bug_schema.json
    rtl_bug_report_schema_check.py: error: unrecognized arguments: --json ...
    rc=2

and ``flow_compliance_check._check_program_exit_zero`` credits ``rc == 2`` as
VACUOUS_PASS — so the clause banked a step PASS while auditing NOTHING and
never writing the audit trail the yaml names. Same defect class as
``lvs_report_check`` (#507) and ``power_report_check``: an option the caller
declares and the callee discards.

``--json`` is now the canonical spelling and ``--out`` is kept as an alias
(same ``dest``) so every existing caller and test keeps working. Argparse's
last-wins applies if both are given.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import _path_layout as _pl


_REQUIRED_TOP_FIELDS = (
    "id", "severity", "module", "observed", "expected",
    "spec_evidence", "repro",
)
_REQUIRED_EVIDENCE_FIELDS = ("doc", "locator", "quote", "interpretation")
_VALID_SEVERITIES = {"info", "warning", "error", "silicon-blocking"}
_MIN_OBSERVED = 30
_MIN_EXPECTED = 30
_MIN_QUOTE = 20


def load_bugs(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("bugs"), list):
        return data["bugs"]
    raise ValueError(
        "rtl_bugs file must be a JSON list, or a JSON object with a "
        "top-level `bugs:` list")


def _check_quote(quote: str) -> Optional[str]:
    if not isinstance(quote, str):
        return "quote must be a string"
    stripped = quote.strip()
    # A quote that is JUST an ellipsis (or surrounding whitespace +
    # ellipsis) carries no actual evidence — flag this BEFORE the
    # length check so the message is informative rather than a generic
    # "too short".
    if stripped in {"...", "…", "[...]"}:
        return "quote is just an ellipsis — provide actual spec text"
    if len(stripped) < _MIN_QUOTE:
        return f"quote too short (need >= {_MIN_QUOTE} chars)"
    return None


def _check_doc_exists(doc: str, project_dir: Path,
                      allow_external: bool) -> Optional[str]:
    p = (project_dir / doc) if not Path(doc).is_absolute() else Path(doc)
    if p.exists():
        return None
    if allow_external:
        return None  # caller opted out of existence check
    # Helpful suggestion: typical locations
    candidates_seen = []
    for sub in ("phase1/generated_docs", "input/docs", "generated_docs", "docs"):
        cand = project_dir / sub / Path(doc).name
        if cand.exists():
            candidates_seen.append(str(cand.relative_to(project_dir)))
    msg = (f"spec doc {doc!r} not found at {p} "
           f"(looked relative to {project_dir})")
    if candidates_seen:
        msg += f"; similar file at: {', '.join(candidates_seen)}"
    return msg


def check_entry(idx: int, bug: Dict[str, Any], project_dir: Path,
                allow_external: bool) -> List[str]:
    """Return list of human-readable problems for a single bug entry."""
    problems: List[str] = []
    if not isinstance(bug, dict):
        return [f"entry #{idx} is not an object"]

    # Required top-level fields
    for f in _REQUIRED_TOP_FIELDS:
        if f not in bug:
            problems.append(f"missing required field: {f}")

    sev = bug.get("severity")
    if sev is not None and sev not in _VALID_SEVERITIES:
        problems.append(
            f"severity={sev!r} not in {sorted(_VALID_SEVERITIES)}")

    obs = bug.get("observed", "")
    if isinstance(obs, str) and len(obs.strip()) < _MIN_OBSERVED:
        problems.append(
            f"observed too short ({len(obs.strip())} chars; need >= {_MIN_OBSERVED}) "
            "— describe what the RTL actually does, not just a one-liner")

    exp = bug.get("expected", "")
    if isinstance(exp, str) and len(exp.strip()) < _MIN_EXPECTED:
        problems.append(
            f"expected too short ({len(exp.strip())} chars; need >= {_MIN_EXPECTED}) "
            "— describe what the spec actually mandates")

    # spec_evidence sub-block
    ev = bug.get("spec_evidence")
    if not isinstance(ev, dict):
        problems.append("spec_evidence must be an object — see SKILL.md")
    else:
        for f in _REQUIRED_EVIDENCE_FIELDS:
            if f not in ev:
                problems.append(f"spec_evidence.{f} missing")
        q_problem = _check_quote(ev.get("quote", ""))
        if q_problem:
            problems.append(f"spec_evidence.quote: {q_problem}")
        doc = ev.get("doc")
        if doc:
            doc_problem = _check_doc_exists(doc, project_dir, allow_external)
            if doc_problem:
                problems.append(f"spec_evidence.doc: {doc_problem}")
        loc = ev.get("locator")
        if loc is not None and not str(loc).strip():
            problems.append("spec_evidence.locator is empty")
        interp = ev.get("interpretation")
        if interp is not None and not str(interp).strip():
            problems.append("spec_evidence.interpretation is empty")

    # silicon-blocking severity needs extra confirmation
    if sev == "silicon-blocking":
        if bug.get("expected_behaviour_unambiguous") is not True:
            problems.append(
                "silicon-blocking requires "
                "expected_behaviour_unambiguous: true (got "
                f"{bug.get('expected_behaviour_unambiguous')!r})")
        secondary_keys = ("vendor_sample_test", "independent_review")
        if not any(bug.get(k) for k in secondary_keys):
            problems.append(
                "silicon-blocking requires at least one of: "
                f"{', '.join(secondary_keys)} "
                "— a single agent's reading of the spec is not enough "
                "to declare a silicon-blocking bug")

    # repro field
    repro = bug.get("repro", "")
    if isinstance(repro, str) and not repro.strip():
        problems.append(
            "repro is empty — point at a tb file, sim hook, or "
            "command sequence")

    return problems


def check(project_dir: Path, bugs_path: Path, out_path: Path,
          allow_external: bool) -> Tuple[int, Dict[str, Any]]:
    if not bugs_path.exists():
        return 2, {"error": f"bugs file not found: {bugs_path}"}
    try:
        bugs = load_bugs(bugs_path)
    except (json.JSONDecodeError, ValueError) as e:
        return 2, {"error": f"cannot parse bugs file: {e}"}

    seen_ids: Dict[str, int] = {}
    findings: List[Dict[str, Any]] = []
    fail = 0

    for i, bug in enumerate(bugs):
        problems = check_entry(i, bug, project_dir, allow_external)
        if isinstance(bug, dict):
            bid = str(bug.get("id", f"<no-id-#{i}>"))
            if bid in seen_ids:
                problems.append(
                    f"duplicate id {bid!r} (also at entry #{seen_ids[bid]})")
            else:
                seen_ids[bid] = i
        else:
            bid = f"<entry-{i}>"
        findings.append({
            "index": i,
            "id": bid,
            "ok": not problems,
            "problems": problems,
        })
        if problems:
            fail += 1

    report = {
        "gate": "rtl_bug_report_schema",
        "bugs_file": str(bugs_path),
        "total": len(bugs),
        "ok": len(bugs) - fail,
        "fail": fail,
        "findings": findings,
        "pass": fail == 0,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return (0 if fail == 0 else 1), report


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir")
    p.add_argument("--bugs", default=None,
                   help="Path to rtl_bugs.json "
                        "(default: <project>/reports/rtl_bugs.json)")
    p.add_argument("--allow-external-docs", action="store_true",
                   help="Skip the spec_evidence.doc existence check "
                        "(use when bug citations point at docs not "
                        "present in the project tree).")
    # `--json` is the flow-wide spelling (112 of 114 gate commands); `--out`
    # is the historical alias this program shipped with. ONE dest, so the
    # value lands in `args.out` whichever spelling the caller used.
    p.add_argument("--json", "--out", dest="out", default=None,
                   help="Output JSON path "
                        "(default: <project>/reports/gates/rtl_bug_schema.json)")
    p.add_argument("--strict", action="store_true",
                   help="Reserved; current behaviour is already strict.")
    args = p.parse_args(argv)

    proj = Path(args.project_dir).resolve()
    if not proj.exists():
        print(f"[rtl-bug-schema] project_dir not found: {proj}", file=sys.stderr)
        return 2
    bugs = Path(args.bugs) if args.bugs else _pl.report_path(proj, "rtl_bugs.json")
    out = Path(args.out) if args.out \
        else _pl.report_path(proj, "gates/rtl_bug_schema.json")

    rc, report = check(proj, bugs, out, args.allow_external_docs)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
