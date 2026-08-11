"""A guard nobody has seen fire is indistinguishable from no guard (vibe-ic#1029).

WHAT THESE TESTS ARE FOR
========================
`suite_write_guard` asserts that a test run leaves `git status --porcelain`
EMPTY. That assertion is worth exactly as much as the proof that it can FAIL,
so the load-bearing test in this file is not the one where the tree stays
clean — it is `test_a_planted_writer_reddens_the_session`, which plants a
deliberate writer and proves the session goes red and NAMES the path.

Three writers into this repo's shipped tree were each found by accident. The
reason none was found by looking is that the rule was prose. A "clears the
finding" assertion on its own would pass vacuously here — nothing can fire if
nothing looks — so every clean-tree assertion below is paired with the planted
writer that proves the same code path bites (flow-change-acceptance §1).

Every test drives the REAL `suite_write_guard` module, loaded as a real pytest
plugin into a real nested pytest session against a real throwaway git repo, for
the reason `test_corpus_write_guard.py` gives about `_gate_dispatch.sh`: a
fixture copy of the logic would drift from the code that actually runs.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_GUARD = _PROGRAMS / "suite_write_guard.py"

sys.path.insert(0, str(_PROGRAMS))
import suite_write_guard as swg  # noqa: E402

#: Every nested session below runs a handful of trivial tests against a
#: throwaway repo. This only stops a hung one from taking the outer session
#: down (#542); it must stay under the 60 s ceiling
#: `ci_harness_timeout_ceiling_check` enforces, or pytest kills the whole
#: session at 180 s first and the bound can never fire as a TEST failure.
_T = 55


def _repo(tmp_path: Path) -> Path:
    """A throwaway git repo with one tracked file and a gitignored cache dir."""
    r = tmp_path / "repo"
    (r / "pkg").mkdir(parents=True)
    (r / "pkg" / "shipped.txt").write_text("published bytes\n")
    (r / ".gitignore").write_text("cache/\n")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    return r


def _write_test_file(repo: Path, body: str) -> Path:
    """A test file OUTSIDE the repo, so authoring it cannot itself dirty it."""
    d = repo.parent / "suite"
    d.mkdir(exist_ok=True)
    f = d / "test_planted.py"
    f.write_text(body)
    return f


def _nested_pytest(repo: Path, test_file: Path, *extra: str):
    """Run a REAL pytest session with the REAL guard plugin loaded."""
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "-p", "suite_write_guard",
            "--write-guard-repo", str(repo), str(test_file), *extra]
    env = {"PATH": __import__("os").environ.get("PATH", ""),
           "PYTHONPATH": str(_PROGRAMS),
           "HOME": __import__("os").environ.get("HOME", "")}
    return subprocess.run(argv, capture_output=True, text=True, timeout=_T,
                          cwd=str(repo.parent), env=env)


# --------------------------------------------------------------------------
# THE CONTROL. #1029: "It must be able to FAIL: plant a deliberate writer and
# prove it reddens; that control is mandatory."
# --------------------------------------------------------------------------

def test_a_planted_writer_reddens_the_session(tmp_path):
    """A test that appends to a TRACKED shipped file must make the run RED.

    This is the `add_compliance_gate.py` shape exactly: a passing test that
    appends to a shipped file and never restores it.
    """
    repo = _repo(tmp_path)
    target = repo / "pkg" / "shipped.txt"
    tf = _write_test_file(repo, (
        "from pathlib import Path\n"
        f"def test_appends_to_a_shipped_file():\n"
        f"    p = Path({str(target)!r})\n"
        "    p.write_text(p.read_text() + 'appended by a passing test\\n')\n"
        "    assert p.is_file()\n"))

    p = _nested_pytest(repo, tf)
    out = p.stdout + p.stderr

    # the test itself PASSED — that is the whole point of the defect
    assert "1 passed" in out, out
    # ... and the session is still RED, because of the write
    assert p.returncode != 0, f"guard did not redden the session:\n{out}"
    assert "WROTE INTO THE TREE" in out, out
    # it NAMES the path, rather than only failing
    assert "pkg/shipped.txt" in out, out
    # and the tree really was mutated
    assert "appended by a passing test" in target.read_text()


def test_a_planted_untracked_writer_also_reddens(tmp_path):
    """`??` is blocking too — `git add -A` would ship it just the same."""
    repo = _repo(tmp_path)
    tf = _write_test_file(repo, (
        "from pathlib import Path\n"
        f"def test_creates_an_untracked_file():\n"
        f"    d = Path({str(repo)!r}) / 'reports'\n"
        "    d.mkdir(parents=True, exist_ok=True)\n"
        "    (d / 'leftover.json').write_text('{}\\n')\n"))

    p = _nested_pytest(repo, tf)
    out = p.stdout + p.stderr
    assert "1 passed" in out, out
    assert p.returncode != 0, f"untracked write did not redden:\n{out}"
    assert "reports/leftover.json" in out, out


def test_a_rewrite_of_an_ALREADY_dirty_file_still_reddens(tmp_path):
    """Status alone cannot see this; the content signature is what catches it.

    The file is already ` M` before the session, so porcelain reads ` M` both
    before and after. Only `(status, size, mtime_ns)` distinguishes them —
    which is why the snapshot carries more than the status.
    """
    repo = _repo(tmp_path)
    target = repo / "pkg" / "shipped.txt"
    target.write_text("a developer's own edit, in flight\n")

    tf = _write_test_file(repo, (
        "from pathlib import Path\n"
        f"def test_rewrites_an_already_modified_file():\n"
        f"    p = Path({str(target)!r})\n"
        "    p.write_text('overwritten by the suite, quite differently\\n')\n"))

    p = _nested_pytest(repo, tf)
    out = p.stdout + p.stderr
    assert p.returncode != 0, f"rewrite of a dirty file went unnoticed:\n{out}"
    assert "pkg/shipped.txt" in out, out


# --------------------------------------------------------------------------
# The paired clean direction. Vacuous on its own — meaningful only next to the
# planted writers above, which prove this same code path can fire.
# --------------------------------------------------------------------------

def test_a_non_writing_session_stays_green(tmp_path):
    repo = _repo(tmp_path)
    tf = _write_test_file(repo, "def test_reads_nothing():\n    assert True\n")
    p = _nested_pytest(repo, tf)
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert "wrote nothing" in out, out


def test_a_dirty_tree_at_session_start_is_NOT_blamed_on_the_run(tmp_path):
    """The false positive that would make people route around the gate.

    A developer with edits in flight must not be told the suite wrote them.
    """
    repo = _repo(tmp_path)
    (repo / "pkg" / "shipped.txt").write_text("in-flight edit\n")
    (repo / "untracked_scratch.txt").write_text("mine, not the suite's\n")

    tf = _write_test_file(repo, "def test_reads_nothing():\n    assert True\n")
    p = _nested_pytest(repo, tf)
    out = p.stdout + p.stderr
    assert p.returncode == 0, f"pre-existing dirt was blamed on the run:\n{out}"
    assert "shipped.txt" not in out, out
    assert "untracked_scratch.txt" not in out, out


def test_ignored_class_is_named_but_never_blocking(tmp_path):
    """The invisible class: reported so it is not lost, advisory so it is not
    a gate that fires on every run in every checkout."""
    repo = _repo(tmp_path)
    tf = _write_test_file(repo, (
        "from pathlib import Path\n"
        f"def test_leaves_an_ignored_artefact():\n"
        f"    d = Path({str(repo)!r}) / 'cache'\n"
        "    d.mkdir(parents=True, exist_ok=True)\n"
        "    (d / 'leftover.json').write_text('{}\\n')\n"))

    p = _nested_pytest(repo, tf)
    out = p.stdout + p.stderr
    assert p.returncode == 0, f"an ignored artefact must not block:\n{out}"
    assert "cache/leftover.json" in out, out
    assert "ADVISORY" in out, out


def test_bytecode_noise_is_counted_not_listed(tmp_path):
    """A gate that prints 200 lines of __pycache__ is a gate people stop
    reading. Suppressed by count, never silently."""
    before = {}
    after = {f"a/__pycache__/m.cpython-310.pyc": ["!!", 1, 1],
             "b/real_leftover.json": ["!!", 2, 2]}
    result = swg.compare(before, after)
    text = swg.format_report(result)
    assert "real_leftover.json" in text
    assert "m.cpython-310.pyc" not in text
    assert "+1 regenerable cache artefact" in text


# --------------------------------------------------------------------------
# Degrade loudly, never silently (flow-change-acceptance §6).
# --------------------------------------------------------------------------

def test_cannot_look_exits_2_and_never_0(tmp_path):
    """rc=2 is NOT CHECKED. It must never be folded into a pass."""
    p = subprocess.run(
        [sys.executable, str(_GUARD), "--repo", str(tmp_path),
         "--compare", str(tmp_path / "no_such_baseline.json")],
        capture_output=True, text=True, timeout=_T)
    assert p.returncode == swg.RC_NOT_CHECKED, (p.returncode, p.stdout, p.stderr)
    assert "WRITE_GUARD_NOT_CHECKED" in p.stderr, p.stderr
    assert "NOT a pass" in p.stdout, p.stdout


def test_turning_the_guard_off_announces_itself(tmp_path):
    """A disabled guard that is silent reads as a guard that passed."""
    repo = _repo(tmp_path)
    tf = _write_test_file(repo, "def test_x():\n    assert True\n")
    p = _nested_pytest(repo, tf, "--write-guard=off")
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert "WRITE_GUARD_NOT_CHECKED" in out, out


def test_a_non_repo_is_not_checked_rather_than_clean(tmp_path):
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    p = subprocess.run(
        [sys.executable, str(_GUARD), "--repo", str(plain),
         "--snapshot", str(tmp_path / "out.json")],
        capture_output=True, text=True, timeout=_T)
    assert p.returncode == swg.RC_NOT_CHECKED, (p.returncode, p.stdout)


# --------------------------------------------------------------------------
# CLI shape, and per-test attribution.
# --------------------------------------------------------------------------

def test_cli_snapshot_then_compare_names_the_writer(tmp_path):
    """The standalone door, for a caller that is not pytest (a landing script,
    a human bisecting a stage that is not a test run at all)."""
    repo = _repo(tmp_path)
    base = tmp_path / "base.json"

    p = subprocess.run([sys.executable, str(_GUARD), "--repo", str(repo),
                        "--snapshot", str(base)],
                       capture_output=True, text=True, timeout=_T)
    assert p.returncode == 0, p.stdout + p.stderr
    assert json.loads(base.read_text()) == {}

    (repo / "pkg" / "shipped.txt").write_text("mutated by something\n")

    rep = tmp_path / "report.json"
    p = subprocess.run([sys.executable, str(_GUARD), "--repo", str(repo),
                        "--compare", str(base), "--json", str(rep)],
                       capture_output=True, text=True, timeout=_T)
    assert p.returncode == swg.RC_WROTE, p.stdout + p.stderr
    assert "pkg/shipped.txt" in p.stdout
    assert [f["path"] for f in json.loads(rep.read_text())["blocking"]] \
        == ["pkg/shipped.txt"]


def test_per_test_mode_attributes_the_write_to_its_nodeid(tmp_path):
    """Session mode says the RUN wrote; per-test says WHICH test wrote.

    2471 test files make "one file at a time against a reset tree" not a
    90-minute job, which is what made attributing the three known writers cost
    three separate accidents.
    """
    repo = _repo(tmp_path)
    tf = _write_test_file(repo, (
        "from pathlib import Path\n"
        "def test_innocent():\n    assert True\n"
        f"def test_guilty():\n"
        f"    p = Path({str(repo / 'pkg' / 'shipped.txt')!r})\n"
        "    p.write_text('written here\\n')\n"))

    p = _nested_pytest(repo, tf, "--write-guard=per-test")
    out = p.stdout + p.stderr
    assert p.returncode != 0, out
    assert "test_guilty" in out, out
    assert "written by" in out, out
    assert "test_innocent" not in out.split("written by")[-1], out


# --------------------------------------------------------------------------
# The guard must not perturb its own subject.
# --------------------------------------------------------------------------

def test_the_guard_itself_writes_nothing(tmp_path):
    repo = _repo(tmp_path)
    before = swg.snapshot(repo)
    for _ in range(3):
        swg.snapshot(repo)
    assert swg.snapshot(repo) == before
    assert swg.compare(before, swg.snapshot(repo))["blocking"] == []


# --------------------------------------------------------------------------
# Driven by a REAL in-repo artefact, not a fixture authored alongside the fix
# (flow-change-acceptance §4): "a change whose tests are all fixtures authored
# alongside it cannot distinguish itself from its own absence."
# --------------------------------------------------------------------------

def test_it_measures_THIS_repository_and_self_compares_clean(tmp_path):
    """The guard's real subject is this checkout, not a throwaway repo.

    Hardcodes no path: the root comes from `_hostpaths.repo_path`, which
    derives it from `__file__`. Self-comparison must be empty on ANY tree,
    dirty or clean — the guard reports what a RUN changed, never what the
    checkout already carried.
    """
    from _hostpaths import repo_path
    repo = repo_path()
    if not (repo / ".git").exists():
        pytest.skip(f"not a git checkout: {repo}")

    snap = swg.snapshot(repo)
    assert isinstance(snap, dict)
    for path, sig in snap.items():
        assert isinstance(path, str) and path
        assert len(sig) == 3 and isinstance(sig[0], str)
        assert swg._classify(sig[0]) in (swg.TRACKED, swg.UNTRACKED, swg.IGNORED)

    assert swg.compare(snap, snap)["blocking"] == []
    assert swg.compare(snap, snap)["advisory"] == []


def test_the_guard_is_actually_WIRED_into_the_rootdir_conftest():
    """A guard nothing loads is a guard that never runs.

    `landing_worktree_is_clean_check` exists and is correct, and #1029 still
    happened, because what fires a check is its WIRING. This asserts the one
    line that makes the guard ride every pytest session rooted at the plugin —
    including the targeted subset `tools/gatekeeper-land.sh` runs on every
    landing — so removing it breaks a test rather than going unnoticed.
    """
    conftest = _PROGRAMS.parent / "conftest.py"
    text = conftest.read_text()
    assert "pytest_plugins" in text, f"guard not wired in {conftest}"
    assert "suite_write_guard" in text, f"guard not wired in {conftest}"
    # and the module the wiring names must exist and be loadable
    assert _GUARD.is_file(), _GUARD


def test_paths_needing_quoting_are_parsed_not_mangled(tmp_path):
    """`-z` rather than the newline form: a path with a space or a quote is
    C-quoted in the default output and would be silently mis-attributed."""
    repo = _repo(tmp_path)
    odd = repo / 'a file with "quotes" and spaces.txt'
    odd.write_text("x\n")
    snap = swg.snapshot(repo)
    assert 'a file with "quotes" and spaces.txt' in snap, snap
