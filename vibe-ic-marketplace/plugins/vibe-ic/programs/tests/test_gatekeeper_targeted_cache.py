"""The targeted-test cache may only ever be WRONG in one direction.

Reuse is a claim that nothing which could change the tier's verdict has moved.
Every test here is about the direction that would cost a landing: a bundle
served for a tree that is not the tree it was measured on, i.e. a FALSE GREEN.
The saving is not tested — a cache that is fast and wrong is worthless, and a
cache that misses too often is merely slow.

The sharpest case, and the one this file exists for: a defect planted in the
worktree WITHOUT a commit leaves `HEAD` untouched. A cache keyed on `HEAD`
alone would hand that tree the clean tree's green.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
PROG = PLUGIN / "programs" / "gatekeeper_targeted_cache.py"
DRIVER = PLUGIN / "programs" / "pytest_per_file_junit.py"

SELECTED = ["programs/tests/test_alpha.py", "programs/tests/test_beta.py"]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cache = _load(PROG, "_t_gk_targeted_cache")
driver = _load(DRIVER, "_t_gk_per_file_driver")


# --------------------------------------------------------------- the fixtures


def _git(repo: Path, *args: str, env=None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, env=e, timeout=120)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    (r / "src" / "thing.py").write_text("VALUE = 1\n")
    _git(r.parent, "init", "-q", str(r))
    _git(r, "config", "user.email", "gate@example.invalid")
    _git(r, "config", "user.name", "gate")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    return r


def _selection(tmp_path: Path, files=SELECTED) -> Path:
    p = tmp_path / "selection.txt"
    p.write_text("".join(f"{f}\n" for f in files))
    return p


def _junit(path: Path, files=SELECTED, red_file: str | None = None,
           process_rc: int = 0, aggregate: bool = True) -> Path:
    """A merged report in EXACTLY the shape the real driver writes.

    Built with the driver's own `_append_process_case` / `_aggregate_copy`
    rather than by hand: the attestation shape is what `landing_merge_verdict`
    authenticates, and a hand-rolled copy of it in a test would be free to
    drift from the writer it is standing in for.
    """
    root = ET.Element("testsuites", {"name": "pytest tests"})
    suite = ET.Element("testsuite", {"name": "pytest", "tests": str(len(files)),
                                     "failures": "0", "errors": "0",
                                     "skipped": "0"})
    for f in files:
        classname = f[: -len(".py")].replace("/", ".")
        tc = ET.SubElement(suite, "testcase",
                           {"classname": classname, "name": "test_it",
                            "file": f, "time": "0.01"})
        if red_file == f:
            ET.SubElement(tc, "failure", {"message": "planted"})
    root.append(driver._aggregate_copy(suite))
    if aggregate:
        driver._append_process_case(
            root, classname="pytest_aggregate_process",
            name="whole_selection::process_exit", file_name="<aggregate>",
            rc=process_rc)
    ET.ElementTree(root).write(str(path), encoding="utf-8",
                               xml_declaration=True)
    return path


def _log(path: Path, cases: int = 2, red: int = 0, rc: int = 0,
         guard: bool = True, extra: str = "") -> Path:
    body = [f"=== [aggregate] {len(SELECTED)} file(s) in one pytest process",
            "suite_write_guard: PASS — the suite wrote nothing" if guard else
            "(no guard line)",
            f"AGGREGATE_COMPLETE  rc={rc}  cases={cases}  red={red}",
            "=== pytest junit summary",
            "  mode       aggregate-first",
            f"  asked      {len(SELECTED)}"]
    if extra:
        body.append(extra)
    path.write_text("\n".join(body) + "\n")
    return path


def _run(argv, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([sys.executable, str(PROG), *argv],
                          capture_output=True, text=True, env=e, timeout=300)


def _bundle(tmp_path: Path, repo: Path, *, selection: Path | None = None,
            harness: Path | None = None, contract: str = "c=1",
            cache_dir: Path | None = None, junit: Path | None = None,
            log: Path | None = None, rc: str = "0"):
    selection = selection or _selection(tmp_path)
    harness = harness or (tmp_path / "harness.sh")
    if not harness.exists():
        harness.write_text("#!/usr/bin/env bash\n")
    cache_dir = cache_dir or (tmp_path / "cache")
    junit = junit or _junit(tmp_path / "junit.xml")
    log = log or _log(tmp_path / "driver.log")
    return dict(selection=selection, harness=harness, contract=contract,
                cache_dir=cache_dir, junit=junit, log=log, rc=rc, repo=repo)


def _publish(b) -> subprocess.CompletedProcess:
    return _run(["publish", "--repo", str(b["repo"]), "--plugin", str(PLUGIN),
                 "--selection", str(b["selection"]), "--harness",
                 str(b["harness"]), "--contract", b["contract"], "--cache-dir",
                 str(b["cache_dir"]), "--junit", str(b["junit"]), "--log",
                 str(b["log"]), "--rc", b["rc"]])


def _lookup(b, tmp_path: Path, env=None, contract=None,
            selection=None) -> subprocess.CompletedProcess:
    return _run(["lookup", "--repo", str(b["repo"]), "--plugin", str(PLUGIN),
                 "--selection", str(selection or b["selection"]), "--harness",
                 str(b["harness"]), "--contract", contract or b["contract"],
                 "--cache-dir", str(b["cache_dir"]), "--junit-out",
                 str(tmp_path / "out.xml"), "--log-out",
                 str(tmp_path / "out.log")], env=env)


# ------------------------------------------------------ the exactness predicate


def test_a_clean_checkout_is_exact(repo: Path):
    ok, why = cache.worktree_is_exact(repo)
    assert ok, why


def test_a_tracked_modification_is_not_exact(repo: Path):
    (repo / "src" / "thing.py").write_text("VALUE = 2\n")
    ok, why = cache.worktree_is_exact(repo)
    assert not ok
    assert "tracked file(s) differ" in why


def test_an_untracked_file_is_not_exact(repo: Path):
    (repo / "src" / "planted.py").write_text("x = 1\n")
    ok, why = cache.worktree_is_exact(repo)
    assert not ok
    assert "untracked file(s) present" in why


def test_assume_unchanged_cannot_hide_a_modified_file(repo: Path):
    """`git status` is clean here. The bytes are not, and the bytes decide.

    This is why the predicate builds a FRESH index from `HEAD^{tree}` instead
    of asking `git status`: the subject's own index is the one thing it can
    set to make a modification invisible.
    """
    _git(repo, "update-index", "--assume-unchanged", "src/thing.py")
    (repo / "src" / "thing.py").write_text("VALUE = 999\n")
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""
    ok, why = cache.worktree_is_exact(repo)
    assert not ok, "a hidden modification was accepted as an exact tree"
    assert "assume-unchanged" in why


# ------------------------------------------------------------------- the key


def test_every_key_component_changes_the_digest(tmp_path: Path, repo: Path):
    """No component of the key may be decorative.

    A component that does not move the digest is a component the cache is not
    really keyed on, however convincing it looks in the manifest.
    """
    b = _bundle(tmp_path, repo)
    material = cache.key_material(repo, PLUGIN, b["selection"], b["harness"],
                                 b["contract"])
    base = cache.key_digest(material)
    assert len(material) >= 14
    for i, (name, _value) in enumerate(material):
        mutated = list(material)
        mutated[i] = (name, "MUTATED")
        assert cache.key_digest(mutated) != base, (
            f"the key ignores {name!r} — it is in the manifest but not in the "
            f"decision")


def test_the_key_moves_with_the_selection_and_the_harness(tmp_path: Path,
                                                          repo: Path):
    b = _bundle(tmp_path, repo)
    first = cache.key_digest(cache.key_material(
        repo, PLUGIN, b["selection"], b["harness"], b["contract"]))
    (tmp_path / "other").mkdir()
    other = _selection(tmp_path / "other", files=SELECTED[:1])
    assert cache.key_digest(cache.key_material(
        repo, PLUGIN, other, b["harness"], b["contract"])) != first
    b["harness"].write_text("#!/usr/bin/env bash\n# edited\n")
    assert cache.key_digest(cache.key_material(
        repo, PLUGIN, b["selection"], b["harness"], b["contract"])) != first


# ----------------------------------------------------------- store and reuse


def test_publish_then_lookup_returns_the_bundle(tmp_path: Path, repo: Path):
    b = _bundle(tmp_path, repo)
    pub = _publish(b)
    assert pub.returncode == 0, pub.stdout + pub.stderr
    assert pub.stdout.startswith("STORED")
    got = _lookup(b, tmp_path)
    assert got.returncode == 0, got.stdout
    assert got.stdout.startswith("HIT")
    assert (tmp_path / "out.xml").read_bytes() == b["junit"].read_bytes()
    assert (tmp_path / "out.log").read_bytes() == b["log"].read_bytes()


def test_a_cold_cache_misses(tmp_path: Path, repo: Path):
    b = _bundle(tmp_path, repo)
    (tmp_path / "cache").mkdir()
    got = _lookup(b, tmp_path)
    assert got.returncode == 1
    assert got.stdout.startswith("MISS")


@pytest.mark.parametrize("mutate,expect", [
    ("dirty_tracked", "not exactly HEAD"),
    ("untracked", "not exactly HEAD"),
    ("head", "no bundle"),
    ("selection", "no bundle"),
    ("harness", "no bundle"),
    ("contract", "no bundle"),
    ("env", "no bundle"),
])
def test_a_stored_green_is_not_served_to_a_different_tree(
        tmp_path: Path, repo: Path, mutate: str, expect: str):
    """THE FIXTURE DEFENCE, one row per way a round can differ.

    `dirty_tracked` is the planted-defect shape: a patch applied to the
    worktree and never committed. `HEAD` is unchanged, so a cache keyed on the
    commit alone would serve this tree the clean tree's green.
    """
    b = _bundle(tmp_path, repo)
    assert _publish(b).returncode == 0
    assert _lookup(b, tmp_path).returncode == 0, "the control hit must hold"

    env = None
    contract = None
    selection = None
    if mutate == "dirty_tracked":
        (repo / "src" / "thing.py").write_text("VALUE = 2  # planted\n")
    elif mutate == "untracked":
        (repo / "src" / "planted.py").write_text("x = 1\n")
    elif mutate == "head":
        (repo / "src" / "thing.py").write_text("VALUE = 2\n")
        _git(repo, "commit", "-qam", "move HEAD")
    elif mutate == "selection":
        (tmp_path / "other").mkdir()
        selection = _selection(tmp_path / "other", files=SELECTED[:1])
    elif mutate == "harness":
        b["harness"].write_text("#!/usr/bin/env bash\n# edited\n")
    elif mutate == "contract":
        contract = "c=2"
    elif mutate == "env":
        env = {"GATEKEEPER_SOMETHING_NEW": "1"}

    got = _lookup(b, tmp_path, env=env, contract=contract, selection=selection)
    assert got.returncode != 0, f"a stale green was served after {mutate}"
    assert expect in got.stdout, got.stdout


def test_a_busy_lock_is_a_miss_not_a_wait(tmp_path: Path, repo: Path):
    import fcntl
    b = _bundle(tmp_path, repo)
    assert _publish(b).returncode == 0
    material = cache.key_material(repo, PLUGIN, b["selection"], b["harness"],
                                 b["contract"])
    head = dict(material)["head"]
    prefix = cache._prefix(b["cache_dir"], head, cache.key_digest(material))
    fd = os.open(str(prefix) + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        got = _lookup(b, tmp_path)
    finally:
        os.close(fd)
    assert got.returncode == 1
    assert "lock" in got.stdout


# ------------------------------------------------------- what is never banked


def test_publish_refuses_a_red_round(tmp_path: Path, repo: Path):
    b = _bundle(tmp_path, repo, rc="1")
    out = _publish(b)
    assert out.returncode != 0
    assert "only a complete green tier is banked" in out.stdout


def test_publish_refuses_a_session_without_the_write_guard(tmp_path: Path,
                                                           repo: Path):
    """The paired guard from `gatekeeper-land.sh`, carried across rounds.

    A green bought by dropping `suite_write_guard` from the session looks
    exactly like an honest green. Banking one would make it permanent.
    """
    b = _bundle(tmp_path, repo,
                log=_log(tmp_path / "noguard.log", guard=False))
    out = _publish(b)
    assert out.returncode != 0
    assert "suite_write_guard" in out.stdout


@pytest.mark.parametrize("extra,fragment", [
    ("NORECORD  programs/tests/test_alpha.py  killed", "NORECORD"),
    ("NOTRUN    programs/tests/test_beta.py  stop-after-failures", "NOTRUN"),
    ("AGGREGATE_NORECORD  stalled", "AGGREGATE_NORECORD"),
    ("EMPTY     programs/tests/test_beta.py  rc=5", "EMPTY"),
])
def test_publish_refuses_an_incomplete_record(tmp_path: Path, repo: Path,
                                              extra: str, fragment: str):
    b = _bundle(tmp_path, repo,
                log=_log(tmp_path / "partial.log", extra=extra))
    out = _publish(b)
    assert out.returncode != 0
    assert fragment in out.stdout


def test_publish_refuses_a_junit_that_does_not_cover_the_selection(
        tmp_path: Path, repo: Path):
    b = _bundle(tmp_path, repo,
                junit=_junit(tmp_path / "short.xml", files=SELECTED[:1]))
    out = _publish(b)
    assert out.returncode != 0
    assert "aggregate covers 1 of 2" in out.stdout


def test_publish_refuses_a_junit_carrying_a_red_case(tmp_path: Path,
                                                     repo: Path):
    b = _bundle(tmp_path, repo,
                junit=_junit(tmp_path / "red.xml", red_file=SELECTED[0]))
    out = _publish(b)
    assert out.returncode != 0
    assert "red outcome" in out.stdout


def test_publish_refuses_a_junit_without_the_aggregate_attestation(
        tmp_path: Path, repo: Path):
    b = _bundle(tmp_path, repo,
                junit=_junit(tmp_path / "noagg.xml", aggregate=False))
    out = _publish(b)
    assert out.returncode != 0
    assert "aggregate process attestation" in out.stdout


def test_publish_refuses_a_dirty_worktree(tmp_path: Path, repo: Path):
    b = _bundle(tmp_path, repo)
    (repo / "src" / "thing.py").write_text("VALUE = 3\n")
    out = _publish(b)
    assert out.returncode != 0
    assert "not exactly HEAD" in out.stdout


# ------------------------------------------------ read-time re-validation


@pytest.mark.parametrize("corrupt", ["xml", "log", "selection", "manifest"])
def test_a_damaged_bundle_is_refused_when_it_is_read(tmp_path: Path,
                                                     repo: Path,
                                                     corrupt: str):
    """Validation is re-run at READ time, never trusted from write time.

    A bundle is written once and read by later rounds. Anything that can
    happen to a file in between — truncation, a partial disk, a hand edit —
    must present as a MISS rather than as evidence.
    """
    b = _bundle(tmp_path, repo)
    assert _publish(b).returncode == 0
    material = cache.key_material(repo, PLUGIN, b["selection"], b["harness"],
                                 b["contract"])
    prefix = str(cache._prefix(b["cache_dir"], dict(material)["head"],
                               cache.key_digest(material)))
    if corrupt == "xml":
        _junit(Path(prefix + ".xml"), red_file=SELECTED[1])
    elif corrupt == "log":
        _log(Path(prefix + ".log"), guard=False)
    elif corrupt == "selection":
        Path(prefix + ".selection").write_text("programs/tests/test_other.py\n")
    elif corrupt == "manifest":
        Path(prefix + ".manifest").write_text("schema=0-forged\nrc=0\n")
    got = _lookup(b, tmp_path)
    assert got.returncode != 0, f"a {corrupt}-damaged bundle was served"
    assert got.stdout.startswith("MISS")


def test_the_program_reports_a_miss_rather_than_raising(tmp_path: Path):
    """Confusion must present as a MISS. This program is on the landing path."""
    got = _run(["lookup", "--repo", str(tmp_path / "nope"), "--plugin",
                str(PLUGIN), "--selection", str(tmp_path / "nope.txt"),
                "--harness", str(tmp_path / "nope.sh"), "--contract", "c",
                "--cache-dir", str(tmp_path / "cache"), "--junit-out",
                str(tmp_path / "o.xml"), "--log-out", str(tmp_path / "o.log")])
    assert got.returncode != 0
    assert got.stdout.startswith("MISS")
