"""package_invariants_check: the meta-gate for the per-package INVARIANTS.yaml.

TWO DUTIES, AND THE SECOND IS THE POINT.

1. THE LIVE GATE. `test_the_real_repository_conforms` runs the checker over THIS
   repository and requires rc 0. That is the enforcement wiring: this tree is
   the plugin's one declared testpath, it is what `gatekeeper-land.sh::run_pytest`
   runs on every landing, so a package whose INVARIANTS.yaml is missing, stale,
   or violated turns a landing red without a new gate lane being invented.

2. THE DISCRIMINATION PROOFS. Every other test builds a minimal repository,
   breaks exactly ONE property, and requires the checker to go red naming that
   property. A guard never seen to fail has not been shown to check anything,
   and the failure this file must never allow is the one the whole pattern is
   about: a package whose invariant file is DELETED reading as a package with no
   constraints.

The fixtures are real git repositories under `tmp_path` because the checker
computes its population from `git ls-files` -- deliberately, so that an
untracked scratch file cannot enter or leave the population. Faking that with a
directory walk would test a different program.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import package_invariants_check as pic

from _hostpaths import REPO_ROOT

_MIN = pic.MIN_SOURCE_FILES


# ── fixture builder ─────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _mkrepo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "vibe-ic-marketplace").mkdir(parents=True)
    (repo / "vibe-ic-marketplace" / ".keep").write_text("x\n")
    _git(repo.parent, "init", "-q", "repo")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    return repo


def _mkpkg(repo: Path, rel: str, *, n: int = _MIN, body: str = "pass\n") -> Path:
    d = repo / rel
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (d / f"m{i:02d}.py").write_text(body)
    return d


def _declare(pkg: Path, *, package: str, namespace: str = "ns",
             invariants: str | None = None) -> None:
    inv = invariants if invariants is not None else textwrap.dedent(f"""\
        invariants:
          - id: {namespace}.something-true
            statement: it is true
            enforced_by:
              - {package}/m00.py
        """)
    (pkg / pic.FILENAME).write_text(textwrap.dedent(f"""\
        schema: 1
        package: {package}
        namespace: {namespace}
        role: a package that exists for this test
        """) + inv)


def _run(repo: Path) -> tuple[int, dict]:
    """Audit *repo* after staging everything, returning (rc, report)."""
    _git(repo, "add", "-A")
    try:
        rep = pic.audit(repo)
    except pic.NotDetermined as exc:
        return 2, {"not_determined": str(exc), "findings": []}
    return (0 if rep["passed"] else 1), rep


def _codes(rep: dict) -> list[str]:
    return sorted(f["code"] for f in rep["findings"])


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = _mkrepo(tmp_path)
    pkg = _mkpkg(r, "alpha")
    _declare(pkg, package="alpha", namespace="alpha")
    return r


# ── 1. the live gate ────────────────────────────────────────────────────────

@pytest.mark.skipif(REPO_ROOT is None, reason="no source monorepo in this tree")
def test_the_real_repository_conforms():
    """Every code package in THIS repo declares conforming invariants."""
    rep = pic.audit(REPO_ROOT)
    assert rep["passed"], "\n".join(
        f"[{f['code']}] {f['package']}: {f['detail']}" for f in rep["findings"])
    # The audit must not be vacuous: assert it actually looked.
    assert len(rep["packages"]) >= 9, rep["packages"]
    assert rep["stats"]["invariants"] >= 20, rep["stats"]
    assert rep["stats"]["rules"] >= 5, rep["stats"]
    assert rep["stats"]["files_examined"] >= 1000, rep["stats"]


@pytest.mark.skipif(REPO_ROOT is None, reason="no source monorepo in this tree")
def test_the_real_population_does_not_shrink_below_what_was_measured():
    """A narrowed threshold or extension set must not drop packages in silence.

    Measured at the time this landed: exactly these nine directories hold
    MIN_SOURCE_FILES or more tracked source files directly.
    """
    got = set(pic.discover_packages(pic.tracked_files(REPO_ROOT)))
    for expected in ("tools", "tools/ci", "tools/phase1_engine",
                     "vibe-ic-marketplace/plugins/vibe-ic/programs",
                     "vibe-ic-marketplace/plugins/vibe-ic/programs/tests",
                     "vibe-ic-marketplace/plugins/vibe-ic/_shared",
                     "vibe-ic-marketplace/plugins/vibe-ic/benchmark",
                     "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/test",
                     "vibe-ic-marketplace/plugins/vibe-ic/tools/phase1_engine"):
        assert expected in got, f"{expected} left the discovered population"


# ── 2. population: the two directions ───────────────────────────────────────

def test_a_deleted_invariant_file_is_a_failure(repo):
    """THE headline case: missing must never read as "no constraints"."""
    rc, before = _run(repo)
    assert rc == 0, before["findings"]
    (repo / "alpha" / pic.FILENAME).unlink()
    rc, rep = _run(repo)
    assert rc == 1
    assert _codes(rep) == ["P2"]
    assert "NOT a package with no constraints" in rep["findings"][0]["detail"]


def test_a_new_package_must_declare_before_it_is_clean(repo):
    """Growing past the threshold pulls a directory into the population."""
    _mkpkg(repo, "beta")
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["P2"]
    assert rep["findings"][0]["package"] == "beta"


def test_a_directory_below_the_threshold_is_not_a_package(repo):
    """The population is computed, so a small directory is simply not one."""
    _mkpkg(repo, "tiny", n=_MIN - 1)
    rc, rep = _run(repo)
    assert rc == 0, rep["findings"]
    assert "tiny" not in rep["packages"]


def test_a_declaration_outside_the_population_is_a_failure(repo):
    """A stray INVARIANTS.yaml cannot sit unowned in the tree."""
    d = _mkpkg(repo, "tiny", n=2)
    _declare(d, package="tiny", namespace="tiny")
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["P3"]


def test_zero_packages_is_not_determined_and_never_a_pass(tmp_path):
    """The empty-population defect this repo finds in other people's gates."""
    r = _mkrepo(tmp_path)
    (r / "readme.md").write_text("no code here\n")
    rc, rep = _run(r)
    assert rc == 2
    assert "0 code packages discovered" in rep["not_determined"]


def test_no_repository_root_is_not_determined(tmp_path):
    with pytest.raises(pic.NotDetermined) as exc:
        pic.find_repo_root(tmp_path)
    assert "no repository root" in str(exc.value)


def test_the_cli_reports_rc_two_without_claiming_a_pass(tmp_path, capsys):
    """`main` must print a disclosure, not a bare silent zero."""
    lonely = tmp_path / "elsewhere"
    lonely.mkdir()
    rc = pic.main([str(lonely)])
    out = capsys.readouterr().out
    assert rc == 2
    assert "NOT_CHECKED" in out and "rc 2 is not a pass" in out


# ── 3. conformance of the declaration itself ────────────────────────────────

def test_a_declaration_must_name_its_own_location(repo):
    _declare(repo / "alpha", package="somewhere/else", namespace="alpha")
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["C2"]


def test_a_declaration_needs_a_role(repo):
    (repo / "alpha" / pic.FILENAME).write_text(
        "schema: 1\npackage: alpha\nnamespace: alpha\nrole: ''\n"
        "invariants:\n  - id: alpha.x\n    statement: s\n"
        "    enforced_by: [alpha/m00.py]\n")
    rc, rep = _run(repo)
    assert rc == 1 and "C3" in _codes(rep)


def test_a_wrong_schema_version_is_refused(repo):
    (repo / "alpha" / pic.FILENAME).write_text("schema: 2\npackage: alpha\n")
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["C1"]


def test_two_packages_may_not_own_the_same_id(repo):
    b = _mkpkg(repo, "beta")
    _declare(b, package="beta", namespace="beta", invariants=textwrap.dedent("""\
        invariants:
          - id: alpha.something-true
            statement: a rule that already has an owner
            enforced_by:
              - beta/m00.py
        """))
    rc, rep = _run(repo)
    assert rc == 1
    assert any(f["code"] == "C6" and "already owned by alpha" in f["detail"]
               for f in rep["findings"]), rep["findings"]


def test_two_packages_may_not_own_the_same_namespace(repo):
    b = _mkpkg(repo, "beta")
    _declare(b, package="beta", namespace="alpha")
    rc, rep = _run(repo)
    assert rc == 1
    assert any(f["code"] == "C6" and 'namespace "alpha"' in f["detail"]
               for f in rep["findings"]), rep["findings"]


def test_an_id_must_be_prefixed_by_its_owner(repo):
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=textwrap.dedent("""\
        invariants:
          - id: unattributed-rule
            statement: a rule that does not name its owner
            enforced_by:
              - alpha/m00.py
        """))
    rc, rep = _run(repo)
    assert rc == 1 and "C7" in _codes(rep)


def test_an_enforcer_that_does_not_exist_is_a_failure(repo):
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=textwrap.dedent("""\
        invariants:
          - id: alpha.protected-by-nothing
            statement: claims an enforcer that is not there
            enforced_by:
              - alpha/a_program_that_was_deleted.py
        """))
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["C8"]
    assert "not a tracked file" in rep["findings"][0]["detail"]


def test_an_untracked_enforcer_does_not_count(repo):
    """Existing on disk is not enough -- it must be IN the repository."""
    (repo / "alpha" / "local_only.py").write_text("pass\n")
    (repo / ".gitignore").write_text("alpha/local_only.py\n")
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=textwrap.dedent("""\
        invariants:
          - id: alpha.enforced-by-a-local-file
            statement: names a file that only exists on this machine
            enforced_by:
              - alpha/local_only.py
        """))
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["C8"]


def test_an_invariant_needs_a_statement(repo):
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=textwrap.dedent("""\
        invariants:
          - id: alpha.silent
            statement: '   '
            enforced_by:
              - alpha/m00.py
        """))
    rc, rep = _run(repo)
    assert rc == 1 and "C5" in _codes(rep)


# ── 4. the local rules ──────────────────────────────────────────────────────

_FORBID = textwrap.dedent("""\
    invariants:
      - id: alpha.no-marker
        statement: the marker may not appear
        enforced_by:
          - alpha/m00.py
        rule:
          kind: forbid_regex
          applies_to: ["*.py"]
          pattern: 'FORBIDDEN_MARKER'
    """)


def test_a_forbidden_pattern_fails_and_names_its_owner(repo):
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=_FORBID)
    rc, rep = _run(repo)
    assert rc == 0, rep["findings"]
    (repo / "alpha" / "m03.py").write_text("x = 'FORBIDDEN_MARKER'\n")
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["L3"]
    detail = rep["findings"][0]["detail"]
    assert detail.startswith('invariant violated by "alpha": alpha.no-marker')
    assert "alpha/m03.py:1" in detail


def test_a_required_pattern_fails_when_absent(repo):
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=textwrap.dedent("""\
        invariants:
          - id: alpha.needs-marker
            statement: every module must carry the marker
            enforced_by:
              - alpha/m00.py
            rule:
              kind: require_regex
              applies_to: ["*.py"]
              pattern: 'REQUIRED_MARKER'
        """))
    rc, rep = _run(repo)
    assert rc == 1
    assert len(rep["findings"]) == _MIN
    assert all(f["code"] == "L3" for f in rep["findings"])


def test_a_rule_over_an_empty_population_is_a_failure(repo):
    """L2 -- the empty-denominator defect, one directory down."""
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=textwrap.dedent("""\
        invariants:
          - id: alpha.about-nothing
            statement: a rule whose population does not exist
            enforced_by:
              - alpha/m00.py
            rule:
              kind: forbid_regex
              applies_to: ["*.rs"]
              pattern: 'anything'
        """))
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["L2"]
    assert "cannot fail" in rep["findings"][0]["detail"]


def test_an_exemption_suppresses_only_the_file_it_names(repo):
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=_FORBID.replace(
                 "      pattern: 'FORBIDDEN_MARKER'\n",
                 "      pattern: 'FORBIDDEN_MARKER'\n"
                 "      exempt:\n"
                 "        - file: m03.py\n"
                 "          because: this one is deliberate\n"))
    (repo / "alpha" / "m03.py").write_text("x = 'FORBIDDEN_MARKER'\n")
    rc, rep = _run(repo)
    assert rc == 0, rep["findings"]
    (repo / "alpha" / "m04.py").write_text("y = 'FORBIDDEN_MARKER'\n")
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["L3"]
    assert "alpha/m04.py" in rep["findings"][0]["detail"]


def test_a_stale_exemption_must_be_deleted(repo):
    """L4 -- the waiver list can only ever be made shorter by a visible edit."""
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=_FORBID.replace(
                 "      pattern: 'FORBIDDEN_MARKER'\n",
                 "      pattern: 'FORBIDDEN_MARKER'\n"
                 "      exempt:\n"
                 "        - file: m03.py\n"
                 "          because: this one is deliberate\n"))
    rc, rep = _run(repo)          # m03.py never had the marker
    assert rc == 1 and _codes(rep) == ["L4"]
    assert "delete the entry" in rep["findings"][0]["detail"]


def test_an_exemption_needs_a_stated_reason(repo):
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=_FORBID.replace(
                 "      pattern: 'FORBIDDEN_MARKER'\n",
                 "      pattern: 'FORBIDDEN_MARKER'\n"
                 "      exempt:\n"
                 "        - file: m03.py\n"))
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["L1"]
    assert "`file` and `because`" in rep["findings"][0]["detail"]


def test_a_narrowed_exemption_still_fails_the_other_lines(repo):
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=_FORBID.replace(
                 "      pattern: 'FORBIDDEN_MARKER'\n",
                 "      pattern: 'FORBIDDEN_MARKER'\n"
                 "      exempt:\n"
                 "        - file: m03.py\n"
                 "          line_matches: 'in a comment'\n"
                 "          because: documented, not invoked\n"))
    (repo / "alpha" / "m03.py").write_text(
        "# FORBIDDEN_MARKER in a comment\nz = 'FORBIDDEN_MARKER'\n")
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["L3"]
    assert "alpha/m03.py:2" in rep["findings"][0]["detail"]


def test_a_narrowed_exemption_that_matches_nothing_is_stale(repo):
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=_FORBID.replace(
                 "      pattern: 'FORBIDDEN_MARKER'\n",
                 "      pattern: 'FORBIDDEN_MARKER'\n"
                 "      exempt:\n"
                 "        - file: m03.py\n"
                 "          line_matches: 'a form that no longer occurs'\n"
                 "          because: documented, not invoked\n"))
    (repo / "alpha" / "m03.py").write_text("z = 'FORBIDDEN_MARKER'\n")
    rc, rep = _run(repo)
    assert rc == 1 and set(_codes(rep)) == {"L3", "L4"}


def test_a_mirror_rule_catches_drift(repo):
    left = _mkpkg(repo, "left")
    right = _mkpkg(repo, "right")
    _declare(left, package="left", namespace="left",
             invariants=textwrap.dedent("""\
        invariants:
          - id: left.copies-agree
            statement: both copies are byte-identical
            enforced_by:
              - left/m00.py
            rule:
              kind: mirror_of
              package: right
              applies_to: ["*.py"]
        """))
    _declare(right, package="right", namespace="right")
    rc, rep = _run(repo)
    assert rc == 0, rep["findings"]
    (right / "m05.py").write_text("pass  # drifted\n")
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["L3"]
    assert "differs from right/m05.py" in rep["findings"][0]["detail"]


def test_a_mirror_rule_catches_a_missing_counterpart(repo):
    left = _mkpkg(repo, "left")
    right = _mkpkg(repo, "right")
    _declare(left, package="left", namespace="left",
             invariants=textwrap.dedent("""\
        invariants:
          - id: left.copies-agree
            statement: both copies are byte-identical
            enforced_by:
              - left/m00.py
            rule:
              kind: mirror_of
              package: right
              applies_to: ["*.py"]
        """))
    _declare(right, package="right", namespace="right")
    (right / "m05.py").unlink()
    rc, rep = _run(repo)
    assert rc == 1
    assert any("has no counterpart" in f["detail"] for f in rep["findings"])


def test_a_declaration_is_never_its_own_subject(repo):
    """A `because` sentence must not be able to trip its own pattern."""
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=textwrap.dedent("""\
        invariants:
          - id: alpha.no-schema-word
            statement: the word must not appear in yaml files here
            enforced_by:
              - alpha/m00.py
            rule:
              kind: forbid_regex
              applies_to: ["*.yaml", "*.py"]
              pattern: 'schema'
        """))
    rc, rep = _run(repo)
    assert rc == 0, rep["findings"]


def test_an_unknown_rule_kind_is_refused(repo):
    _declare(repo / "alpha", package="alpha", namespace="alpha",
             invariants=textwrap.dedent("""\
        invariants:
          - id: alpha.bad-kind
            statement: s
            enforced_by:
              - alpha/m00.py
            rule:
              kind: eyeball_it
              applies_to: ["*.py"]
        """))
    rc, rep = _run(repo)
    assert rc == 1 and _codes(rep) == ["L1"]
