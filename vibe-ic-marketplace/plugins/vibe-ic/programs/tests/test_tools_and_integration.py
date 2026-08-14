"""Tests for the maintenance tools + end-to-end integration.

Covers:
- bootstrap_compliance.py helpers (pattern detection, YAML emit)
- gen_compliance_tests.py (pattern_to_satisfier etc.)
- add_compliance_gate.py (first application AND idempotency)
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
sys.path.insert(0, str(PLUGIN / "programs"))
import skill_compliance_check as scc  # noqa: E402
import suite_write_guard as _swg  # noqa: E402
import bootstrap_compliance as bc      # noqa: E402


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
def _seed_plugin_copy(tmp_path, *scripts):
    """Seed a throwaway plugin tree from the real one. Returns its plugin dir."""
    plugin = tmp_path / "plugins" / "vibe-ic"
    (plugin / "_shared").mkdir(parents=True)
    for name in scripts:
        shutil.copy2(PLUGIN / "_shared" / name, plugin / "_shared" / name)
    shutil.copytree(PLUGIN / "skills", plugin / "skills")
    return plugin


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
_is_regenerable = _swg._is_cache_noise


def _digest_tree(root):
    """md5 over (relative path, bytes) of every SHIPPABLE file under `root`."""
    h = hashlib.md5()
    for p in sorted(q for q in root.rglob("*") if q.is_file()):
        rel = p.relative_to(root)
        if _is_regenerable(str(rel)):
            continue
        h.update(str(p.relative_to(root)).encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


# Recorded at import, asserted at the END of this module. See
# `test_shipped_skills_tree_is_untouched_by_this_module`.
_SHIPPED_SKILLS_MD5_AT_IMPORT = _digest_tree(PLUGIN / "skills")


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
    def test_bootstrap_is_idempotent(self, tmp_path):
        """Running bootstrap twice must not duplicate or alter existing files."""
        plugin = _seed_plugin_copy(tmp_path, "bootstrap_compliance.py")
        skills = plugin / "skills"
        before = _snapshot(skills, "*/compliance.yaml")
        # Not `assert before`: the collapsed dict was truthy too. The claim is
        # "every skill was compared", so the denominator is asserted against the
        # skill count, and it is in the message when it is not met.
        assert len(before) == _skill_count(skills), (
            f"compared {len(before)} compliance.yaml, expected one per skill "
            f"({_skill_count(skills)}) — the comparison is not skill-wide")
        res = subprocess.run(
            [sys.executable, str(plugin / "_shared" / "bootstrap_compliance.py")],
            capture_output=True, text=True, cwd=str(plugin))
        assert res.returncode == 0, res.stderr
        after = _snapshot(skills, "*/compliance.yaml")
        assert before == after, "bootstrap mutated existing files"

    def test_bootstrap_writes_the_missing_compliance_yaml(self, tmp_path):
        """The FIRST application. `test_bootstrap_is_idempotent` cannot see it:
        every shipped skill already has a compliance.yaml, so both runs are
        no-ops and the assertion holds against a tool that does nothing."""
        plugin = _seed_plugin_copy(tmp_path, "bootstrap_compliance.py")
        victim = sorted((plugin / "skills").glob("*/compliance.yaml"))[0]
        name = victim.parent.name
        victim.unlink()
        res = subprocess.run(
            [sys.executable, str(plugin / "_shared" / "bootstrap_compliance.py")],
            capture_output=True, text=True, cwd=str(plugin))
        assert res.returncode == 0, res.stderr
        assert victim.exists(), (
            f"bootstrap did NOT create skills/{name}/compliance.yaml on first "
            f"application. stdout:\n{res.stdout}")
        assert f"WROTE: skills/{name}/compliance.yaml" in res.stdout

    def test_add_gate_first_application_appends_the_section(self, tmp_path):
        """The FIRST application — the case whose absence let #1029 sit.

        `test_add_gate_is_idempotent` measures the run AFTER the section is
        already present, which is a no-op for a correct tool and equally a
        no-op for a tool that does nothing at all. Nothing measured the run
        that has work to do.
        """
        plugin = _seed_plugin_copy(tmp_path, "add_compliance_gate.py")
        script = plugin / "_shared" / "add_compliance_gate.py"

        # Strip the gate off one COPIED skill so the first application always
        # has work, rather than depending on the shipped tree still carrying a
        # gate-less skill (today exactly one does: fork-gatekeeper-loop).
        victim = sorted((plugin / "skills").glob("*/SKILL.md"))[0]
        name = victim.parent.name
        base = victim.read_text(errors="replace").split(
            "## Compliance gate (mandatory)")[0].rstrip() + "\n"
        assert "Compliance gate" not in base, (
            f"{name}/SKILL.md names the gate outside the appended section; "
            "the first-application probe cannot be seeded from it")
        victim.write_text(base)
        untouched_before = _snapshot(plugin / "skills", "*/SKILL.md")

        res = subprocess.run([sys.executable, str(script)],
                             capture_output=True, text=True, cwd=str(plugin))
        assert res.returncode == 0, res.stderr

        got = victim.read_text(errors="replace")
        assert "## Compliance gate (mandatory)" in got, (
            "add_compliance_gate did NOT append the section on FIRST "
            f"application to skills/{name}/SKILL.md. stdout:\n{res.stdout}")
        assert got.startswith(base.rstrip()), "the prior body was not preserved"
        assert f"plugins/vibe-ic/skills/{name}/compliance.yaml" in got, (
            "the appended section did not interpolate the skill name")
        assert f"UPDATED: plugins/vibe-ic/skills/{name}/SKILL.md" in res.stdout

        # ...and it touched EXACTLY the files that needed it, no others.
        need = {rel for rel, text in untouched_before.items()
                if "Compliance gate" not in text}
        assert str(victim.relative_to(plugin / "skills")) in need
        after = _snapshot(plugin / "skills", "*/SKILL.md")
        changed = {k for k in after if after[k] != untouched_before[k]}
        assert changed == need, (
            f"add_compliance_gate rewrote {changed - need} that already had "
            f"the section, and skipped {need - changed} that did not")

    def test_add_gate_is_idempotent(self, tmp_path):
        """Running add_compliance_gate twice must not duplicate the section."""
        plugin = _seed_plugin_copy(tmp_path, "add_compliance_gate.py")
        script = plugin / "_shared" / "add_compliance_gate.py"
        skills = plugin / "skills"
        # Bring the copy to the fully-gated state first, so the second run is
        # the one under measurement.
        first = subprocess.run([sys.executable, str(script)],
                               capture_output=True, text=True, cwd=str(plugin))
        assert first.returncode == 0, first.stderr
        before = _snapshot(skills, "*/SKILL.md")
        # The denominator, asserted and reported. `assert before` passed for
        # years against a dict of ONE entry (#1045); one entry is truthy, and a
        # comparison of one arbitrary file out of 63 is what let #1029 sit.
        assert len(before) == _skill_count(skills), (
            f"compared {len(before)} SKILL.md, expected one per skill "
            f"({_skill_count(skills)}) — the comparison is not skill-wide")
        second = subprocess.run([sys.executable, str(script)],
                                capture_output=True, text=True, cwd=str(plugin))
        assert second.returncode == 0, second.stderr
        after = _snapshot(skills, "*/SKILL.md")
        assert before == after, "add_compliance_gate mutated files on 2nd run"
        assert "Added Compliance gate to 0 SKILL.md files." in second.stdout

    def test_basename_key_is_blind_to_a_non_idempotent_write(self, tmp_path):
        """The PAIRED GUARD for #1045: the control that proves the fix is a fix.

        `test_add_gate_is_idempotent` above is green under BOTH keyings — the
        tool is idempotent, so `before == after` holds whether the dict holds 63
        entries or 1. A green test therefore says nothing about the key, and
        nothing in this suite reddened when the key was reverted (measured: the
        two idempotency tests passed under `p.name`). So the rekeying that
        #1046 landed had no guard, and the next careless refactor restores
        #1045 silently.

        This test supplies the missing evidence by making the operation
        genuinely NON-idempotent for exactly ONE skill -- deliberately NOT the
        one the basename key would have retained -- and driving both keyings
        over the same write:

            old key (`p.name`)  -> before == after   BLIND, the defect
            new key (path)      -> before != after   CAUGHT, the fix

        Revert `_snapshot`'s key to `p.name` and this test dies on the second
        assertion, which is the property `test_add_gate_is_idempotent` cannot
        have: it is the only place where the two keyings disagree.
        """
        plugin = _seed_plugin_copy(tmp_path, "add_compliance_gate.py")
        script = plugin / "_shared" / "add_compliance_gate.py"
        skills = plugin / "skills"
        assert subprocess.run([sys.executable, str(script)], cwd=str(plugin),
                              capture_output=True, text=True).returncode == 0

        # The basename dict keeps whichever file the glob yields LAST, so the
        # single entry it compares is the LAST skill in sorted order. Mutate a
        # different one -- otherwise the old key would catch it by luck and the
        # control would prove nothing.
        every = sorted(skills.glob("*/SKILL.md"))
        assert len(every) > 1, "one skill cannot demonstrate a key collision"
        old_key_would_compare = every[-1]
        victim = every[0]
        assert victim != old_key_would_compare
        assert victim.name == old_key_would_compare.name == "SKILL.md", (
            "the collision premise no longer holds: these files no longer "
            "share a basename, so this control has nothing to demonstrate")

        # Make the OPERATION non-idempotent, for that one skill only: defeat
        # its already-applied skip so it re-appends the section every run.
        src = script.read_text()
        guard = "if 'Compliance gate' in content:"
        assert guard in src, (
            "add_compliance_gate.py no longer carries the skip this control "
            "subverts; re-derive the non-idempotent variant before trusting it")
        script.write_text(src.replace(
            guard,
            f"if 'Compliance gate' in content "
            f"and md.parent.name != {victim.parent.name!r}:"))

        before_by_path = _snapshot(skills, "*/SKILL.md")
        before_by_name = _snapshot(skills, "*/SKILL.md", key=_key_by_name)
        assert len(before_by_path) == _skill_count(skills)
        assert len(before_by_name) == 1, (
            "the basename key no longer collapses; the defect being guarded "
            "against is not reproducible and this control is vacuous")

        res = subprocess.run([sys.executable, str(script)], cwd=str(plugin),
                             capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        assert f"UPDATED: plugins/vibe-ic/skills/{victim.parent.name}/SKILL.md" \
            in res.stdout, "the seeded non-idempotent write did not happen"

        after_by_path = _snapshot(skills, "*/SKILL.md")
        after_by_name = _snapshot(skills, "*/SKILL.md", key=_key_by_name)

        # THE CONTROL, both halves.
        assert before_by_name == after_by_name, (
            "expected the basename key to be blind here; if it now sees the "
            "write, the victim was chosen wrong and the comparison below "
            "proves nothing")
        assert before_by_path != after_by_path, (
            "the path key MISSED a non-idempotent write to "
            f"skills/{victim.parent.name}/SKILL.md -- the same blindness "
            "#1045 describes")

        changed = {k for k in after_by_path
                   if after_by_path[k] != before_by_path[k]}
        assert changed == {str(victim.relative_to(skills))}, (
            f"expected exactly the seeded skill to move, got {sorted(changed)}")


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


# ---------------------------------------------------------------------------
# The regression guard for vibe-ic#1029, kept LAST on purpose.
# ---------------------------------------------------------------------------
def test_shipped_skills_tree_is_untouched_by_this_session():
    """No test in this SESSION may leave a byte of `skills/` different.

    SCOPE — the name used to say "by this module", which was module-scoped
    prose over a session-scoped mechanism, and it cost a bisection to find
    that out. `_SHIPPED_SKILLS_MD5_AT_IMPORT` is captured when THIS FILE IS
    IMPORTED, and pytest imports every selected module during collection
    before running anything. So the window this assertion covers is:

        every test in the session that runs before this one,
        PLUS every module collected after this one, at import time.

    A module collected later that writes at import time is inside the window
    even though not one of its tests has run. That is not a quirk to work
    around — it is why this catches things `-k` and single-file runs cannot.

    Against the pre-fix file it goes RED: the maintenance-tool tests ran
    `add_compliance_gate.py` as shipped and it appended a section to
    `skills/fork-gatekeeper-loop/SKILL.md`. That modification is what made
    `gatekeeper-land.sh` line 213 fail and the landing stamp never get written.

    This assertion is the test-side of the gate; it does not replace
    `landing_worktree_is_clean_check.py`, which still owns the whole tree.
    """
    assert _digest_tree(PLUGIN / "skills") == _SHIPPED_SKILLS_MD5_AT_IMPORT, (
        "a test in this SESSION — not necessarily in this module — wrote into "
        "the SHIPPED skills/ tree. Run the tool against a copy; see "
        "_seed_plugin_copy(). If the diff is a `__pycache__/*.pyc`, the writer "
        "is an IMPORT of a shipped `skills/**/programs/*.py`, not a tool: set "
        "`sys.dont_write_bytecode` around the `exec_module` call. That case is "
        "invisible to git, `git add -A` and suite_write_guard (all of which "
        "skip it as regenerable), so this digest is the only thing that sees "
        "it — which is why it presents with no obvious author.")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
