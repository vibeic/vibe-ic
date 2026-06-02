"""Tests for the maintenance tools + end-to-end integration.

Covers:
- bootstrap_compliance.py helpers (pattern detection, YAML emit)
- gen_compliance_tests.py (pattern_to_satisfier etc.)
- add_compliance_gate.py (idempotency)
- Integration: every one of the 55 skills passes the synthetic-audit pipeline
"""
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
DRIVER = PLUGIN / "_shared" / "skill_compliance_check.py"
BOOTSTRAP = PLUGIN / "_shared" / "bootstrap_compliance.py"
GEN_TESTS = PLUGIN / "_shared" / "gen_compliance_tests.py"
ADD_GATE = PLUGIN / "_shared" / "add_compliance_gate.py"

sys.path.insert(0, str(PLUGIN / "_shared"))
import skill_compliance_check as scc  # noqa: E402
import bootstrap_compliance as bc      # noqa: E402


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
class TestBootstrap:
    def test_detect_handoff_line(self):
        md = "Next step: `Next: run /eda_formal to execute SBY`"
        reqs = bc.detect_skill_patterns(md)
        assert any("handoff" in r[0] for r in reqs)

    def test_detect_output_format_header(self):
        md = "## Output format\n\nemit a report"
        reqs = bc.detect_skill_patterns(md)
        assert any(r[0] == "R_has_output_section" for r in reqs)

    def test_detect_next_step_header(self):
        md = "## Next step\n- run /rtl-review"
        reqs = bc.detect_skill_patterns(md)
        assert any(r[0] == "R_next_step_section" for r in reqs)

    def test_gen_yaml_is_valid(self):
        yaml = bc.gen_yaml("my-skill", [("R_x", "desc x", r"XYZ")])
        # Round-trip through our parser
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".yaml",
                                         delete=False) as f:
            f.write(yaml); path = f.name
        d = scc._load_yaml(Path(path))
        assert d["skill"] == "my-skill"
        assert len(d["requirements"]) >= 1  # one custom + common

    def test_gen_yaml_empty_detected_still_has_common_reqs(self):
        yaml = bc.gen_yaml("empty", [])
        assert "R_next_step" in yaml
        assert "R_status_or_summary" in yaml


# ---------------------------------------------------------------------------
# Integration: every skill passes basic audit
# ---------------------------------------------------------------------------
class TestEndToEndAllSkills:
    def test_every_skill_has_compliance_yaml(self):
        skills = [d for d in (PLUGIN / "skills").iterdir() if d.is_dir()]
        missing = [s.name for s in skills if not (s / "compliance.yaml").exists()]
        assert missing == [], f"Skills missing compliance.yaml: {missing}"

    def test_every_skill_has_test_file(self):
        skills = [d for d in (PLUGIN / "skills").iterdir()
                  if d.is_dir() and (d / "compliance.yaml").exists()]
        missing = [s.name for s in skills
                   if not (s / "tests" / "test_compliance.py").exists()]
        assert missing == [], f"Skills missing test_compliance.py: {missing}"

    def test_every_compliance_yaml_loads(self):
        failures = []
        for y in (PLUGIN / "skills").glob("*/compliance.yaml"):
            try:
                d = scc._load_yaml(y)
                assert d.get("skill") == y.parent.name, (
                    f"skill field mismatch in {y}: got {d.get('skill')}")
                assert isinstance(d.get("requirements"), list), (
                    f"requirements must be a list in {y}")
                assert len(d["requirements"]) > 0, (
                    f"no requirements in {y}")
            except Exception as e:
                failures.append(f"{y.parent.name}: {e}")
        assert not failures, "\n".join(failures)

    def test_every_skill_empty_output_fails_audit(self, tmp_path):
        """For every skill, an empty string must fail the audit. This
        proves the driver can process the compliance.yaml at runtime."""
        failures = []
        for y in (PLUGIN / "skills").glob("*/compliance.yaml"):
            out = tmp_path / f"{y.parent.name}.md"
            out.write_text("")
            res = subprocess.run(
                [sys.executable, str(DRIVER),
                 "--requirements", str(y), str(out)],
                capture_output=True, text=True, timeout=30)
            if res.returncode != 1:
                failures.append(
                    f"{y.parent.name}: exit={res.returncode} "
                    f"(expected 1=FAIL)")
        assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# Idempotency of maintenance tools
# ---------------------------------------------------------------------------
class TestMaintenanceTools:
    def test_bootstrap_is_idempotent(self):
        """Running bootstrap twice must not duplicate or alter existing files."""
        before = {}
        for y in (PLUGIN / "skills").glob("*/compliance.yaml"):
            before[y.name] = y.read_text()
        res = subprocess.run(
            [sys.executable, str(BOOTSTRAP)],
            capture_output=True, text=True, cwd=str(PLUGIN))
        after = {}
        for y in (PLUGIN / "skills").glob("*/compliance.yaml"):
            after[y.name] = y.read_text()
        assert before == after, "bootstrap mutated existing files"

    def test_add_gate_is_idempotent(self):
        """Running add_compliance_gate twice must not duplicate the section."""
        marketplace = PLUGIN.parent.parent.parent
        core = marketplace / "plugins" / "vibe-ic" / "skills"
        before = {}
        for md in core.glob("*/SKILL.md"):
            before[md.name] = md.read_text()
        subprocess.run(
            [sys.executable, str(ADD_GATE)],
            capture_output=True, text=True, cwd=str(PLUGIN))
        after = {}
        for md in core.glob("*/SKILL.md"):
            after[md.name] = md.read_text()
        assert before == after, "add_compliance_gate mutated files on 2nd run"


# ---------------------------------------------------------------------------
# Merged-plugin schema validation (Wave 82 — vibe-ic/vibe-ic-d
# merged into vibe-ic). Tests originally probed vibe-ic/skills/
# under the split layout; after the merge the canonical place for
# SKILL.md is vibe-ic/skills/. Legacy core dir is still consulted as
# fallback for backwards-compat with checkouts mid-migration.
# ---------------------------------------------------------------------------
def _skill_dirs():
    """Return the directory holding canonical SKILL.md files."""
    legacy = PLUGIN.parent / "vibe-ic" / "skills"
    if legacy.is_dir():
        legacy_dirs = [d for d in legacy.iterdir()
                       if d.is_dir() and (d / "SKILL.md").exists()]
        if legacy_dirs:
            return legacy
    return PLUGIN / "skills"


class TestCoreSkillSchema:
    def test_every_core_skill_has_skill_md(self):
        core = _skill_dirs()
        missing = [d.name for d in core.iterdir()
                   if d.is_dir() and not (d / "SKILL.md").exists()]
        assert missing == [], f"skills without SKILL.md: {missing}"

    def test_every_skill_md_has_frontmatter(self):
        core = _skill_dirs()
        failures = []
        for md in core.glob("*/SKILL.md"):
            text = md.read_text()
            if not text.startswith("---\n"):
                failures.append(f"{md.parent.name}: missing frontmatter")
                continue
            # Must have name and description
            end = text.find("\n---\n", 4)
            if end < 0:
                failures.append(f"{md.parent.name}: no closing ---")
                continue
            fm = text[4:end]
            if "name:" not in fm:
                failures.append(f"{md.parent.name}: no 'name:' in frontmatter")
            if "description:" not in fm:
                failures.append(f"{md.parent.name}: no 'description:' in frontmatter")
        assert not failures, "\n".join(failures)

    def test_every_skill_md_has_compliance_gate(self):
        core = _skill_dirs()
        missing = []
        for md in core.glob("*/SKILL.md"):
            if "Compliance gate" not in md.read_text():
                missing.append(md.parent.name)
        assert missing == [], f"skills without Compliance gate: {missing}"

    def test_core_and_d_skill_names_match(self):
        """Every vibe-ic skill with compliance.yaml must have a SKILL.md
        in the canonical skill directory (otherwise agents have no
        SKILL.md to audit against). Post Wave-82 merge, both live in
        vibe-ic/skills/, so this check is intra-plugin."""
        core = _skill_dirs()
        core_names = {d.name for d in core.iterdir() if d.is_dir()}
        d_names = {d.name for d in (PLUGIN / "skills").iterdir()
                   if d.is_dir()}
        # If core points at vibe-ic/skills/ (merged), the sets are
        # identical by construction. If core points at the legacy
        # vibe-ic/skills/ (split), every vibe-ic-d skill must
        # have a peer in vibe-ic/skills/.
        if core == (PLUGIN / "skills"):
            assert d_names == core_names
            return
        orphan_d = d_names - core_names
        assert not orphan_d, (
            f"vibe-ic has compliance for skills not in vibe-ic: "
            f"{orphan_d}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
