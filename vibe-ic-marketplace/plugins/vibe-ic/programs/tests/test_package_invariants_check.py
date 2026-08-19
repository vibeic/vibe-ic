"""Tests for package_invariants_check — the per-package invariant declaration.

TWO POPULATIONS, ON PURPOSE.

The SYNTHETIC half builds throwaway git repositories and drives each named
failure. It has to be synthetic: this repository is (by the gate's own design)
clean, so there is no VIOLATED, ORPHANED or MISPLACED instance in it to read.

The REAL half drives the gate against THIS checkout through `_hostpaths.repo_path`
and asserts the two properties a fixture cannot vouch for — that the derived
package set is the real one, and that removing a real declaration from the real
index is seen. A change whose tests are all fixtures authored alongside it
cannot distinguish itself from its own absence (vibe-ic#400).

Every mutation below is applied to a COPY. Nothing here writes to the checkout.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _hostpaths import repo_path

_PROGRAMS = Path(__file__).resolve().parents[1]
_GATE = _PROGRAMS / "package_invariants_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("package_invariants_check", _GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pic = _load()


# ---------------------------------------------------------------------------
# synthetic repositories
# ---------------------------------------------------------------------------

_GOOD_DECL = """\
package: pkg
purpose: a synthetic package
owns: ["*.py"]
tests:
  root: pkg/tests
  collected_by: run_all.sh
  collected_by_kind: named
invariants:
  - id: I_no_forbidden_call
    statement: no forbidden_call() here
    rule: forbid_regex
    pattern: 'forbidden_call\\('
    applies_to: ["*.py"]
    severity: BLOCKING
    why: a synthetic rule with a real subject
"""


def _repo(tmp_path, *, decl=_GOOD_DECL, source_lines=None, extra=None,
          n_sources=4, name="repo"):
    """A throwaway git repo holding one package `pkg/` and a runner."""
    root = tmp_path / name
    (root / "pkg" / "tests").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for i in range(n_sources):
        (root / "pkg" / f"mod{i}.py").write_text(
            (source_lines or "print('ok')\n"))
    (root / "pkg" / "tests" / "test_pkg.py").write_text("def test_x():\n    pass\n")
    (root / "run_all.sh").write_text("#!/bin/sh\npytest pkg/tests\n")
    if decl is not None:
        (root / "pkg" / "INVARIANTS.yaml").write_text(decl)
    for rel, text in (extra or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def _run(root, *args):
    """Drive the gate as a SUBPROCESS, so the exit code is the real one."""
    proc = subprocess.run(
        [sys.executable, str(_GATE), "--root", str(root), *args],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    return proc.returncode, proc.stdout


def test_a_clean_package_passes_and_discloses_its_denominator(tmp_path):
    rc, out = _run(_repo(tmp_path))
    assert rc == 0, out
    assert "PASS" in out
    # A pass that does not say how much it read is the #447 defect.
    assert "1 source package(s)" in out
    assert "1 invariant(s)" in out
    assert "4 file selection(s)" in out


def test_violated_fires_and_names_the_file_and_line(tmp_path):
    root = _repo(tmp_path, source_lines="x = 1\nforbidden_call()\n")
    rc, out = _run(root)
    assert rc == 1, out
    assert "[VIOLATED]" in out
    assert "I_no_forbidden_call" in out
    assert "mod0.py:2" in out
    # The statement a human reads must travel with the failure.
    assert "no forbidden_call() here" in out


def test_missing_fires_when_a_package_declares_nothing(tmp_path):
    rc, out = _run(_repo(tmp_path, decl=None))
    assert rc == 1, out
    assert "[MISSING]" in out
    assert "pkg/INVARIANTS.yaml" in out


def test_orphaned_fires_when_a_declaration_binds_nothing(tmp_path):
    root = _repo(tmp_path, extra={"not_a_pkg/INVARIANTS.yaml": _GOOD_DECL})
    rc, out = _run(root)
    assert rc == 1, out
    assert "[ORPHANED]" in out
    assert "not_a_pkg/INVARIANTS.yaml" in out


def test_misplaced_fires_when_the_declaration_names_another_tree(tmp_path):
    rc, out = _run(_repo(tmp_path, decl=_GOOD_DECL.replace(
        "package: pkg\n", "package: some/other/tree\n")))
    assert rc == 1, out
    assert "[MISPLACED]" in out


def test_no_invariants_fires_on_an_emptied_declaration(tmp_path):
    """Emptying the list must not read as 'this package is unconstrained'."""
    rc, out = _run(_repo(tmp_path, decl=_GOOD_DECL.split("invariants:")[0]
                         + "invariants: []\n"))
    assert rc == 1, out
    assert "[NO_INVARIANTS]" in out


def test_zero_denominator_fires_on_a_rule_with_no_subject(tmp_path):
    rc, out = _run(_repo(tmp_path, decl=_GOOD_DECL.replace(
        'applies_to: ["*.py"]', 'applies_to: ["*.rs"]')))
    assert rc == 1, out
    assert "[ZERO_DENOMINATOR]" in out


def test_an_invariant_that_selects_nothing_at_all_fails_rather_than_skipping(tmp_path):
    """An unevaluated rule must not read as a rule that held."""
    decl = _GOOD_DECL.replace('    applies_to: ["*.py"]\n', "")
    rc, out = _run(_repo(tmp_path, decl=decl))
    assert rc == 1, out
    assert "[SCHEMA]" in out
    assert "missing `applies_to:`" in out


def test_undeclared_skip_fires_when_tests_are_dropped_without_a_reason(tmp_path):
    decl = _GOOD_DECL.replace(
        "  root: pkg/tests\n  collected_by: run_all.sh\n  collected_by_kind: named\n",
        "  root: NONE\n")
    rc, out = _run(_repo(tmp_path, decl=decl))
    assert rc == 1, out
    assert "[UNDECLARED_SKIP]" in out


def test_a_declared_reason_makes_the_absence_of_tests_acceptable(tmp_path):
    decl = _GOOD_DECL.replace(
        "  root: pkg/tests\n  collected_by: run_all.sh\n  collected_by_kind: named\n",
        "  root: NONE\n  reason: drives a live network service; no offline fixture\n")
    rc, out = _run(_repo(tmp_path, decl=decl))
    assert rc == 0, out


def test_tests_unnamed_fires_when_the_runner_never_names_the_tree(tmp_path):
    root = _repo(tmp_path)
    (root / "run_all.sh").write_text("#!/bin/sh\npytest somewhere/else\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    rc, out = _run(root)
    assert rc == 1, out
    assert "[TESTS_UNNAMED]" in out


def test_a_tree_named_only_in_a_comment_does_not_count(tmp_path):
    """vibe-ic#1391 exactly: prose in a checklist is not automation."""
    root = _repo(tmp_path)
    (root / "run_all.sh").write_text(
        "#!/bin/sh\n# remember to run pkg/tests by hand\npytest other\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    rc, out = _run(root)
    assert rc == 1, out
    assert "[TESTS_UNNAMED]" in out


def test_require_regex_fires_on_the_file_that_lacks_it(tmp_path):
    decl = _GOOD_DECL.replace("rule: forbid_regex", "rule: require_regex")
    rc, out = _run(_repo(tmp_path, decl=decl))
    assert rc == 1, out
    assert "[VIOLATED]" in out
    assert "does not carry the required pattern" in out


def test_paired_regex_fires_only_when_the_trigger_is_present(tmp_path):
    decl = (_GOOD_DECL.replace("rule: forbid_regex", "rule: paired_regex")
            .replace("    applies_to:", "    requires: 'with_a_deadline'\n    applies_to:"))
    # trigger absent everywhere -> nothing to pair, so it holds
    rc, out = _run(_repo(tmp_path, decl=decl))
    assert rc == 0, out
    # trigger present without its pair -> fires
    rc, out = _run(_repo(tmp_path, decl=decl, name="unpaired",
                         source_lines="forbidden_call()\n"))
    assert rc == 1, out
    assert "triggers the pattern without carrying what it requires" in out
    # trigger present WITH its pair -> holds again
    rc, out = _run(_repo(tmp_path, decl=decl, name="paired",
                         source_lines="forbidden_call(with_a_deadline)\n"))
    assert rc == 0, out


def test_a_negated_glob_narrows_the_selection_not_the_pattern(tmp_path):
    decl = _GOOD_DECL.replace('applies_to: ["*.py"]',
                              'applies_to: ["*.py", "!mod0.py"]')
    root = _repo(tmp_path, decl=decl, source_lines="print('ok')\n")
    (root / "pkg" / "mod0.py").write_text("forbidden_call()\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    rc, out = _run(root)
    assert rc == 0, out
    assert "3 file selection(s)" in out, "the exclusion must leave the denominator"


def test_an_empty_tree_refuses_rather_than_passing(tmp_path):
    """A gate that read nothing must not exit 0 (vibe-ic#564)."""
    root = tmp_path / "empty"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    rc, out = _run(root)
    assert rc == 2, out
    assert "NOT DETERMINED" in out
    assert "0 source package(s)" in out


# ---------------------------------------------------------------------------
# the real checkout
# ---------------------------------------------------------------------------

_REPO_ROOT = repo_path()


def test_the_real_repo_declares_every_package_it_derives():
    """Drives the gate on THIS checkout. Not a fixture — the tree itself."""
    rc, out = _run(_REPO_ROOT)
    assert rc == 0, out
    assert "PASS" in out


def test_discovery_finds_the_real_packages_and_excludes_the_test_trees():
    tracked = pic._tracked_files(_REPO_ROOT)
    assert len(tracked) > 1000, "the real tracked tree should be large"
    pkgs = pic.discover_packages(tracked, 4)
    assert len(pkgs) >= 5
    plugin = "vibe-ic-marketplace/plugins/vibe-ic"
    assert f"{plugin}/programs" in pkgs
    assert "tools/ci" in pkgs
    # The biggest directory in the repo is a TEST root and must not be a package.
    assert f"{plugin}/programs/tests" not in pkgs
    assert not any("/tests" in p or "/fixtures/" in p for p in pkgs)


def test_deleting_a_real_declaration_is_seen(tmp_path):
    """DELETE one, and the gate must fail — a missing invariant is not 'no rules'.

    Run against a COPY of the real checkout, so the real one is untouched.
    """
    victim = "tools/ci/INVARIANTS.yaml"
    assert (_REPO_ROOT / victim).is_file(), "fixture assumption: the file is there"
    copy = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", "--depth", "1",
                    "file://" + str(_REPO_ROOT), str(copy)], check=True)
    if not (copy / victim).is_file():
        pytest.skip(f"{victim} is not committed in this checkout yet")
    rc, out = _run(copy)
    assert rc == 0, f"the copy must start clean:\n{out}"
    subprocess.run(["git", "rm", "-q", victim], cwd=copy, check=True)
    rc, out = _run(copy)
    assert rc == 1, out
    assert "[MISSING]" in out
    assert victim in out


def test_the_derivation_never_reads_the_declarations():
    """Discovery must not consult INVARIANTS.yaml — else a deletion is invisible.

    Asserted on the real tree by construction: remove every declaration from the
    tracked list and the package set is unchanged.
    """
    tracked = pic._tracked_files(_REPO_ROOT)
    without = [p for p in tracked if Path(p).name != pic.DECL_NAME]
    assert len(without) < len(tracked), "the real tree should carry declarations"
    assert pic.discover_packages(tracked, 4) == pic.discover_packages(without, 4)


def test_every_real_declaration_states_a_severity_and_a_why():
    """The §5 declaration is not left to a default, in any real package."""
    yaml = pytest.importorskip("yaml")
    tracked = pic._tracked_files(_REPO_ROOT)
    decls = [p for p in tracked if Path(p).name == pic.DECL_NAME]
    assert len(decls) >= 5, f"expected the pattern in >=5 packages, saw {len(decls)}"
    for rel in decls:
        doc = yaml.safe_load((_REPO_ROOT / rel).read_text())
        for inv in doc["invariants"]:
            assert inv["severity"] in ("BLOCKING", "ADVISORY"), rel
            assert inv["why"].strip(), rel
            assert inv["statement"].strip(), rel

