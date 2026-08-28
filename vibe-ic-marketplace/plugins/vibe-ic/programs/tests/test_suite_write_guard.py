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

THE CHILD'S ENVIRONMENT IS PART OF THE FIXTURE (vibe-ic#1047)
=============================================================
Driving a real nested session means the child's environment decides what the
child loads, and an environment nobody chose is one the HOST chose. These tests
passed 16/16 on one machine and failed 8/16 on the machine that runs every
`gh pr merge` — same commit, same command — because the child autoloaded a
broken `pytest11` entry point that has nothing to do with this guard.

So `_child_env` below decides the whole environment, and two tests fabricate a
broken plugin on the child's path to prove the decision holds — on any host,
including one where the offending package is not installed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_GUARD = _PROGRAMS / "suite_write_guard.py"

sys.path.insert(0, str(_PROGRAMS))
import suite_write_guard as swg  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

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


def _child_env(*extra_pythonpath: str) -> dict:
    """The child's WHOLE environment, decided here rather than by the host.

    vibe-ic#1047: these tests assert `returncode == 0` on a spawned pytest.
    That assertion is only about the guard if nothing ELSE on the host can
    make a bare pytest exit non-zero — so every input that decides what the
    child loads is pinned here, and nothing is inherited by accident.

    `PYTEST_DISABLE_PLUGIN_AUTOLOAD` is the load-bearing one. Without it the
    child loads every `pytest11` entry point installed on the machine, and one
    broken third-party package reddens a test that has nothing to do with it.
    On the landing host that package is `web3` (`web3.tools.pytest_ethereum`,
    `ImportError: cannot import name 'ContractName' from 'eth_typing'`), and it
    took 8 of these 16 tests down while saying nothing about the guard.

    Setting it in the OPERATOR's shell does not help and measuring that it did
    not help is what makes this fix worth writing down: `subprocess.run(env=…)`
    REPLACES the child environment, so a variable exported outside this
    process is dropped by the very whitelist meant to make the child
    predictable. The mitigation has to be applied to the child, here, or it
    reaches nothing.

    `PYTEST_ADDOPTS` and `PYTEST_PLUGINS` are pinned EMPTY for the same
    reason: both are read by the child and both can inject a plugin or a flag
    the assertions below never asked for.

    Disabling autoload does NOT weaken what the child runs. The guard is
    loaded explicitly by `-p suite_write_guard`, and the planted-writer tests
    above are the proof: they still go red and still name the path. A fix that
    bought a green by removing the guard from the child would have traded a
    false red for a false green, which is worse than the defect.
    """
    pythonpath = os.pathsep.join([str(_PROGRAMS), *extra_pythonpath])
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": pythonpath,
        # decide what the child loads; do not let the host decide it
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_ADDOPTS": "",
        "PYTEST_PLUGINS": "",
    }


def _nested_pytest(repo: Path, test_file: Path, *extra: str, env: dict | None = None):
    """Run a REAL pytest session with the REAL guard plugin loaded."""
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "-p", "suite_write_guard",
            "--write-guard-repo", str(repo), str(test_file), *extra]
    return _pr.run(argv, capture_output=True, text=True, cwd=str(repo.parent), env=env or _child_env())


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
    after = {"a/__pycache__/m.cpython-310.pyc": ["!!", 1, 1],
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
    p = _pr.run(
        [sys.executable, str(_GUARD), "--repo", str(tmp_path),
         "--compare", str(tmp_path / "no_such_baseline.json")],
        capture_output=True, text=True)
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
    p = _pr.run(
        [sys.executable, str(_GUARD), "--repo", str(plain),
         "--snapshot", str(tmp_path / "out.json")],
        capture_output=True, text=True)
    assert p.returncode == swg.RC_NOT_CHECKED, (p.returncode, p.stdout)


# --------------------------------------------------------------------------
# CLI shape, and per-test attribution.
# --------------------------------------------------------------------------

def test_cli_snapshot_then_compare_names_the_writer(tmp_path):
    """The standalone door, for a caller that is not pytest (a landing script,
    a human bisecting a stage that is not a test run at all)."""
    repo = _repo(tmp_path)
    base = tmp_path / "base.json"

    p = _pr.run([sys.executable, str(_GUARD), "--repo", str(repo),
                        "--snapshot", str(base)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert json.loads(base.read_text()) == {}

    (repo / "pkg" / "shipped.txt").write_text("mutated by something\n")

    rep = tmp_path / "report.json"
    p = _pr.run([sys.executable, str(_GUARD), "--repo", str(repo),
                        "--compare", str(base), "--json", str(rep)],
                       capture_output=True, text=True)
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
# The HARNESS must not be an assertion about the host (vibe-ic#1047).
#
# These two tests are what turns "it fails on .102" into something any host can
# run. The condition is not waited for: a broken `pytest11` entry point is
# FABRICATED on the child's path, which is exactly the shape `web3` has on the
# landing host, so the defect reproduces on a machine where `web3` is not
# installed at all and cannot silently un-reproduce when someone repairs it.
# --------------------------------------------------------------------------

#: The real message from the landing host, reused verbatim so a reader
#: grepping the issue lands here (`web3.tools.pytest_ethereum.deployer`).
_BROKEN_PLUGIN_ERROR = "cannot import name 'ContractName' from 'eth_typing'"


def _broken_pytest11_dist(tmp_path: Path) -> Path:
    """A directory that looks, to `importlib.metadata`, like an INSTALLED
    pytest plugin whose module raises `ImportError` when pytest imports it."""
    site = tmp_path / "hostsite"
    site.mkdir()
    (site / "wg1047_broken_plugin.py").write_text(
        f"raise ImportError({_BROKEN_PLUGIN_ERROR!r})\n")
    dist = site / "wg1047_broken_plugin-1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: wg1047-broken-plugin\nVersion: 1.0\n")
    (dist / "entry_points.txt").write_text(
        "[pytest11]\nwg1047_broken = wg1047_broken_plugin\n")
    (dist / "RECORD").write_text("")
    return site


def test_a_broken_host_plugin_cannot_redden_the_child_but_WOULD_have(tmp_path):
    """Both directions, in one test, because either alone proves nothing.

    The negative control comes first: with autoload left to the host, the
    fabricated plugin really does kill the child before the guard can speak.
    An immunity assertion whose hostile fixture is inert would pass against
    the pre-fix code too (flow-change-acceptance §1).
    """
    repo = _repo(tmp_path)
    target = repo / "pkg" / "shipped.txt"
    tf = _write_test_file(repo, (
        "from pathlib import Path\n"
        f"def test_appends_to_a_shipped_file():\n"
        f"    p = Path({str(target)!r})\n"
        "    p.write_text(p.read_text() + 'appended by a passing test\\n')\n"))
    site = _broken_pytest11_dist(tmp_path)

    # NEGATIVE CONTROL — this is the .102 failure, reproduced here.
    hostile = _child_env(str(site))
    hostile.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD")
    p = _nested_pytest(repo, tf, env=hostile)
    out = p.stdout + p.stderr
    assert p.returncode != 0, f"the hostile fixture is inert:\n{out}"
    assert _BROKEN_PLUGIN_ERROR in out, f"the plugin never loaded:\n{out}"
    # and note WHY that red says nothing about the guard: the session died
    # during config parse, so the guard never got to report at all
    assert "WROTE INTO THE TREE" not in out, out
    assert not target.read_text().endswith("appended by a passing test\n")

    # THE FIX — same broken plugin, same path, environment decided by us.
    p = _nested_pytest(repo, tf, env=_child_env(str(site)))
    out = p.stdout + p.stderr
    assert _BROKEN_PLUGIN_ERROR not in out, f"host plugin reached the child:\n{out}"
    # the guard is still LOADED and still bites — the green was not bought by
    # taking the guard out of the child
    assert "1 passed" in out, out
    assert p.returncode != 0, f"guard did not redden the session:\n{out}"
    assert "WROTE INTO THE TREE" in out, out
    assert "pkg/shipped.txt" in out, out


def test_a_broken_host_plugin_cannot_redden_a_NON_writing_child(tmp_path):
    """The false RED #1047 actually produced: a clean session called dirty.

    `test_a_non_writing_session_stays_green` is the one whose `returncode == 0`
    was an assertion about the host's `site-packages`. Under a hostile path it
    must still be an assertion about the guard.
    """
    repo = _repo(tmp_path)
    site = _broken_pytest11_dist(tmp_path)
    tf = _write_test_file(repo, "def test_reads_nothing():\n    assert True\n")

    p = _nested_pytest(repo, tf, env=_child_env(str(site)))
    out = p.stdout + p.stderr
    assert p.returncode == 0, f"a host plugin reddened a clean session:\n{out}"
    assert "wrote nothing" in out, out


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


# --------------------------------------------------------------------------
# THE AMBIENT-REPOSITORY TRAP (vibe-ic#1412)
#
# Both tests below drive the DISCOVERY door — no `--write-guard-repo` — because
# that is the door the defect lives behind and the one every real session uses.
# They are a pair on purpose: the first says the guard must decline a tree it
# cannot measure, the second says it must still BITE on a tree it can. Either
# one alone could be satisfied by breaking the guard in the other direction.
# --------------------------------------------------------------------------

def _detached_copy_of_the_guard(dest: Path) -> Path:
    """A copy of the REAL guard module at `dest/programs/`, importable there.

    The guard reaches `git status` through `_progress_run`, so the copy is not
    one file any more. Its siblings come with it, into the same `programs/`
    directory they live in here — which is the shape the guard is deployed in,
    not a convenience for the test. Copying only the entry module would leave
    the mirror importing a module that is not there, and the nested pytest
    would die on the import rather than on the property under test.
    """
    (dest / "programs").mkdir(parents=True, exist_ok=True)
    target = dest / "programs" / "suite_write_guard.py"
    target.write_text(_GUARD.read_text())
    for dep in ("_progress_run.py", "_watchdog.py"):
        (dest / "programs" / dep).write_text((_GUARD.parent / dep).read_text())
    return target


def _ambient_repo(tmp_path: Path) -> Path:
    """A repo that is NOT this tree and has never heard of its `.gitignore`.

    No `__pycache__` rule, which is the whole point: in THIS checkout
    `.gitignore:2` puts bytecode in the IGNORED (advisory) class, and in an
    unrelated repository the identical bytes are UNTRACKED (blocking).
    """
    r = tmp_path / "ambient"
    r.mkdir()
    (r / "unrelated.txt").write_text("a repository that is not the subject\n")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    return r


def test_a_detached_copy_inside_an_ambient_repo_is_NOT_CHECKED_not_blocked(tmp_path):
    """A `cp -al` mirror under a `$TMPDIR` inside some other checkout.

    This is #1412 in miniature. `matrix_mutation_ledger`'s LOCK 2 replay runs
    each PLUGIN_TREE witness cell in a hardlink mirror of the plugin, and reads
    the cell's EXIT CODE to decide whether the unmutated cell was green. When
    the mirror lands inside an unrelated repository the guard discovered THAT
    repository, saw the session's own bytecode as `??`, and reddened a session
    whose test passed — so the ledger recorded `ALREADY_RED`, i.e. "this gate
    can no longer be shown to have teeth", about a replay that was working.

    The guard must decline: a detached copy has no `git status` describing it.
    Declining is not a quiet pass — `WRITE_GUARD_NOT_CHECKED` is asserted here,
    and rc=2/NOT-CHECKED is this file's standing convention.
    """
    ambient = _ambient_repo(tmp_path)
    mirror = ambient / "mirror"
    _detached_copy_of_the_guard(mirror)
    helper = mirror / "programs" / "zz_imported_after_the_baseline.py"
    helper.write_text("OK = True\n")
    tf = mirror / "test_in_the_mirror.py"
    tf.write_text(
        "def test_imports_a_module_and_writes_nothing_of_its_own():\n"
        "    import zz_imported_after_the_baseline as z\n"
        "    assert z.OK\n")

    env = _child_env()
    # the copy, NOT this checkout's `programs/` — otherwise the child imports
    # the tracked original and discovers the real repository.
    env["PYTHONPATH"] = str(mirror / "programs")

    before = swg.snapshot(ambient)
    p = _pr.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-p", "suite_write_guard", str(tf)],
        capture_output=True, text=True, cwd=str(mirror), env=env)
    out = p.stdout + p.stderr
    after = swg.snapshot(ambient)

    # The setup is live, not inert: the ambient repo really did gain
    # blocking-class paths from that session. Without this the test could pass
    # because nothing happened rather than because the guard declined.
    gained = swg.compare(before, after)["blocking"]
    assert gained, (
        "the ambient repository gained no blocking-class path, so this test "
        "would pass even with the trap wide open; the child wrote no bytecode "
        f"(PYTHONDONTWRITEBYTECODE?). out={out[-800:]}")
    assert all("mirror/" in f["path"] for f in gained), gained

    assert p.returncode == 0, (
        "a session in a detached copy was BLOCKED by the state of the "
        "repository that merely encloses it:\n" + out[-2000:])
    assert "WRITE_GUARD_NOT_CHECKED" in out, (
        "declining must be LOUD — silence reads as 'measured and clean':\n"
        + out[-2000:])
    assert "does not track it" in out, out[-2000:]


def test_the_SAME_discovery_door_still_reddens_a_real_checkout(tmp_path):
    """PAIRED GUARD. The fix must not buy its green by declining everything.

    Same door as the test above — discovery, no `--write-guard-repo` — but the
    guard's own file is TRACKED here, so the repository it finds is the tree it
    is testing and a planted writer must still make the session RED and NAME
    the path. If `_repo_root` ever starts declining a real checkout, this goes
    red; if it stops declining a detached copy, the test above goes red. Only
    the correct discriminator satisfies both.
    """
    r = tmp_path / "checkout"
    _detached_copy_of_the_guard(r)
    (r / "pkg").mkdir()
    (r / "pkg" / "shipped.txt").write_text("published bytes\n")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)

    tf = tmp_path / "test_planted_writer.py"
    tf.write_text(
        "from pathlib import Path\n"
        "def test_appends_to_a_shipped_file():\n"
        f"    p = Path(r'{r / 'pkg' / 'shipped.txt'}')\n"
        "    p.write_text(p.read_text() + 'mutated by a test\\n')\n")

    env = _child_env()
    env["PYTHONPATH"] = str(r / "programs")
    p = _pr.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-p", "suite_write_guard", str(tf)],
        capture_output=True, text=True, cwd=str(r), env=env)
    out = p.stdout + p.stderr
    assert p.returncode == 1, (
        "the guard discovered a REAL checkout and let a tracked write through:"
        "\n" + out[-2000:])
    assert "WROTE INTO THE TREE" in out, out[-2000:]
    assert "pkg/shipped.txt" in out, out[-2000:]
    assert "WRITE_GUARD_NOT_CHECKED" not in out, (
        "declined a checkout that tracks the guard — the fix would then be "
        "buying its green by measuring nothing:\n" + out[-2000:])
