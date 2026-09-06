"""Auto-generated tests for mixed-signal-cosim compliance checking.

Reads ../compliance.yaml and drives ../../_shared/skill_compliance_check.py.
Do not hand-edit — run plugins/_shared/gen_compliance_tests.py to refresh.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

# Locate driver and compliance file relative to this test
# Layout: .../vibe-ic/skills/<skill>/tests/test_compliance.py
# Driver: .../vibe-ic/_shared/skill_compliance_check.py
THIS        = Path(__file__).resolve()
SKILL_DIR   = THIS.parent.parent
COMPLIANCE  = SKILL_DIR / "compliance.yaml"
DRIVER      = THIS.parents[3] / "_shared" / "skill_compliance_check.py"
assert COMPLIANCE.exists(), f"compliance.yaml missing: {COMPLIANCE}"
assert DRIVER.exists(), f"driver missing: {DRIVER}"

sys.path.insert(0, str(DRIVER.parent))
import skill_compliance_check as scc  # noqa: E402
import synthetic_fixture_limits as LIMITS  # noqa: E402
from pattern_satisfier import pattern_to_satisfier  # noqa: E402

SKILL_NAME = "mixed-signal-cosim"


def load_requirements():
    return scc._load_yaml(COMPLIANCE)


def build_good_output(compliance):
    """Produce text that contains a satisfier for every required pattern.

    #2057 — the satisfier is `_shared/pattern_satisfier.py`, which walks the
    regex's own parse tree and verifies its output with `re.fullmatch` before
    returning it. It replaces a chain of `re.sub` rewrites over the pattern
    TEXT that emitted things like `## (?:Output)` and a literal `{7,40}`, and
    therefore did not satisfy the pattern it was built from on 53 of the 69
    skills shipping this file.
    """
    parts = ["# Auto-built good output\n"]
    for r in compliance.get("requirements", []) or []:
        pat = r["pattern"]
        sat = _pattern_to_satisfier(pat)
        parts.append(f"<!-- sat for {r['id']} -->\n{sat}\n")
    return "\n".join(parts)


def _pattern_to_satisfier(pat: str) -> str:
    """Delegates to `_shared/pattern_satisfier.py` (#2057).

    This used to be ~25 lines of `re.sub` rewriting the pattern's SURFACE
    text: it kept the `?:` of a non-capturing group, copied a `{m,n}`
    repetition through verbatim, left a literal `.?` / `.*` in the output and
    stripped every backslash at the end — turning `\b` into the letter `b`
    and leaving an inline `(?i)` as visible text. The shared module reads the
    regex's STRUCTURE instead and checks its own answer with `re.fullmatch`
    before returning it.
    """
    return pattern_to_satisfier(pat)


def run_driver(tmp_path, text):
    report = tmp_path / "out.md"
    report.write_text(text)
    out_json = tmp_path / "audit.json"
    res = subprocess.run(
        [sys.executable, str(DRIVER),
         "--requirements", str(COMPLIANCE),
         "--json", str(out_json), str(report)],
        capture_output=True, text=True)
    data = json.loads(out_json.read_text()) if out_json.exists() else None
    return res, data


def test_compliance_yaml_loads():
    spec = load_requirements()
    assert isinstance(spec, dict), "compliance.yaml must parse to a dict"
    assert spec.get("skill") == "mixed-signal-cosim", (
        f"compliance.yaml skill field mismatch: got {spec.get('skill')}")
    reqs = spec.get("requirements", [])
    assert isinstance(reqs, list) and len(reqs) > 0, (
        "compliance.yaml must declare at least one requirement")


def test_empty_output_fails_audit(tmp_path):
    """Sanity: empty output must fail every required check."""
    res, data = run_driver(tmp_path, "")
    assert res.returncode == 1, "empty output should FAIL audit"
    assert data["verdict"] == "FAIL"


def _declared_receipt_cross_checks(spec):
    """The cross-checks this skill's OWN yaml binds to an auditor's receipt.

    DERIVED from the yaml, never a hand-written second list — a hand-written
    register beside a generated one is what drifted in #2057 item 1.
    """
    return {c["id"] for c in (spec.get("cross_checks") or [])
            if c.get("rule") == "audit_receipt_evidence"}


def _receipt_finding_base(finding_id):
    """`audit_receipt_evidence` reports a configuration error under a
    suffixed id (`<id>_unknown_auditor`, `<id>_no_auditor`); both are the
    same declared cross-check."""
    for suffix in ("_unknown_auditor", "_no_auditor"):
        if finding_id.endswith(suffix):
            return finding_id[:-len(suffix)]
    return finding_id


def test_good_output_passes_all_required(tmp_path):
    """A synthetic good-output built from all patterns satisfies the checker.

    #2050 — THIS TEST USED TO SKIP BEFORE ITS ASSERT. When the synthetic
    document failed any required pattern it called `pytest.skip()`, so on 53
    of the 69 skills that ship this file the assert below never ran and the
    suite still reported green. That is how #2048 survived: the acceptance
    command in that issue gave byte-identical node-id sets on both arms.
    cz2050 replaced the blanket skip with a NAMED list of those 53.

    #2057 — the 53 all had ONE cause, the satisfier, and it is fixed:
    `_shared/pattern_satisfier.py` walks the regex's parse tree instead of
    rewriting its text, so `SYNTHETIC_FIXTURE_LIMITATIONS` is now EMPTY and
    every skill's required patterns are really satisfied. The list stays,
    empty, because the assert below still reddens if a NEW pattern becomes
    unreachable — that is the direction it was built to catch.

    With the required patterns satisfied, the outcome is fully determined and
    is asserted OUTRIGHT — no skip, no xfail, in either population:

      * a skill whose yaml binds NO auditor receipt must audit PASS;
      * a skill whose yaml binds one or more must FAIL with exactly those
        cross-checks NOT_MEASURED and nothing else, because a receipt is
        written by a real auditor run over a real subject and a synthetic
        Markdown document has no auditor run behind it. That set is DERIVED
        from the skill's own yaml, so it reddens if a receipt-bound check
        starts passing on nothing AND if any other finding appears.
    """
    spec = load_requirements()
    text = build_good_output(spec)
    res, data = run_driver(tmp_path, text)

    fails = [f for f in data["findings"] if f["severity"] == "FAIL"]
    req_fails = sorted(f["id"] for f in fails if f["id"].startswith("R"))
    declared = sorted(LIMITS.SYNTHETIC_FIXTURE_LIMITATIONS.get(SKILL_NAME, ()))

    assert req_fails == declared, (
        f"{SKILL_NAME}: the named synthetic-fixture limitation list in "
        "_shared/synthetic_fixture_limits.py no longer matches what is "
        f"measured. declared={declared} measured={req_fails}. "
        "If the measured set GREW, a required pattern just became unreachable "
        "for the generator — fix `_shared/pattern_satisfier.py` or the "
        "pattern, do not extend the list to silence this. If it SHRANK, "
        "delete the repaired IDs from the list; that is the list getting "
        "shorter, which is the point.")

    receipt_bound = _declared_receipt_cross_checks(spec)
    measured_receipt = {_receipt_finding_base(f["id"]) for f in fails
                        if not f["id"].startswith("R")}
    assert measured_receipt == receipt_bound, (
        f"{SKILL_NAME}: the non-requirement failures of the synthetic "
        f"good-output are {sorted(measured_receipt)}, but this skill's own "
        f"compliance.yaml binds {sorted(receipt_bound)} to an auditor "
        "receipt. An UNEXPECTED id means the synthetic document tripped "
        "something new; a MISSING one means a receipt-bound audit passed "
        "with no receipt on disk, which is the defect #2048 was about.")

    if receipt_bound:
        assert data["verdict"] == "FAIL" and res.returncode == 1
        for f in fails:
            assert f.get("state") == "NOT_MEASURED", (f["id"], f.get("state"))
        return
    assert data["verdict"] == "PASS", [f["id"] for f in fails]
    assert res.returncode == 0
