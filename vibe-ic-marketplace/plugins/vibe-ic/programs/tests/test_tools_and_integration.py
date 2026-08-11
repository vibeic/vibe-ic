"""Tests for the maintenance tools + end-to-end integration.

Covers:
- bootstrap_compliance.py helpers (pattern detection, YAML emit)
- gen_compliance_tests.py (pattern_to_satisfier etc.)
- add_compliance_gate.py (idempotency)
- Integration: every one of the 55 skills passes the synthetic-audit pipeline
"""
import hashlib
import shutil
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
# #1029 — these tools WRITE. Every test that runs one must run it against a
# COPY of skills/, never the shipped tree.
#
# Before this, `test_add_gate_is_idempotent` ran add_compliance_gate.py with
# cwd=PLUGIN and no way to redirect it. The tool appended a Compliance-gate
# section to skills/fork-gatekeeper-loop/SKILL.md, the test asserted on the
# SECOND application (correctly a no-op) and passed, and the modification was
# left in the checkout. `gatekeeper-land.sh` runs the targeted tests at line
# 205 and `landing_worktree_is_clean_check.py --expect-fingerprint` at line
# 213 — so a green test run made the very next gate go red, the stamp was
# never written, and pre-push refused. Nothing measured the FIRST application,
# which is why it sat.
# ---------------------------------------------------------------------------
def _seed_skills_copy(tmp_path):
    """Copy the real skills/ tree (SKILL.md + compliance.yaml) into tmp_path.

    Seeded from the real tree, not from a fixture, so the tools are still
    exercised against real content — the fix must not cost us that.
    """
    src = PLUGIN / "skills"
    dst = tmp_path / "skills"
    dst.mkdir()
    for d in sorted(src.iterdir()):
        if not d.is_dir() or not (d / "SKILL.md").exists():
            continue
        (dst / d.name).mkdir()
        shutil.copy2(d / "SKILL.md", dst / d.name / "SKILL.md")
        if (d / "compliance.yaml").exists():
            shutil.copy2(d / "compliance.yaml",
                         dst / d.name / "compliance.yaml")
    assert list(dst.glob("*/SKILL.md")), "seed copied no SKILL.md"
    return dst


def _snapshot(root, pattern):
    """{relative path: md5} — keyed by PATH, not by name.

    The pre-#1029 snapshots were keyed by `md.name`, which is "SKILL.md" for
    every skill, so both dicts collapsed to a single arbitrary entry and the
    comparison covered one file out of ~90.
    """
    return {str(p.relative_to(root)):
            hashlib.md5(p.read_bytes()).hexdigest()
            for p in sorted(root.glob(pattern))}


def _real_tree_snapshot():
    return _snapshot(PLUGIN / "skills", "*/SKILL.md") | \
           _snapshot(PLUGIN / "skills", "*/compliance.yaml")


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
GATE_HEADER = "## Compliance gate (mandatory)"


class TestMaintenanceTools:
    def _run(self, tool, skills_dir):
        res = subprocess.run(
            [sys.executable, str(tool), "--skills-dir", str(skills_dir)],
            capture_output=True, text=True, cwd=str(PLUGIN), timeout=120)
        assert res.returncode == 0, f"{tool.name} exit={res.returncode}\n{res.stderr}"
        return res

    # -- add_compliance_gate ------------------------------------------------
    def test_add_gate_first_application_appends_the_section(self, tmp_path):
        """THE ASSERTION #1029 WAS MISSING.

        test_add_gate_is_idempotent measures the SECOND application, which is
        correctly a no-op — so it is green whether the tool works or does
        nothing at all. This measures the FIRST: on a SKILL.md with no gate,
        one run must append the section, name that skill's own
        compliance.yaml, preserve the existing body, and touch nothing else.
        """
        skills = _seed_skills_copy(tmp_path)
        # Strip the gate section everywhere so the first application has real
        # work to do, and remember the untouched bodies.
        for md in sorted(skills.glob("*/SKILL.md")):
            md.write_text(md.read_text().split(GATE_HEADER)[0].rstrip() + "\n")
        # The tool's own predicate is the substring "Compliance gate"; a file
        # that still mentions it elsewhere is one the tool deliberately skips.
        bodies = {md.parent.name: md.read_text()
                  for md in sorted(skills.glob("*/SKILL.md"))
                  if "Compliance gate" not in md.read_text()}
        skipped = _snapshot(skills, "*/SKILL.md")
        assert len(bodies) > 1, "nothing left to append to — test is vacuous"

        res = self._run(ADD_GATE, skills)

        assert f"Added Compliance gate to {len(bodies)} SKILL.md files." \
            in res.stdout, res.stdout
        for name, body in bodies.items():
            text = (skills / name / "SKILL.md").read_text()
            assert GATE_HEADER in text, f"{name}: gate not appended"
            assert f"skills/{name}/compliance.yaml" in text, (
                f"{name}: gate does not name this skill's compliance.yaml")
            assert text.startswith(body.rstrip()), (
                f"{name}: original body not preserved")
            assert text.count(GATE_HEADER) == 1, f"{name}: gate duplicated"
        # Everything the tool declined to touch is byte-identical.
        after = _snapshot(skills, "*/SKILL.md")
        for rel, digest in skipped.items():
            if Path(rel).parent.name in bodies:
                continue
            assert after[rel] == digest, f"{rel}: skipped file was rewritten"

    def test_add_gate_is_idempotent(self, tmp_path):
        """Running add_compliance_gate twice must not duplicate the section."""
        skills = _seed_skills_copy(tmp_path)
        self._run(ADD_GATE, skills)          # bring every file to gated state
        before = _snapshot(skills, "*/SKILL.md")
        self._run(ADD_GATE, skills)          # the 2nd run is the subject
        after = _snapshot(skills, "*/SKILL.md")
        assert before == after, "add_compliance_gate mutated files on 2nd run"
        assert len(before) > 1, "snapshot collapsed — key by path, not name"

    def test_add_gate_does_not_write_into_the_checkout(self, tmp_path):
        """The regression guard for #1029 itself."""
        before = _real_tree_snapshot()
        self._run(ADD_GATE, _seed_skills_copy(tmp_path))
        assert _real_tree_snapshot() == before, (
            "add_compliance_gate wrote into the shipped skills/ tree")

    # -- bootstrap_compliance ----------------------------------------------
    def test_bootstrap_first_application_creates_the_yaml(self, tmp_path):
        """First-application counterpart for bootstrap: a skill with no
        compliance.yaml must get a loadable one naming that skill."""
        skills = _seed_skills_copy(tmp_path)
        names = sorted(d.name for d in skills.iterdir() if d.is_dir())
        victim = names[0]
        (skills / victim / "compliance.yaml").unlink()
        survivor_before = (skills / names[1] / "compliance.yaml").read_text()

        res = self._run(BOOTSTRAP, skills)

        assert "Created 1 compliance.yaml files." in res.stdout, res.stdout
        made = scc._load_yaml(skills / victim / "compliance.yaml")
        assert made["skill"] == victim
        assert len(made["requirements"]) > 0
        assert (skills / names[1] / "compliance.yaml").read_text() == \
            survivor_before, "bootstrap rewrote an existing compliance.yaml"

    def test_bootstrap_is_idempotent(self, tmp_path):
        """Running bootstrap twice must not duplicate or alter existing files."""
        skills = _seed_skills_copy(tmp_path)
        before = _snapshot(skills, "*/compliance.yaml")
        self._run(BOOTSTRAP, skills)
        after = _snapshot(skills, "*/compliance.yaml")
        assert before == after, "bootstrap mutated existing files"
        assert len(before) > 1, "snapshot collapsed — key by path, not name"

    def test_bootstrap_does_not_write_into_the_checkout(self, tmp_path):
        """The regression guard for #1029's latent second writer."""
        skills = _seed_skills_copy(tmp_path)
        # Make bootstrap have real work to do, so the guard is not vacuous.
        (skills / sorted(d.name for d in skills.iterdir()
                         if d.is_dir())[0] / "compliance.yaml").unlink()
        before = _real_tree_snapshot()
        self._run(BOOTSTRAP, skills)
        assert _real_tree_snapshot() == before, (
            "bootstrap_compliance wrote into the shipped skills/ tree")


# ---------------------------------------------------------------------------
# Merged-plugin schema validation (Wave 82 — two plugins
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
        # vibe-ic/skills/ (split), every merged-in skill must
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
