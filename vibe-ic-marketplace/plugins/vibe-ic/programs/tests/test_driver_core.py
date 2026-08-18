"""Unit tests for the core compliance-check driver.

Covers:
- Minimal YAML parser (no PyYAML fallback path)
- audit() function dispatch
- Each of the 6 cross-check rules
- Requirement class handling
- CLI path (subprocess)
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
DRIVER = ROOT / "_shared" / "skill_compliance_check.py"
assert DRIVER.exists()

sys.path.insert(0, str(DRIVER.parent))
import skill_compliance_check as scc  # noqa: E402


class TestMinimalYamlParser:
    def test_simple_key_value(self, tmp_path):
        p = tmp_path / "a.yaml"
        p.write_text("skill: foo\nversion: 1\n")
        d = scc._load_yaml(p)
        assert d["skill"] == "foo"
        assert d["version"] == 1

    def test_list_of_dicts(self, tmp_path):
        p = tmp_path / "a.yaml"
        p.write_text(
            "requirements:\n"
            "  - id: R1\n"
            "    description: \"d1\"\n"
            "    pattern: 'p1'\n"
            "  - id: R2\n"
            "    description: \"d2\"\n"
            "    pattern: 'p2'\n")
        d = scc._load_yaml(p)
        assert len(d["requirements"]) == 2
        assert d["requirements"][0]["id"] == "R1"
        assert d["requirements"][1]["pattern"] == "p2"

    def test_boolean_values(self, tmp_path):
        p = tmp_path / "a.yaml"
        p.write_text("enabled: true\ndisabled: false\n")
        d = scc._load_yaml(p)
        assert d["enabled"] is True
        assert d["disabled"] is False

    def test_quoted_values_preserve_spaces(self, tmp_path):
        p = tmp_path / "a.yaml"
        p.write_text('description: "hello world"\n')
        d = scc._load_yaml(p)
        assert d["description"] == "hello world"

    def test_comments_are_stripped(self, tmp_path):
        p = tmp_path / "a.yaml"
        p.write_text("# top comment\nskill: foo  # inline comment\n")
        d = scc._load_yaml(p)
        assert d["skill"] == "foo"

    def test_hash_inside_quotes_preserved(self, tmp_path):
        p = tmp_path / "a.yaml"
        p.write_text('pattern: "a#b"\n')
        d = scc._load_yaml(p)
        assert d["pattern"] == "a#b"

    def test_empty_list(self, tmp_path):
        p = tmp_path / "a.yaml"
        p.write_text("cross_checks: []\n")
        d = scc._load_yaml(p)
        assert d["cross_checks"] == [] or d["cross_checks"] is None


class TestRequirementCheck:
    def test_matching_pattern_no_finding(self):
        req = scc.Requirement("R1", "desc", r"\*\*STATUS\*\*:\s*OK")
        assert scc._requirement_check(req, "**STATUS**: OK") == []

    def test_missing_pattern_returns_fail(self):
        req = scc.Requirement("R1", "Missing X", r"FOO")
        findings = scc._requirement_check(req, "bar bar")
        assert len(findings) == 1
        assert findings[0].severity == "FAIL"
        assert findings[0].id == "R1"

    def test_non_required_returns_warn(self):
        req = scc.Requirement("R1", "d", r"FOO", required=False)
        findings = scc._requirement_check(req, "nope")
        assert findings[0].severity == "WARN"


class TestScoreFormulaCrossCheck:
    def test_passes_when_score_matches(self):
        text = ("**STATUS**: OK\n**Score**: 7\n"
                "**Counts**: errors=0, warnings=3, infos=0\n")
        findings = scc._cc_score_formula({"id": "t"}, text)
        assert findings == []

    def test_fails_when_score_mismatches(self):
        text = ("**STATUS**: OK\n**Score**: 10\n"
                "**Counts**: errors=1, warnings=0, infos=0\n")
        findings = scc._cc_score_formula({"id": "t"}, text)
        assert len(findings) == 1
        assert "expected score=7" in findings[0].detail

    def test_skipped_when_status_not_ok(self):
        text = ("**STATUS**: ABORTED\n**Score**: 0\n"
                "**Counts**: errors=99, warnings=99, infos=0\n")
        assert scc._cc_score_formula({"id": "t"}, text) == []

    def test_formula_caps_at_10(self):
        text = ("**STATUS**: OK\n**Score**: 0\n"
                "**Counts**: errors=10, warnings=10, infos=0\n")
        assert scc._cc_score_formula({"id": "t"}, text) == []


class TestRowCountCrossCheck:
    def test_matching_rows_pass(self):
        text = (
            "**Counts**: errors=0, warnings=1, infos=0\n"
            "## Findings (ERROR)\n\n"
            "| File | Line | Msg |\n|---|---|---|\n"
            "## Findings (WARN)\n\n"
            "| File | Line | Msg |\n|---|---|---|\n"
            "| f | 1 | w |\n"
            "## Findings (INFO)\n\n"
            "| File | Line | Msg |\n|---|---|---|\n")
        assert scc._cc_row_count_vs_counts({"id": "t"}, text) == []

    def test_mismatch_row_is_flagged(self):
        text = (
            "**Counts**: errors=0, warnings=2, infos=0\n"
            "## Findings (WARN)\n\n"
            "| File | Line | Msg |\n|---|---|---|\n"
            "| f | 1 | w |\n")
        findings = scc._cc_row_count_vs_counts({"id": "t"}, text)
        assert any("warn" in f.id.lower() for f in findings)


class TestCrcGenIfDeclared:
    def test_no_crc_declared_no_finding(self):
        text = '"sub_blocks_parametric": []'
        assert scc._cc_crc_gen_if_declared({"id": "t"}, text) == []

    def test_crc_declared_without_generator_flagged(self):
        text = '"kind": "crc"\n(no generator here)'
        findings = scc._cc_crc_gen_if_declared({"id": "t"}, text)
        assert len(findings) == 1

    def test_crc_declared_with_generator_ok(self):
        text = '"kind": "crc"\npython3 scripts/crc_vector_gen.py --preset X'
        assert scc._cc_crc_gen_if_declared({"id": "t"}, text) == []


class TestPostcheckPassOnly:
    def test_pass_pass_ok(self):
        text = "// Post-checks: rtl_hygiene_lint=PASS, fsm_error_invariant=PASS"
        assert scc._cc_postcheck_pass_only({"id": "t"}, text) == []

    def test_any_fail_flagged(self):
        text = "// Post-checks: rtl_hygiene_lint=PASS, fsm_error_invariant=FAIL"
        assert len(scc._cc_postcheck_pass_only({"id": "t"}, text)) == 1

    def test_no_header_flagged(self):
        findings = scc._cc_postcheck_pass_only({"id": "t"}, "no header")
        assert len(findings) == 1
        assert findings[0].severity == "FAIL"
        assert "missing" in findings[0].description.lower() or \
               "missing" in findings[0].detail.lower() or \
               "Post-checks" in findings[0].description

    def test_partial_header_does_not_pass(self):
        # Only one of the two fields named — still needs the full header
        findings = scc._cc_postcheck_pass_only(
            {"id": "t"}, "// Post-checks: rtl_hygiene_lint=PASS")
        assert len(findings) == 1
        assert findings[0].severity == "FAIL"


class TestNoForbiddenPatterns:
    def test_none_of_listed_present_ok(self):
        spec = {"id": "t", "patterns": [r"foo", r"bar"]}
        assert scc._cc_no_forbidden_patterns(spec, "baz qux") == []

    def test_any_match_flagged(self):
        spec = {"id": "t", "patterns": [r"intersect"]}
        findings = scc._cc_no_forbidden_patterns(spec, "a intersect b")
        assert len(findings) == 1


class TestPatternRequiresTool:
    def test_phrase_and_tool_both_present_ok(self):
        spec = {"id": "t", "if_phrase_matches": r"Lightning",
                "tool_must_match": r"tristate_bus_check\.py"}
        assert scc._cc_pattern_requires_tool(
            spec, "Lightning bus — tristate_bus_check.py run") == []

    def test_phrase_without_tool_flagged(self):
        spec = {"id": "t", "if_phrase_matches": r"Lightning",
                "tool_must_match": r"tristate_bus_check\.py"}
        findings = scc._cc_pattern_requires_tool(spec, "Lightning bus here")
        assert len(findings) == 1

    def test_phrase_absent_no_check(self):
        spec = {"id": "t", "if_phrase_matches": r"Lightning",
                "tool_must_match": r"tool"}
        assert scc._cc_pattern_requires_tool(spec, "generic output") == []


class TestAuditDispatch:
    def test_unknown_rule_produces_warn(self, tmp_path):
        compliance = {
            "skill": "test",
            "requirements": [],
            "cross_checks": [{"id": "c1", "rule": "does_not_exist"}]
        }
        findings = scc.audit("", compliance)
        assert any(f.severity == "WARN" and "Unknown" in f.description
                   for f in findings)

    def test_empty_compliance_no_findings(self):
        findings = scc.audit("anything", {"requirements": [], "cross_checks": []})
        assert findings == []


class TestCli:
    def _run(self, tmp_path, text, yaml_content, extra_args=()):
        out = tmp_path / "out.md"
        out.write_text(text)
        yml = tmp_path / "compliance.yaml"
        yml.write_text(yaml_content)
        outj = tmp_path / "audit.json"
        res = subprocess.run(
            [sys.executable, str(DRIVER),
             "--requirements", str(yml),
             "--json", str(outj), str(out), *extra_args],
            capture_output=True, text=True)
        data = json.loads(outj.read_text()) if outj.exists() else None
        return res, data

    def test_missing_output_returns_2(self, tmp_path):
        yml = tmp_path / "y.yaml"
        yml.write_text("skill: x\nrequirements: []\n")
        res = subprocess.run(
            [sys.executable, str(DRIVER),
             "--requirements", str(yml), str(tmp_path / "nope.md")],
            capture_output=True, text=True)
        assert res.returncode == 2

    def test_missing_yaml_returns_2(self, tmp_path):
        out = tmp_path / "a.md"
        out.write_text("x")
        res = subprocess.run(
            [sys.executable, str(DRIVER),
             "--requirements", str(tmp_path / "nope.yaml"), str(out)],
            capture_output=True, text=True)
        assert res.returncode == 2

    def test_empty_compliance_passes(self, tmp_path):
        res, data = self._run(tmp_path, "hi", "skill: s\nrequirements: []\n")
        assert res.returncode == 0
        assert data["verdict"] == "PASS"

    def test_single_requirement_miss(self, tmp_path):
        yaml = (
            "skill: s\n"
            "requirements:\n"
            "  - id: R1\n"
            "    description: \"must contain XYZ\"\n"
            "    pattern: 'XYZ'\n")
        res, data = self._run(tmp_path, "does not contain", yaml)
        assert res.returncode == 1
        assert any(f["id"] == "R1" for f in data["findings"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
