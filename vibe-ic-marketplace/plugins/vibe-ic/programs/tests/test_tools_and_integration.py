"""Tests for the maintenance tools + end-to-end integration.

Covers:
- bootstrap_compliance.py helpers (pattern detection, YAML emit)
- gen_compliance_tests.py (shared cases and preservation of existing tests)
- add_compliance_gate.py (first application AND idempotency)
- Integration: declared contracts remain valid and refuse missing evidence
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
sys.path.insert(0, str(PLUGIN / "programs"))
import skill_compliance_check as scc  # noqa: E402
import bootstrap_compliance as bc      # noqa: E402
import skill_authoring as authoring     # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ---------------------------------------------------------------------------
# Write into a COPY, never into the shipped tree (vibe-ic#1029)
# ---------------------------------------------------------------------------
# `add_compliance_gate.py` and `bootstrap_compliance.py` both resolve their
# target from `Path(__file__).resolve().parent.parent` — the plugin directory
# they are SHIPPED in. Invoke them as shipped and they write into the shipped
# `skills/` tree. That is what #1029 measured: a clean `origin/main` checkout,
# `pytest programs/tests/test_tools_and_integration.py` -> 15 passed, and
#
#     git status --porcelain
#      M vibe-ic-marketplace/plugins/vibe-ic/skills/fork-gatekeeper-loop/SKILL.md
#
# `gatekeeper-land.sh` runs this suite at line 205 and then, at line 213, runs
# `landing_worktree_is_clean_check.py --expect-fingerprint` — the gate that
# exists precisely to catch a tree that moved while the gates ran. It went red
# on dirt the gates themselves created, the run removed `.git/gatekeeper-stamp`,
# and `pre-push` then refused the push. The local landing path could not
# complete on a clean checkout.
#
# The fix is NOT to relax that gate or to carve `skills/` out of its scope — the
# gate is right, the test was wrong to write there. Because both tools derive
# every path from the script's own location, seeding
# `<tmp>/plugins/vibe-ic/{_shared,skills}` and running the COPIED script
# redirects them completely: `d_plugin = <tmp>/plugins/vibe-ic`, so
# `core_skills = d_plugin/skills`, which is the copy.


# --- the two keyings, named, so the defect can be RUN and not merely described.
# `_key_by_name` is the vibe-ic#1045 defect preserved as a control. It has one
# caller: the paired guard below, which drives both keyings over the same write
# and asserts the old one is blind to it. Nothing else may use it.
def _key_by_path(root, p):
    return str(p.relative_to(root))


def _key_by_name(root, p):
    return p.name


def _snapshot(root, pattern, key=_key_by_path):
    """Map RELATIVE PATH -> content, and REPORT THE DENOMINATOR.

    Keyed by relative path, not by `p.name`: every one of these files is named
    `SKILL.md` (or `compliance.yaml`), so keying by name collapsed 63 files into
    one dict entry and compared only whichever the glob yielded last
    (vibe-ic#1029, diagnosed in #1045).

    Two things the rekeying alone did not do, and #1045 asks for (both here):

    * the count is PRINTED. "63 files -> 1 entry" was true for years and no
      reader could have seen it, because nothing emitted it. A denominator that
      is never shown cannot be recognised as absurd;
    * a collapse is FATAL for the production key, not merely unlikely. This is
      the assertion that survives a careless refactor back to `p.name` --
      `assert before` does not: a one-entry dict is truthy, which is exactly why
      the collapsed comparison passed.
    """
    files = sorted(root.glob(pattern))
    snap = {key(root, p): p.read_text(errors="replace") for p in files}
    print(f"[denominator] {len(snap)} key(s) from {len(files)} file(s) "
          f"matching {pattern!r} under {root} (key={key.__name__})")
    if key is _key_by_path:
        assert len(snap) == len(files), (
            f"key collision: {len(files)} files collapsed into {len(snap)} "
            f"dict entries, so the comparison would measure a subset and call "
            f"it the whole. Key on the path, not the basename (#1045).")
    return snap


def _skill_count(skills_root):
    """The denominator every skill-wide comparison below must reach."""
    return len([d for d in skills_root.iterdir()
                if d.is_dir() and (d / "SKILL.md").exists()])


#: REGENERABLE, not shipped, and the reason this gate cried wolf.
#:
#: `skills/` carries importable `.py` files, so merely COLLECTING one makes
#: CPython write `__pycache__/*.pyc` beside it — with no tool run and no test
#: having written any CONTENT. Measured: `pytest --collect-only` on a single
#: `skills/**/test_*.py`, executing nothing, takes the tree from 0 `.pyc` to 1.
#: Those bytes are git-ignored, so `git status skills/` stays EMPTY while the
#: digest moves, which is why the failure reads as a phantom.
#:
#: THE PREDICATE IS THE SIBLING GATE'S OWN, not a copy of it. This assertion
#: calls itself the test-side of `suite_write_guard`, whose contract is TRACKED
#: blocking / UNTRACKED blocking / IGNORED advisory-never-blocking. Re-deriving
#: the ignore set here would make the alignment "nearly true": a first draft of
#: this change listed `__pycache__` and `.pytest_cache` only, and would have
#: kept tripping on `.mypy_cache`, `.ruff_cache` and `.hypothesis` — which
#: anyone running ruff or mypy from a root containing the plugin creates — while
#: the gate it mirrors treated them as advisory. Importing the predicate makes
#: the two sets the same set by construction, and picks up `.pyo` as well.
#:
#: Nothing else is excluded: a real shippable file planted in the tree still
#: fails the assertion.




# Recorded at import, asserted at the END of this module. See
# `test_shipped_skills_tree_is_untouched_by_this_module`.


def _authoring_fixture(tmp_path):
    """Two private subjects: ordinary guidance and one real authored contract."""
    plugin = tmp_path / "plugins" / "vibe-ic"
    shutil.copytree(PLUGIN / "_shared", plugin / "_shared")
    shutil.copytree(PLUGIN / "skills" / "hold-fix", plugin / "skills" / "hold-fix")
    (plugin / "skills" / "hold-fix" / "tests" / "test_compliance.py").unlink()
    advice = plugin / "skills" / "local-advice"
    advice.mkdir()
    (advice / "SKILL.md").write_text(
        "---\nname: local-advice\ndescription: Explain a local tradeoff.\n---\n"
        "Explain the available choices using the supplied constraints.\n")
    return plugin


def _footprint(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def _author(plugin, script, *args):
    import json
    import time
    argv = [sys.executable, str(plugin / "_shared" / script), *args]
    before = _footprint(plugin / "skills")
    started = time.monotonic()
    result = subprocess.run(argv, cwd=plugin, capture_output=True, text=True, timeout=30)
    with (plugin.parent / "authoring-calls.jsonl").open("a") as evidence:
        evidence.write(json.dumps({"argv": argv, "rc": result.returncode,
                                   "stdout": result.stdout, "stderr": result.stderr,
                                   "wall_seconds": time.monotonic() - started,
                                   "before": before, "after": _footprint(plugin / "skills")}) + "\n")
    return result


@pytest.mark.parametrize("script", ["bootstrap_compliance.py", "add_compliance_gate.py", "gen_compliance_tests.py"])
def test_ordinary_guidance_does_not_trigger_automatic_authoring(tmp_path, script):
    plugin = _authoring_fixture(tmp_path)
    before = _footprint(plugin / "skills")
    result = _author(plugin, script)
    assert result.returncode == 0, result.stdout + result.stderr
    after = _footprint(plugin / "skills")
    assert after == before, {
        "script": script, "created": sorted(after.keys() - before.keys()),
        "changed": sorted(k for k in before.keys() & after.keys() if before[k] != after[k]),
        "stdout": result.stdout,
    }


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
        yaml = bc.gen_yaml("my-skill", [("R_x", 'describes "x"', r"XYZ")])
        # Round-trip through our parser
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".yaml",
                                         delete=False) as f:
            f.write(yaml); path = f.name
        d = scc._load_yaml(Path(path))
        assert d["skill"] == "my-skill"
        assert [r["id"] for r in d["requirements"]] == ["R_x"]

    def test_gen_yaml_empty_detected_does_not_invent_requirements(self, tmp_path):
        draft = tmp_path / "draft.yaml"
        draft.write_text(bc.gen_yaml("empty", []))
        assert scc._load_yaml(draft)["requirements"] == []


# ---------------------------------------------------------------------------
# Integration: validate declared contracts; guidance needs no generated files
# ---------------------------------------------------------------------------
class TestEndToEndAllSkills:
    def test_declared_contracts_are_available_and_well_formed(self):
        # Guidance needs no contract; authored contracts and concrete references
        # still have to be readable and consumable by the existing engine.
        for skill in (PLUGIN / "skills").iterdir():
            if (skill / "SKILL.md").is_file():
                authoring.validate_skill_contracts(skill)

    def test_plain_guidance_does_not_need_generated_files(self, tmp_path):
        plugin = _authoring_fixture(tmp_path)
        advice = plugin / "skills" / "local-advice"
        before = _footprint(advice)
        authoring.validate_skill_contracts(advice)
        assert _footprint(advice) == before
        assert set(before) == {"SKILL.md"}

    @pytest.mark.parametrize("problem", ["missing-reference", "bad-pattern", "bad-rule", "wrong-skill"])
    def test_invalid_declared_contract_is_refused(self, tmp_path, problem):
        plugin = _authoring_fixture(tmp_path)
        skill = plugin / "skills" / "local-advice"
        md = skill / "SKILL.md"
        md.write_text(md.read_text() + "\nReport contract: [schema](compliance.yaml).\n")
        if problem != "missing-reference":
            import yaml
            spec = {"skill": skill.name, "requirements": [{"id": "R_measurement", "pattern": "measured"}]}
            if problem == "bad-pattern":
                spec["requirements"][0]["pattern"] = "["
            elif problem == "bad-rule":
                spec["cross_checks"] = [{"id": "X_measurement", "rule": "not_a_rule"}]
            else:
                spec["skill"] = "wrong-skill"
            (skill / "compliance.yaml").write_text(yaml.safe_dump(spec))
        with pytest.raises(authoring.ContractError):
            authoring.validate_skill_contracts(skill)
        before = _footprint(plugin / "skills")
        result = _author(plugin, "add_compliance_gate.py", "--skill", "local-advice")
        assert result.returncode == 2, result.stdout + result.stderr
        assert _footprint(plugin / "skills") == before

    def test_every_skill_empty_output_fails_audit(self, tmp_path):
        """For every authored contract, an empty string must fail the audit. This
        proves the driver can process the compliance.yaml at runtime."""
        failures = []
        for y in (PLUGIN / "skills").glob("*/compliance.yaml"):
            out = tmp_path / f"{y.parent.name}.md"
            out.write_text("")
            res = _pr.run(
                [sys.executable, str(DRIVER),
                 "--requirements", str(y), str(out)],
                capture_output=True, text=True)
            if res.returncode != 1:
                failures.append(
                    f"{y.parent.name}: exit={res.returncode} "
                    f"(expected 1=FAIL)")
        assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# Idempotency of maintenance tools
# ---------------------------------------------------------------------------
class TestMaintenanceTools:
    def test_bootstrap_is_idempotent(self, tmp_path):
        plugin = _authoring_fixture(tmp_path)
        result = _author(plugin, "bootstrap_compliance.py", "--skill", "local-advice")
        assert result.returncode == 0, result.stderr
        before = _footprint(plugin / "skills")
        result = _author(plugin, "bootstrap_compliance.py", "--skill", "local-advice", "--skill", "hold-fix")
        assert result.returncode == 0, result.stderr
        assert _footprint(plugin / "skills") == before

    def test_bootstrap_explicitly_writes_only_a_draft(self, tmp_path):
        plugin = _authoring_fixture(tmp_path)
        before = _footprint(plugin / "skills")
        result = _author(plugin, "bootstrap_compliance.py", "--skill", "local-advice")
        assert result.returncode == 0, result.stderr
        after = _footprint(plugin / "skills")
        assert after.keys() - before.keys() == {"local-advice/compliance.draft.yaml"}
        assert all(after[k] == v for k, v in before.items())
        draft = plugin / "skills/local-advice/compliance.draft.yaml"
        assert scc._load_yaml(draft)["requirements"] == []
        for tool in ("add_compliance_gate.py", "gen_compliance_tests.py"):
            refusal = _author(plugin, tool, "--skill", "local-advice")
            assert refusal.returncode == 2, refusal.stdout + refusal.stderr
            assert _footprint(plugin / "skills") == after

    def test_add_gate_first_application_links_existing_contract_only(self, tmp_path):
        plugin = _authoring_fixture(tmp_path)
        skill = plugin / "skills/hold-fix"
        md = skill / "SKILL.md"
        body = "---\nname: hold-fix\ndescription: Inspect the supplied timing evidence.\n---\nInspect hold results.\n"
        md.write_text(body)
        before = _footprint(plugin / "skills")
        result = _author(plugin, "add_compliance_gate.py", "--skill", "hold-fix")
        assert result.returncode == 0, result.stdout + result.stderr
        after = _footprint(plugin / "skills")
        assert before.keys() == after.keys()
        assert {k for k in before if before[k] != after[k]} == {"hold-fix/SKILL.md"}
        assert md.read_text().startswith(body.rstrip())
        assert authoring.referenced_contracts(skill) == [(skill / "compliance.yaml").resolve()]
        # Actual report consumer: its own generated explanatory paragraph is
        # neither timing results nor an auditor receipt, so cannot certify work.
        report = tmp_path / "prose-only.md"
        report.write_text(md.read_text())
        result = subprocess.run([sys.executable, str(DRIVER), "--requirements",
                                 str(skill / "compliance.yaml"), str(report)],
                                capture_output=True, text=True)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "X_eda_log_check" in result.stdout

    def test_add_gate_is_idempotent(self, tmp_path):
        plugin = _authoring_fixture(tmp_path)
        skill = plugin / "skills/hold-fix"
        first = _author(plugin, "add_compliance_gate.py", "--skill", "hold-fix")
        assert first.returncode == 0, first.stderr
        before = _footprint(plugin / "skills")
        second = _author(plugin, "add_compliance_gate.py", "--skill", "hold-fix")
        assert second.returncode == 0, second.stderr
        assert _footprint(plugin / "skills") == before

    def test_basename_key_is_blind_to_a_non_idempotent_write(self, tmp_path):
        # Preserve the real snapshot collision control independently of the
        # authoring tool's internal skip expression or global sweep behavior.
        plugin = _authoring_fixture(tmp_path)
        skills = plugin / "skills"
        every = sorted(skills.glob("*/SKILL.md"))
        victim = every[0]
        before_by_path = _snapshot(skills, "*/SKILL.md")
        before_by_name = _snapshot(skills, "*/SKILL.md", key=_key_by_name)
        assert len(before_by_path) == _skill_count(skills)
        assert len(before_by_name) == 1 and len(every) > 1
        victim.write_text(victim.read_text() + "\nMeasured control write.\n")
        after_by_path = _snapshot(skills, "*/SKILL.md")
        after_by_name = _snapshot(skills, "*/SKILL.md", key=_key_by_name)
        assert before_by_name == after_by_name
        assert before_by_path != after_by_path
        assert {k for k in before_by_path if before_by_path[k] != after_by_path[k]} == {str(victim.relative_to(skills))}

    def test_dangling_reference_refuses_before_authoring(self, tmp_path):
        plugin = _authoring_fixture(tmp_path)
        skill = plugin / "skills/hold-fix"
        md = skill / "SKILL.md"
        md.write_text(md.read_text() + "\nAlso read [contract](../missing/compliance.yaml).\n")
        before = _footprint(plugin / "skills")
        result = _author(plugin, "add_compliance_gate.py", "--skill", "hold-fix")
        assert result.returncode == 2, result.stdout + result.stderr
        assert _footprint(plugin / "skills") == before

    @pytest.mark.parametrize("style", ["handwritten", "edited-generated"])
    def test_generator_preserves_handwritten_tests(self, tmp_path, style):
        plugin = _authoring_fixture(tmp_path)
        target = plugin / "skills/hold-fix/tests/test_compliance.py"
        if style == "handwritten":
            shutil.copy2(Path(__file__), target)
        else:
            original = PLUGIN / "skills/hold-fix/tests/test_compliance.py"
            target.write_text(original.read_text() + '''

def test_receipt_requirement_is_still_declared():
    spec = load_requirements()
    assert any(c.get("rule") == "audit_receipt_evidence"
               for c in spec["cross_checks"]), spec["cross_checks"]
''')
        before = _footprint(plugin / "skills")
        result = _author(plugin, "gen_compliance_tests.py", "--skill", "hold-fix")
        assert result.returncode == 0, result.stderr
        assert _footprint(plugin / "skills") == before
        if style == "edited-generated":
            # The extra regression must survive AND discriminate: boilerplate
            # cases adapt to a removed receipt rule, this authored case refuses.
            import yaml
            contract = plugin / "skills/hold-fix/compliance.yaml"
            for arm in ("intact", "receipt-rule-removed"):
                if arm == "receipt-rule-removed":
                    spec = yaml.safe_load(contract.read_text())
                    spec["cross_checks"] = [c for c in spec["cross_checks"]
                                             if c.get("rule") != "audit_receipt_evidence"]
                    contract.write_text(yaml.safe_dump(spec))
                argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "--import-mode=importlib", f"--basetemp={tmp_path / arm}",
                        f"--junitxml={tmp_path / (arm + '.xml')}",
                        str(target) + "::test_receipt_requirement_is_still_declared"]
                measured = subprocess.run(argv, cwd=plugin, capture_output=True, text=True)
                (tmp_path / f"{arm}.log").write_text(measured.stdout + measured.stderr)
                assert measured.returncode == (0 if arm == "intact" else 1), measured.stdout + measured.stderr

    @pytest.mark.parametrize("skill_name", ["flow-change-acceptance", "hold-fix"])
    def test_shared_wrapper_preserves_legacy_cases_and_outcomes(self, tmp_path, skill_name):
        import ast
        import json
        import xml.etree.ElementTree as ET
        plugin = _authoring_fixture(tmp_path)
        consumer = plugin / "programs/tests/test_pattern_satisfier_2057.py"
        consumer.parent.mkdir(parents=True)
        shutil.copy2(PLUGIN / "programs/tests" / consumer.name, consumer)

        def check_consumer(arm, expected_rc):
            label = f"consumer-{arm}"
            junit = tmp_path / f"{label}.xml"
            argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                    "--import-mode=importlib", f"--basetemp={tmp_path / label}",
                    f"--junitxml={junit}", str(consumer) +
                    "::test_the_generated_tests_still_assert_the_register_both_ways"]
            result = subprocess.run(argv, cwd=plugin, capture_output=True, text=True, timeout=60)
            (tmp_path / f"{label}.log").write_text(result.stdout + result.stderr)
            (tmp_path / f"{label}-command.json").write_text(json.dumps({"argv": argv, "rc": result.returncode}))
            assert result.returncode == expected_rc, result.stdout + result.stderr
            cases = list(ET.parse(junit).iter("testcase"))
            assert len(cases) == 1 and cases[0].find("skipped") is None
            assert (cases[0].find("failure") is not None) == (expected_rc == 1), cases[0].attrib

        skill = plugin / "skills" / skill_name
        if not skill.exists():
            shutil.copytree(PLUGIN / "skills" / skill_name, skill)
        else:
            shutil.copy2(PLUGIN / "skills" / skill_name / "tests/test_compliance.py", skill / "tests/test_compliance.py")
        target = skill / "tests/test_compliance.py"
        observations = []
        original = target.read_bytes()
        for arm in ("legacy", "shared"):
            if arm == "shared":
                # Existing modules remain byte-identical. Create a NEW wrapper
                # only in this private fixture to compare the same pytest IDs.
                before = _footprint(plugin / "skills")
                result = _author(plugin, "gen_compliance_tests.py", "--skill", skill_name)
                assert result.returncode == 0, result.stderr
                assert _footprint(plugin / "skills") == before
                target.unlink()
                before = _footprint(plugin / "skills")
                result = _author(plugin, "gen_compliance_tests.py", "--skill", skill_name)
                assert result.returncode == 0, result.stderr
                after = _footprint(plugin / "skills")
                assert after.keys() - before.keys() == {f"{skill_name}/tests/test_compliance.py"}
                assert all(after[k] == v for k, v in before.items())
                assert len(target.read_bytes()) < len(original)
                result = _author(plugin, "gen_compliance_tests.py", "--skill", skill_name)
                assert result.returncode == 0, result.stderr
                assert _footprint(plugin / "skills") == after
            junit = tmp_path / f"{arm}.xml"
            argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                    "--import-mode=importlib", f"--basetemp={tmp_path / arm}", f"--junitxml={junit}", str(target)]
            result = subprocess.run(argv, cwd=plugin, capture_output=True, text=True)
            (tmp_path / f"{arm}.log").write_text(result.stdout + result.stderr)
            (tmp_path / f"{arm}-command.json").write_text(json.dumps({"argv": argv, "rc": result.returncode}))
            cases = [(n.get("classname"), n.get("name"), [c.tag for c in n if c.tag in {"failure", "error", "skipped"}])
                     for n in ET.parse(junit).iter("testcase")]
            observations.append((result.returncode, cases))
            check_consumer(arm, 0)
        assert observations[0] == observations[1], observations
        assert observations[0][0] == 0 and len(observations[0][1]) == 3, observations

        shared = plugin / "_shared/generated_compliance_support.py"
        original_shared = shared.read_text()
        try:
            for mutation in ("broken-shared-method", "suppressed-register-check",
                             "skip-real-rejection", "xfail-real-rejection"):
                tree = ast.parse(original_shared)
                method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                              and n.name == "test_good_output_passes_all_required")
                if mutation == "broken-shared-method":
                    method.body = [ast.Pass()]
                else:
                    assertion = next(n for n in method.body if isinstance(n, ast.Assert)
                                     and isinstance(n.test, ast.Compare)
                                     and isinstance(n.test.left, ast.Name)
                                     and n.test.left.id == "req_fails")
                    if mutation == "suppressed-register-check":
                        replacement = ast.Pass()
                    else:
                        action = "skip" if mutation == "skip-real-rejection" else "xfail"
                        suppression = ast.parse(f'__import__("pytest").{action}("control: suppress real rejection")').body
                        replacement = ast.If(test=ast.UnaryOp(op=ast.Not(), operand=assertion.test),
                                             body=suppression, orelse=[])
                    method.body[method.body.index(assertion)] = replacement
                shared.write_text(ast.unparse(ast.fix_missing_locations(tree)) + "\n")
                check_consumer(mutation, 1)
        finally:
            shared.write_text(original_shared)



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

    def test_localized_instructions_keep_the_same_contract(self, tmp_path):
        plugin = _authoring_fixture(tmp_path)
        skill = plugin / "skills/hold-fix"
        md = skill / "SKILL.md"
        before = authoring.referenced_contracts(skill)
        md.write_text(md.read_text().replace("Compliance gate", "合規檢查"))
        assert authoring.referenced_contracts(skill) == before
        authoring.validate_skill_contracts(skill)

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


# ---------------------------------------------------------------------------
# The regression guard for vibe-ic#1029, kept LAST on purpose.
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
