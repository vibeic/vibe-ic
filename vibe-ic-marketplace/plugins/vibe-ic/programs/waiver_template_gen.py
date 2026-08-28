#!/usr/bin/env python3
"""
waiver_template_gen.py — Generate a `waivers.json.template` scaffold
from a flow_compliance_check.py verdict.

Why this exists
---------------
Field agents whose Phase 2+3 verdict is `Overall: FAIL` because of
canonical-flow steps that genuinely cannot run in the open-source
container (e.g. DFT / SPEF / IR / EM / antenna / SI / metal-fill, M1-M4
mixed-signal, or 5 P0-umbrella sub-gates whose tool dependencies are
commercial) need waivers to reach `PASS_WITH_WAIVERS`.

Hand-authoring 15-20 waiver entries by hand is tedious. The temptation
is to "auto-emit" `waivers.json` from the verdict — but the existing
`waivers_schema_check.py` + `waiver_legitimacy_check.py` are specifically
designed to REJECT self-approved / placeholder / rubber-stamp waivers,
because that's the most common anti-pattern that hides real engineering
gaps behind a green verdict.

This program threads the needle: emit a STRUCTURAL scaffold
(`waivers.json.template`) with:

  - Real `id` values pulled from the verdict
  - `review_required: true` (required by the legitimacy gate)
  - An `_evidence_hint` field carrying the failing-gate output verbatim
    so the human can decide
  - `approver`, `reason`, `ticket` fields set to placeholder values that
    `waivers_schema_check.py` is GUARANTEED to reject (so the template
    cannot accidentally ship as the final `waivers.json`)

The human then:
  1. Renames `waivers.json.template` → `waivers.json`
  2. Fills `approver` (must NOT be agent/claude/ai/self/bot/auto)
  3. Fills `reason` with ≥20 chars of real engineering rationale (NOT
     "TODO" / "TBD" / "n/a" / "skip" / "pending" etc.)
  4. Fills `ticket` (Linear/Jira id)
  5. Re-runs `flow_compliance_check.py --strict`

Anti-fabrication: the program WILL NOT overwrite an existing
`waivers.json` — it only writes the `.template` sibling file. The
template's placeholder approver / reason values are deliberately ones
the schema rejects (`__TODO_HUMAN_NAME__` is not in the SELF_APPROVERS
set, but it's < MIN_REASON_LEN trigger for reason and looks
recognisably "unfilled").

chip-AGNOSTIC: the program only reads `flow_compliance_check` verdict
JSON (or runs the gate fresh). No chip-class string literals, no
hardcoded step ids — the verdict's MISSING / FAIL list is the source
of truth.

Usage
-----
    python3 waiver_template_gen.py <project_dir>
        [--audit-json reports/flow_compliance.json]
        [--out waivers.json.template]
        [--include-fail]    # also scaffold non-waivable FAIL items
        [--quiet]

Exit codes
----------
    0 — template emitted (or no waiver candidates → noop with note)
    1 — would overwrite an existing waivers.json (refused)
    2 — io / parse error
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Placeholder strings used in the template. These are intentionally
# chosen so that waivers_schema_check.py REJECTS them with helpful
# error messages — the user CANNOT accidentally ship the template as
# the final waivers.json. Specifically:
#
#   - `approver = "agent"` is in waivers_schema_check.SELF_APPROVERS,
#     so the self-approval rule fires immediately.
#   - `reason = "TODO"` is in waivers_schema_check.PLACEHOLDER_REASONS,
#     and is also below MIN_REASON_LEN=20 — double-protected reject.
#   - `ticket` has no enforced schema value at present; a placeholder is
#     fine here, but is left obvious so the human sees the "fill me".
#
# A separate `_template_note` field carries the long-form guidance
# (commercial tool required, foundry-signoff plan, etc.). The schema
# ignores keys starting with `_`.
PLACEHOLDER_APPROVER = "agent"
PLACEHOLDER_REASON = "TODO"
PLACEHOLDER_TICKET = "__TODO_TICKET_ID__"
TEMPLATE_NOTE_BODY = (
    "FILL ME: replace `reason` with >=20 chars of engineering "
    "rationale (NOT 'TODO' / 'TBD' / 'n/a' / 'skip' / 'pending' / "
    "'will do later'). Replace `approver` with a real human name "
    "(NOT 'agent' / 'claude' / 'ai' / 'self' / 'bot' / 'automated' "
    "/ 'auto'). Replace `ticket` with a Linear/Jira id. Include in "
    "the reason: (a) the commercial / external tool required, "
    "(b) what the human ran in the open-source flow and what it "
    "produced, (c) the foundry-signoff plan entry that closes this "
    "deferral."
)


def _run_flow_compliance(project: Path, audit_json: Path) -> int:
    """Run flow_compliance_check.py if no fresh JSON exists. Returns
    its exit code. We don't fail the template generator on rc != 0 —
    a FAIL verdict is precisely the input we want."""
    if audit_json.exists():
        return 0
    prog = Path(__file__).parent / "flow_compliance_check.py"
    if not prog.is_file():
        return 2
    audit_json.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["python3", str(prog), str(project),
           "--phase", "3", "--strict-structural",
           "--json", str(audit_json)]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=120)
        return cp.returncode
    except Exception:
        return 2


def _normalise_step_id(raw: Any) -> Optional[Any]:
    """Normalise step id to the schema's accepted form.
    int 1..40, or string "A<n>", "M<n>", "P0"."""
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if s.upper() == "P0":
            return "P0"
        import re
        m = re.match(r"^([AM])(\d+)$", s, re.IGNORECASE)
        if m:
            return f"{m.group(1).upper()}{int(m.group(2))}"
        # step_<n>_label
        m2 = re.match(r"^step[_\-\s]*(\d+)", s, re.IGNORECASE)
        if m2:
            try:
                return int(m2.group(1))
            except ValueError:
                pass
        try:
            return int(s)
        except ValueError:
            pass
    return None


def _classify_waivable(status: str) -> bool:
    """Only MISSING (no tool available / step did not run for a
    structural reason) is template-worthy. FAIL means a step ran and
    produced a real defect — those should be FIXED, not waivered.
    --include-fail relaxes this for advanced use."""
    return status in ("MISSING",)


def _build_entries(audit: Dict[str, Any],
                   include_fail: bool) -> List[Dict[str, Any]]:
    """Walk the flow_compliance_check audit JSON and return waiver
    template entries (one per MISSING / (optionally) FAIL step)."""
    entries: List[Dict[str, Any]] = []
    results = audit.get("results") or audit.get("steps") or []
    if not isinstance(results, list):
        return entries
    for r in results:
        if not isinstance(r, dict):
            continue
        status = (r.get("status") or "").upper()
        if not include_fail and not _classify_waivable(status):
            continue
        if include_fail and status not in ("MISSING", "FAIL"):
            continue
        sid = _normalise_step_id(r.get("id") or r.get("step_id"))
        if sid is None:
            continue
        # Pull evidence hints — the gate's own message is the best
        # source of truth for the human reviewer.
        ev_hint = (
            r.get("message")
            or r.get("detail")
            or r.get("reason")
            or "(no gate message captured)"
        )
        required = r.get("required_outputs") or r.get("expected") or []
        entry: Dict[str, Any] = {
            "id": sid,
            "reason": PLACEHOLDER_REASON,
            "approver": PLACEHOLDER_APPROVER,
            "review_required": True,
            "ticket": PLACEHOLDER_TICKET,
            "_template_note": TEMPLATE_NOTE_BODY,
            "_evidence_hint": (str(ev_hint)[:500]
                               if not isinstance(ev_hint, list)
                               else ev_hint[:5]),
            "_gate_status": status,
        }
        if required:
            entry["_required_outputs_hint"] = (
                required if isinstance(required, list) else [required]
            )[:10]
        entries.append(entry)
    return entries


def _portable_audit_ref(audit_json: Path, project: Path) -> str:
    """The audit path AS IT SHOULD SHIP: relative to the project it describes.

    `main` resolves `project_dir`, so `audit_json` is always ABSOLUTE by the
    time it reaches here. Writing `str(audit_json)` therefore stamped the
    generating operator's own home directory into `waivers.json.template` — a
    file that ships to every plugin installer — which is exactly what
    `shipped_path_portability_check` R1 exists to refuse. The relative form
    names the same file for whoever reads the template, on any machine.

    An audit outside the project (an absolute `--audit-json` elsewhere) has no
    relative form, so it degrades to the BARE NAME rather than to the absolute
    path: the field is a provenance hint for a human, never something reopened
    by this program, so losing the directory costs nothing and leaking it
    costs portability.
    """
    try:
        return audit_json.relative_to(project).as_posix()
    except ValueError:
        return audit_json.name


def generate(project: Path, audit_json: Path, out_path: Path,
             include_fail: bool, quiet: bool) -> int:
    # Anti-fabrication safety: never overwrite an existing waivers.json.
    real_waivers = project / "waivers.json"
    if out_path.name == "waivers.json" and real_waivers.exists():
        print("waiver_template_gen: refusing to overwrite existing "
              f"{real_waivers}. Use --out <other-path> or remove the "
              "existing file first.", file=sys.stderr)
        return 1

    # Run flow_compliance_check if no fresh audit JSON
    if not audit_json.exists():
        rc = _run_flow_compliance(project, audit_json)
        if rc == 2 or not audit_json.exists():
            print(f"waiver_template_gen: cannot read or produce "
                  f"{audit_json}", file=sys.stderr)
            return 2

    try:
        audit = json.loads(audit_json.read_text())
    except Exception as exc:
        print(f"waiver_template_gen: cannot parse {audit_json}: {exc}",
              file=sys.stderr)
        return 2

    entries = _build_entries(audit, include_fail=include_fail)
    if not entries:
        if not quiet:
            print(f"waiver_template_gen: no MISSING"
                  f"{'/FAIL' if include_fail else ''} steps in audit; "
                  f"nothing to scaffold.")
        return 0

    template = {
        "_note": (
            "Generated by waiver_template_gen.py. Each entry is a "
            "SCAFFOLD; the schema gate will reject this file as-is. "
            "Replace every __TODO__ placeholder with real engineering "
            "rationale and a human approver name before renaming to "
            "waivers.json. The plugin's anti-fabrication doctrine "
            "requires that waivers are human-approved, not "
            "agent-emitted."
        ),
        "_generator": "waiver_template_gen.py",
        "_source_audit": _portable_audit_ref(audit_json, project),
        "waived_steps": entries,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(template, indent=2, ensure_ascii=False)
                        + "\n")
    if not quiet:
        print(f"waiver_template_gen: wrote {len(entries)} scaffold "
              f"entries to {out_path}. Edit __TODO__ placeholders "
              f"before renaming to waivers.json.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir")
    p.add_argument("--audit-json",
                   default="reports/flow_compliance.json",
                   help="Path to flow_compliance_check JSON (run "
                        "gate if absent). Default: "
                        "reports/flow_compliance.json")
    p.add_argument("--out", default="waivers.json.template",
                   help="Output template path "
                        "(default: waivers.json.template)")
    p.add_argument("--include-fail", action="store_true",
                   help="Also scaffold FAIL items (default: only "
                        "MISSING). FAIL items are real defects that "
                        "should typically be FIXED, not waivered; "
                        "use sparingly.")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"waiver_template_gen: not a directory: {project}",
              file=sys.stderr)
        return 2
    audit_json = (project / args.audit_json
                  if not Path(args.audit_json).is_absolute()
                  else Path(args.audit_json))
    out_path = (project / args.out
                if not Path(args.out).is_absolute()
                else Path(args.out))
    return generate(project, audit_json, out_path,
                    include_fail=args.include_fail,
                    quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
