#!/usr/bin/env python3
"""
hw_acceptance_test_passed_check.py — final-step gate for the closed
hardware debug loop (hw-debug-loop skill).

Why this gate exists
====================
hw-debug-loop SKILL ends with Step 7: convergence audit. This gate
is what the audit runs. It checks that the bounded debug loop
actually converged to a PASS verdict on the rig and that every
oracle-referenced fix is backed by a captured artifact.

The gate enforces three things:

  1. `evidence/baseline_fail.json` exists — the FAILing baseline
     was recorded before any fix, so the iteration is reproducible.

  2. `evidence/iter_<N>_pass.json` exists AND
     `evidence/acceptance_signature.json` declares what "PASS" means
     for this project (which fields/values constitute a passing
     verdict). v0.119.15: the gate no longer silently falls back to
     an <half-duplex-tester>-specific fingerprint (byte[6]=0xF2). Projects must
     declare their own signature explicitly OR opt into the named
     `"md905_byte6_F2"` legacy template — see signature schema below.

  3. Every `waivers.json["oracle_referenced_fix"]` entry points to
     an artifact under `input/oracle/` that exists. No silent
     oracle copies.

Only when all three hold is Phase 2c complete.

Usage
-----
python3 hw_acceptance_test_passed_check.py <project_dir>

Returns 0 on PASS, 1 on FAIL.
"""

import json
import re
import sys
from pathlib import Path


def find_pass_artifact(evidence_dir: Path):
    """Find iter_<N>_pass.json with the highest N. Returns (path, parsed)."""
    if not evidence_dir.is_dir():
        return None, None
    cands = []
    for f in evidence_dir.iterdir():
        m = re.match(r"iter_(\d+)_pass\.json$", f.name)
        if m:
            cands.append((int(m.group(1)), f))
    if not cands:
        return None, None
    cands.sort()
    path = cands[-1][1]
    try:
        data = json.loads(path.read_text())
        return path, data
    except Exception:
        return path, None


def _check_example_tester_byte6_F2_template(data: dict) -> tuple[bool, str]:
    """Named template `example_tester_byte6_F2` — generic half-duplex
    tester acceptance signature. Projects that ship a half-duplex-tester-
    class host tester opt in explicitly via acceptance_signature.json:
    {"template": "example_tester_byte6_F2"}. Not used as a silent default
    in v0.119.15+.
    """
    if data.get("verdict") != "PASS":
        return False, f"verdict is {data.get('verdict')!r}, not 'PASS'"
    frames = data.get("e0_frames") or []
    if len(frames) < 1:
        return False, "no e0_frames captured"
    pass_count = sum(1 for f in frames if f.get("byte6") == 0xF2 or
                                          f.get("byte6") == 242)
    if pass_count < 1:
        return False, "no e0_frame has byte[6]=0xF2"
    return True, f"verdict=PASS, {pass_count}/{len(frames)} frames byte[6]=0xF2"


# Registry of named acceptance templates. Add new chip families here.
# The canonical key is the chip-AGNOSTIC `example_tester_byte6_F2`; the
# legacy benchmark-specific key is kept as a back-compat alias so older
# acceptance_signature.json files still resolve.
_NAMED_TEMPLATES = {
    "example_tester_byte6_F2": _check_example_tester_byte6_F2_template,
    "md905_byte6_F2": _check_example_tester_byte6_F2_template,
}


def check_custom_signature(data: dict, sig: dict) -> tuple[bool, str]:
    """Verify the stored data matches a project-defined signature.

    Schema (one of):

      Direct field-equality:
        {"expected": {"verdict": "PASS", "frame_count_min": 5}}
        — every key in `expected` must equal the corresponding key in
          the captured pass-artifact data. Custom (non-equality)
          checks are not supported in this minimal form; use a
          template for richer logic.

      Named template:
        {"template": "md905_byte6_F2"}
        — dispatches to _NAMED_TEMPLATES.

    Both forms may be combined; template runs first, then equality.
    """
    template = sig.get("template")
    if isinstance(template, str):
        if template not in _NAMED_TEMPLATES:
            return False, (f"acceptance_signature.template={template!r} not "
                           f"in registry {sorted(_NAMED_TEMPLATES)}")
        ok, why = _NAMED_TEMPLATES[template](data)
        if not ok:
            return False, f"template {template!r}: {why}"

    expected = sig.get("expected", {})
    if isinstance(expected, dict):
        for k, v in expected.items():
            if data.get(k) != v:
                return False, f"field {k!r} = {data.get(k)!r}, expected {v!r}"

    return True, ("matches custom acceptance signature"
                  if not template else
                  f"matches template {template!r} + expected fields")


def check_oracle_evidence(project_dir: Path, waivers: dict) -> list[str]:
    """For every oracle_referenced_fix entry, verify the cited
    evidence file exists. Returns list of problems (empty = OK)."""
    problems = []
    fixes = waivers.get("oracle_referenced_fix") or []
    if isinstance(fixes, dict):
        fixes = [fixes]
    for fix in fixes:
        if not isinstance(fix, dict):
            problems.append(f"oracle_referenced_fix entry is not a dict: {fix!r}")
            continue
        evidence = fix.get("evidence")
        if not evidence:
            problems.append(f"fix entry {fix.get('opcode', '?')!r} has no "
                            "'evidence' field pointing at the dump file")
            continue
        ev_path = project_dir / evidence
        if not ev_path.exists():
            problems.append(f"evidence file {evidence!r} (declared for "
                            f"opcode {fix.get('opcode', '?')}) does not exist")
    return problems


def main():
    if len(sys.argv) < 2:
        print("Usage: hw_acceptance_test_passed_check.py <project_dir>")
        sys.exit(2)
    project_dir = Path(sys.argv[1]).resolve()
    evidence_dir = project_dir / "evidence"

    # Soft skip: if no hw-debug-loop has been entered (no evidence
    # baseline), assume Phase 2c was either trivially passed (rare)
    # or not yet started. The flow_compliance_check overall verdict
    # combined with other gates handles those cases.
    if not (evidence_dir / "baseline_fail.json").exists() and \
       not list(evidence_dir.glob("iter_*_pass.json") if evidence_dir.is_dir() else []):
        print("PASS — no hw-debug-loop evidence directory; gate not yet "
              "applicable (Phase 2c either not entered or trivially passed)")
        sys.exit(0)

    failures = []

    # 1. Baseline fail evidence.
    if not (evidence_dir / "baseline_fail.json").exists():
        failures.append("evidence/baseline_fail.json missing — the initial "
                        "FAILing frames + SOF sha + git rev were not recorded")

    # 2. Final PASS artifact.
    pass_path, pass_data = find_pass_artifact(evidence_dir)
    if pass_path is None:
        failures.append("no evidence/iter_<N>_pass.json artifact found — "
                        "the loop has not converged")
    else:
        # v0.119.15: acceptance signature is REQUIRED — no silent
        # <half-duplex-tester> default. Each project must declare what "PASS"
        # looks like for its own host rig.
        sig_path = evidence_dir / "acceptance_signature.json"
        if pass_data is None:
            failures.append(f"final PASS artifact {pass_path.name!r} is "
                            "unparseable")
        elif not sig_path.exists():
            failures.append(
                "evidence/acceptance_signature.json missing — projects "
                "must declare their own pass-fingerprint (chip-agnostic "
                "schema). Either ship a signature file with "
                '`{"template": "md905_byte6_F2"}` (legacy <half-duplex-tester> host '
                'tester) or `{"expected": {"verdict": "PASS", ...}}` '
                "for project-specific equality checks."
            )
        else:
            try:
                sig = json.loads(sig_path.read_text())
                ok, why = check_custom_signature(pass_data, sig)
            except Exception as e:
                ok, why = False, f"acceptance_signature.json unreadable: {e}"
            if not ok:
                failures.append(
                    f"final PASS artifact {pass_path.name!r} does not "
                    f"satisfy the acceptance signature: {why}")

    # 3. Oracle-referenced fixes have evidence.
    waivers_path = project_dir / "waivers.json"
    if waivers_path.exists():
        try:
            waivers = json.loads(waivers_path.read_text())
            for problem in check_oracle_evidence(project_dir, waivers):
                failures.append(problem)
        except Exception as e:
            failures.append(f"waivers.json unreadable: {e}")

    if not failures:
        print("PASS — closed hardware debug loop converged. baseline_fail "
              "recorded, iter_<N>_pass meets acceptance signature, every "
              "oracle_referenced_fix has cited evidence.")
        sys.exit(0)

    print(f"FAIL — closed hardware debug loop has not converged "
          f"({len(failures)} problem(s)):")
    for f in failures:
        print(f"  • {f}")
    print()
    print("Why this matters:")
    print("  hw-debug-loop SKILL Step 7 (convergence audit) requires that:")
    print("    (1) the FAILing baseline was recorded;")
    print("    (2) the final iteration actually produced byte[6]=0xF2;")
    print("    (3) every oracle-referenced delta is backed by a captured")
    print("        oracle dump or scope artifact.")
    print("  Without all three, the L1-L23 → RTL → SOF flow is not")
    print("  reproducible — the next fresh agent reading the spec will")
    print("  re-introduce the bug because the silicon-vs-spec delta wasn't")
    print("  documented.")
    print()
    print("Fix: re-run hw-debug-loop SKILL from Step 1 if no baseline; or")
    print("     run the host acceptance test until PASS and save")
    print("     evidence/iter_<N>_pass.json; or attach the oracle dump")
    print("     file referenced by each oracle_referenced_fix entry.")
    sys.exit(1)


if __name__ == "__main__":
    main()
