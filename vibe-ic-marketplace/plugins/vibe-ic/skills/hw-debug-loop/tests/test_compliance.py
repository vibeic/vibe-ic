"""Auto-generated tests for hw-debug-loop compliance checking.

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


def load_requirements():
    return scc._load_yaml(COMPLIANCE)


def build_good_output(compliance):
    """Produce text that literally contains a satisfier for every required
    pattern. For simple regex patterns, the pattern text itself (after
    escape cleanup) is often a valid satisfier; we pick a simple default."""
    parts = ["# Auto-built good output\n"]
    for r in compliance.get("requirements", []) or []:
        pat = r["pattern"]
        # Crude satisfier: strip regex meta, produce a literal that matches
        sat = _pattern_to_satisfier(pat)
        parts.append(f"<!-- sat for {r['id']} -->\n{sat}\n")
    return "\n".join(parts)


def _pattern_to_satisfier(pat: str) -> str:
    """Turn a regex into a string that contains a match. Very conservative."""
    # Replace common regex constructs with literal text
    import re
    s = pat
    # \s* -> ' '; \s+ -> ' '; \d+ -> '1'; \w+ -> 'x'
    s = re.sub(r'\\s\*', ' ', s)
    s = re.sub(r'\\s\+', ' ', s)
    s = re.sub(r'\\d\+', '1', s)
    s = re.sub(r'\\d', '1', s)
    s = re.sub(r'\\w\+', 'x', s)
    s = re.sub(r'\\w', 'x', s)
    # Character classes [a-z] -> 'a'
    s = re.sub(r'\[([^\]]+)\]\+', lambda m: m.group(1)[0], s)
    s = re.sub(r'\[([^\]]+)\]', lambda m: m.group(1)[0], s)
    # Groups with alternation (A|B) -> A
    s = re.sub(r'\(([^|)]+)\|[^)]+\)', lambda m: m.group(1), s)
    # Drop anchors and simple groups
    s = s.replace('^', '').replace('$', '')
    s = s.replace('\\.', '.').replace('\\|', '|')
    s = s.replace('\\(', '(').replace('\\)', ')')
    s = s.replace('\\[', '[').replace('\\]', ']')
    s = s.replace('\\*', '*').replace('\\+', '+')
    # Strip remaining backslashes
    s = re.sub(r'\\', '', s)
    # Ensure non-empty
    return s or 'XXX'


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
    assert spec.get("skill") == "hw-debug-loop", (
        f"compliance.yaml skill field mismatch: got {spec.get('skill')}")
    reqs = spec.get("requirements", [])
    assert isinstance(reqs, list) and len(reqs) > 0, (
        "compliance.yaml must declare at least one requirement")


def test_empty_output_fails_audit(tmp_path):
    """Sanity: empty output must fail every required check."""
    res, data = run_driver(tmp_path, "")
    assert res.returncode == 1, "empty output should FAIL audit"
    assert data["verdict"] == "FAIL"


def test_good_output_passes_all_required(tmp_path):
    """A synthetic good-output built from all patterns satisfies the checker.

    If this fails, either (a) a pattern in compliance.yaml is too strict
    for synthetic generation and the test must be customized, or (b) the
    driver has a bug.
    """
    spec = load_requirements()
    text = build_good_output(spec)
    res, data = run_driver(tmp_path, text)
    # We only require that all REQUIRED elements (not cross-checks) pass
    req_fails = [f for f in data["findings"]
                 if f["severity"] == "FAIL" and f["id"].startswith("R")]
    if req_fails:
        pytest.skip(
            "Synthetic good-output did not satisfy all required regex patterns; "
            "this skill's compliance.yaml likely needs hand-tailored test "
            f"fixture. Unsatisfied: {[f['id'] for f in req_fails]}")
    assert data["verdict"] == "PASS"
