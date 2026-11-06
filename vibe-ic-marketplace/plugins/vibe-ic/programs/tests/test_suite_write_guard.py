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

import os
import subprocess
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
_GUARD = _PROGRAMS / "suite_write_guard.py"

sys.path.insert(0, str(_PROGRAMS))

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


# --------------------------------------------------------------------------
# The paired clean direction. Vacuous on its own — meaningful only next to the
# planted writers above, which prove this same code path can fire.
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Degrade loudly, never silently (flow-change-acceptance §6).
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# CLI shape, and per-test attribution.
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# The guard must not perturb its own subject.
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Driven by a REAL in-repo artefact, not a fixture authored alongside the fix
# (flow-change-acceptance §4): "a change whose tests are all fixtures authored
# alongside it cannot distinguish itself from its own absence."
# --------------------------------------------------------------------------


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
