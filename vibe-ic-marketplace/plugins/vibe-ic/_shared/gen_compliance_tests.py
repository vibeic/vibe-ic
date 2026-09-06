#!/usr/bin/env python3
"""
Generate a minimal `tests/test_compliance.py` for every skill.

For each skill, the generated test:
  1. Loads the skill's compliance.yaml.
  2. Verifies the YAML parses and has at least one requirement.
  3. Builds a "good" output that satisfies all required patterns (by
     concatenating each pattern as literal text), feeds it to the shared
     driver, and asserts verdict == PASS — or, for a skill named in
     `_shared/synthetic_fixture_limits.py`, asserts that the requirement IDs
     it cannot satisfy are EXACTLY the ones declared there, then xfails with
     the recorded reason (#2050).

Step 4 of this list used to read "for each requirement, removes its satisfying
token ... and asserts the driver flags that requirement as FAIL". No template
this repo has shipped emitted such a test. The claim is removed rather than
left standing: a docstring describing a test that does not exist is the same
unmeasured claim #2048 and #2050 are about.

The generated tests are deterministic: same yaml → same good-output →
same audit outcome.
"""
from pathlib import Path
import sys


TEMPLATE = '''\
"""Auto-generated tests for {skill_name} compliance checking.

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
assert COMPLIANCE.exists(), f"compliance.yaml missing: {{COMPLIANCE}}"
assert DRIVER.exists(), f"driver missing: {{DRIVER}}"

sys.path.insert(0, str(DRIVER.parent))
import skill_compliance_check as scc  # noqa: E402
import synthetic_fixture_limits as LIMITS  # noqa: E402

SKILL_NAME = "{skill_name}"


def load_requirements():
    return scc._load_yaml(COMPLIANCE)


def build_good_output(compliance):
    """Produce text that literally contains a satisfier for every required
    pattern. For simple regex patterns, the pattern text itself (after
    escape cleanup) is often a valid satisfier; we pick a simple default."""
    parts = ["# Auto-built good output\\n"]
    for r in compliance.get("requirements", []) or []:
        pat = r["pattern"]
        # Crude satisfier: strip regex meta, produce a literal that matches
        sat = _pattern_to_satisfier(pat)
        parts.append(f"<!-- sat for {{r['id']}} -->\\n{{sat}}\\n")
    return "\\n".join(parts)


def _pattern_to_satisfier(pat: str) -> str:
    """Turn a regex into a string that contains a match. Very conservative."""
    # Replace common regex constructs with literal text
    import re
    s = pat
    # \\s* -> ' '; \\s+ -> ' '; \\d+ -> '1'; \\w+ -> 'x'
    s = re.sub(r'\\\\s\\*', ' ', s)
    s = re.sub(r'\\\\s\\+', ' ', s)
    s = re.sub(r'\\\\d\\+', '1', s)
    s = re.sub(r'\\\\d', '1', s)
    s = re.sub(r'\\\\w\\+', 'x', s)
    s = re.sub(r'\\\\w', 'x', s)
    # Character classes [a-z] -> 'a'
    s = re.sub(r'\\[([^\\]]+)\\]\\+', lambda m: m.group(1)[0], s)
    s = re.sub(r'\\[([^\\]]+)\\]', lambda m: m.group(1)[0], s)
    # Groups with alternation (A|B) -> A
    s = re.sub(r'\\(([^|)]+)\\|[^)]+\\)', lambda m: m.group(1), s)
    # Drop anchors and simple groups
    s = s.replace('^', '').replace('$', '')
    s = s.replace('\\\\.', '.').replace('\\\\|', '|')
    s = s.replace('\\\\(', '(').replace('\\\\)', ')')
    s = s.replace('\\\\[', '[').replace('\\\\]', ']')
    s = s.replace('\\\\*', '*').replace('\\\\+', '+')
    # Strip remaining backslashes
    s = re.sub(r'\\\\', '', s)
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
    assert spec.get("skill") == "{skill_name}", (
        f"compliance.yaml skill field mismatch: got {{spec.get('skill')}}")
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

    #2050 — THIS TEST USED TO SKIP BEFORE ITS ASSERT. When the synthetic
    document failed any required pattern it called `pytest.skip()`, so on 53
    of the 69 skills that ship this file the assert below never ran and the
    suite still reported green. That is how #2048 survived: the acceptance
    command in that issue gave byte-identical node-id sets on both arms.

    The blanket skip is replaced by a NAMED list, per skill, of the exact
    requirement IDs the generator cannot satisfy — and the list is checked
    both ways. If the measured set differs from the declared set in EITHER
    direction the test FAILS and says which way, so a pattern that quietly
    becomes unreachable cannot hide and a repaired one cannot be left on the
    list forever. A skill absent from the list asserts PASS outright.
    """
    spec = load_requirements()
    text = build_good_output(spec)
    res, data = run_driver(tmp_path, text)
    # We only require that all REQUIRED elements (not cross-checks) pass
    req_fails = sorted(f["id"] for f in data["findings"]
                       if f["severity"] == "FAIL" and f["id"].startswith("R"))
    declared = sorted(LIMITS.SYNTHETIC_FIXTURE_LIMITATIONS.get(SKILL_NAME, ()))

    assert req_fails == declared, (
        f"{{SKILL_NAME}}: the named synthetic-fixture limitation list in "
        "_shared/synthetic_fixture_limits.py no longer matches what is "
        f"measured. declared={{declared}} measured={{req_fails}}. "
        "If the measured set GREW, a required pattern just became unreachable "
        "for the generator — fix the pattern or the generator, do not extend "
        "the list to silence this. If it SHRANK, delete the repaired IDs from "
        "the list; that is the list getting shorter, which is the point.")

    if declared:
        pytest.xfail(LIMITS.reason_for(SKILL_NAME))
    assert data["verdict"] == "PASS"
'''


def main():
    plugins = Path(__file__).resolve().parent.parent
    # In the unified plugin layout, skills are directly under plugin root
    made = 0
    for yaml_file in plugins.glob('skills/*/compliance.yaml'):
        skill_dir = yaml_file.parent
        skill_name = skill_dir.name
        tests_dir = skill_dir / 'tests'
        tests_dir.mkdir(exist_ok=True)
        target = tests_dir / 'test_compliance.py'
        # Don't overwrite hand-written tests
        if target.exists() and 'Auto-generated' not in target.read_text()[:200]:
            print(f"SKIP (hand-written): {target.relative_to(plugins)}")
            continue
        target.write_text(TEMPLATE.format(skill_name=skill_name))
        made += 1
        print(f"WROTE: {target.relative_to(plugins)}")
    print(f"\nGenerated {made} test files.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
