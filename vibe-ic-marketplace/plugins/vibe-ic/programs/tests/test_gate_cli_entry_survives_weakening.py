"""A gate this commit touches must still be unable to pass while broken.

The 63x8 matrix asks whether a STEP is wired, falsifiable, declares what it
produces.  It does not ask whether the PROGRAM behind that step can be weakened
without anything noticing — and those are different facts.  A survey found five
gates where the second was false while the first was true: 40 matrix cells read
ENFORCED over gates that could be neutered in silence.

Running the full survey costs about ten minutes, which is the wrong price for
every commit and the right price for none.  This guard pays it only where the
risk is: the gate programs THIS working tree changes.  A commit that touches no
gate program costs one canary probe; a commit that weakens one is refused at the
moment it would land.

The canary is not decoration.  Without it, a probe that had stopped working —
an entry shape it no longer recognises, a pytest invocation that no longer runs
anything — would report a clean survey by doing nothing, and this file would
become the thing it exists to prevent.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).resolve().parents[1]
#: Bound for a probe subprocess. MEASURED on this tree: the two probe-driving
#: tests take 1.71 s and 1.43 s. The 600 s I first wrote was decoration — it is
#: above the 60 s ceiling `ci_harness_timeout_ceiling_check` enforces, so it
#: could never fire: pytest kills the SESSION at 180 s first, taking every
#: other file in the subset with it. 45 s keeps ~26x headroom over the measured
#: time and stays under the ceiling.
_PROBE_TIMEOUT_S = 45
PLUGIN_ROOT = PROGRAMS_DIR.parent
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PROGRAMS_DIR))
import gate_cli_mutation_probe as PROBE  # noqa: E402

_GATE_CLAUSES = ("program_exit_zero", "advisory_program_exit_zero",
                 "optional_program_exit_zero")

#: Probed on every run regardless of what changed.  Chosen because its gate is
#: blocking and its tests drive the CLI, so a CAUGHT here means the machinery
#: works end to end.
_CANARY = "perc_signoff_check"


def _gate_programs() -> set:
    """Every program the flow names in a gate clause."""
    import yaml
    doc = yaml.safe_load(FLOW_YAML.read_text())
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _GATE_CLAUSES:
                    cmd = value.get("command") if isinstance(value, dict) else value
                    if isinstance(cmd, str):
                        m = re.match(r"\s*([A-Za-z0-9_]+)", cmd)
                        if m:
                            found.add(m.group(1))
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for step in doc["steps"]:
        walk(step.get("gate"))
    return found


def _changed_gate_programs() -> list:
    """Gate programs this working tree changes, against the upstream baseline.

    Returns [] when the baseline cannot be resolved — a shallow CI checkout, a
    detached build.  That is a real limit and it is why the canary exists: this
    guard degrades to "the probe still works", never to "nothing was checked".
    """
    gates = _gate_programs()
    for base in ("origin/main", "main"):
        try:
            r = subprocess.run(
                ["git", "diff", "--name-only", f"{base}...HEAD"],
                cwd=PLUGIN_ROOT, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return []
        if r.returncode != 0:
            continue
        break
    else:
        return []
    changed = set()
    for line in list(r.stdout.split("\n")) + _dirty():
        p = Path(line.strip())
        if p.suffix == ".py" and p.parent.name == "programs" and p.stem in gates:
            changed.add(p.stem)
    return sorted(changed)


def _dirty() -> list:
    """Uncommitted changes count too — the guard should fire before the commit."""
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=PLUGIN_ROOT,
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    return [line[3:].strip() for line in r.stdout.split("\n") if line.strip()]


_TARGETS = sorted({_CANARY, *_changed_gate_programs()})


def test_the_flow_names_gate_programs_this_guard_can_find():
    """If the clause vocabulary moves, this guard would silently watch nothing."""
    gates = _gate_programs()
    assert len(gates) > 100, (
        "only %d gate programs found in the flow — the clause names this guard "
        "walks (%s) no longer match the yaml, so it is watching almost nothing"
        % (len(gates), ", ".join(_GATE_CLAUSES)))
    assert _CANARY in gates, (
        "the canary %r is no longer a gate program; pick another blocking gate "
        "whose tests drive its CLI" % _CANARY)


@pytest.mark.parametrize("program", _TARGETS)
def test_neutering_the_gate_reddens_something(program):
    """Make it unable to fail, and require a test to notice.

    SILENT is the finding.  NO_TEST / NO_ENTRY are failures of the MEASUREMENT
    and are reported as such — a probe that could not run has not cleared the
    gate, and saying so is the difference between this guard and the static
    proxy that was rejected for producing two false comforts.
    """
    result = PROBE.probe(program)
    state = result["state"]
    if state == "CAUGHT":
        return
    if state == "SILENT":
        pytest.fail(
            "%s can be made unable to fail and nothing reddens.\n"
            "  entry neutered: %s\n"
            "  test files run: %s\n"
            "The flow reads this program's EXIT CODE. A test that calls audit() "
            "measures the finding and leaves the verdict-to-exit-code mapping "
            "unmeasured. Add a test that runs it as a subprocess on an input it "
            "should refuse, and assert the exit code the flow would act on."
            % (program, result.get("entry"), ", ".join(result.get("tests", []))))
    pytest.fail(
        "%s was NOT PROBED (%s) — the measurement failed, which is not the same "
        "as the gate being protected. Fix the probe rather than reading this as "
        "a pass." % (program, state))


def test_no_gate_is_left_neutered_in_the_tree():
    """A killed probe cannot reach its `finally`.

    Measured: one did, and the next run then read the NEUTERED file as its
    original and restored to it — the weakening compounding one line per killed
    run, invisibly, in a gate the flow depends on. The probe now refuses a file
    that already carries the marker and leaves a sidecar while it works; this
    asserts neither is sitting in the tree.
    """
    stale = PROBE.stale_backups()
    assert not stale, (
        "a probe was interrupted and left %d backup(s): %s\n"
        "Restore each program from its sidecar (or from git) and delete the "
        "sidecar before trusting any result in this file."
        % (len(stale), ", ".join(p.name for p in stale)))
    marked = [p.name for p in PROGRAMS_DIR.glob("*.py")
              if p.name != "gate_cli_mutation_probe.py"
              and "# NEUTERED" in p.read_text(errors="replace")]
    assert not marked, (
        "these programs carry the probe's NEUTERED marker and cannot fail: %s"
        % ", ".join(marked))

# --- #547 review: the probe must not mutate the tree other sessions read -----

def test_the_default_run_never_touches_the_shipped_programs_tree(tmp_path):
    """A neutered gate returns 0, so a concurrent reader sees a PASS it did not
    earn. That is worse than the same-shaped hazard measured at v1.7.97, where
    an injected file made other sessions FAIL — wrong, but loud. This one is
    quiet and green, for exactly the class of check whose job is to be able to
    fail.

    Asserted on `git status` of the shipped tree across a real probe run, not on
    the presence of a `--programs-root` flag: the flag existing proves nothing
    about which path the default takes.
    """
    import subprocess as sp
    def dirt():
        r = sp.run(["git", "status", "--porcelain", "programs"],
                   cwd=PLUGIN_ROOT, capture_output=True, text=True, timeout=60)
        return r.stdout
    before = dirt()
    r = sp.run([sys.executable, str(PROGRAMS_DIR / "gate_cli_mutation_probe.py"),
                "spec_declaration_emit"],
               cwd=PLUGIN_ROOT, capture_output=True, text=True,
               timeout=_PROBE_TIMEOUT_S)
    assert dirt() == before, (
        "the probe modified the shipped programs tree; while a gate is neutered "
        "any concurrent reader of it gets an unearned PASS\n" + dirt())
    assert "CAUGHT" in r.stdout or "SILENT" in r.stdout, (
        "the probe did not reach a verdict, so the no-dirt assertion above "
        "proves only that it did nothing:\n" + r.stdout + r.stderr)


# --- 2026-08-04: the CLI was safe and the API was not ------------------------

def test_the_probe_FUNCTION_never_touches_the_shipped_tree_either():
    """`main()` copied the tree; `probe()` did not — and `probe()` is what the
    parametrised test above calls.

    That is how `hold_area_budget_check.py` and `hold_corner_coverage_check.py`
    came to be sitting in a shared checkout with an injected early return: this
    very file drove the API on them and the run was killed. Asserted through
    the API, on the real tree, because the CLI-shaped test above passed
    throughout the window in which the damage was being done.
    """
    import hashlib
    import threading
    import time

    target = PROGRAMS_DIR / "hold_area_budget_check.py"
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    seen, result = [], {}

    # SAMPLED WHILE IT RUNS, not compared before and after. The pre-fix code
    # restored in a `finally`, so a before/after comparison passes over it —
    # that is exactly why the CLI-shaped test above stayed green through the
    # whole period in which the API was mutating the shipped tree. The window
    # is what matters: while it is open, every concurrent reader of this gate
    # gets an exit code it did not earn.
    t = threading.Thread(
        target=lambda: result.update(PROBE.probe("hold_area_budget_check")),
        daemon=True)
    t.start()
    while t.is_alive():
        try:
            seen.append(hashlib.sha256(target.read_bytes()).hexdigest())
        except OSError:
            seen.append("MISSING")
        time.sleep(0.01)
    t.join(timeout=_PROBE_TIMEOUT_S)

    assert set(seen) <= {expected}, (
        "the shipped gate changed on disk while PROBE.probe() ran; for that "
        "window any concurrent reader of it got an unearned exit code, and a "
        "kill inside it leaves the tree that way permanently")
    assert len(seen) > 1, (
        "the probe finished before a single sample was taken, so nothing was "
        "observed")
    assert result.get("state") in ("CAUGHT", "SILENT"), (
        "no verdict was reached, so the sampling above proves only that "
        "nothing happened: %s" % result)


def test_a_SIGKILL_mid_probe_leaves_the_repository_byte_identical(tmp_path):
    """The only test that can distinguish this fix from the `finally` it
    replaces.

    The `finally` in `probe()` was correct before this change and is correct
    after it. It was never the problem — it does not run on `SIGKILL`, which is
    how a long agent session ends a subprocess. So the process is killed HERE,
    inside the window in which the mutation is on disk, and the assertion is
    that the repository never held it.
    """
    import hashlib
    import os
    import signal
    import subprocess as sp
    import time

    target = PROGRAMS_DIR / "hold_area_budget_check.py"
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    # ONLY A DIRECTORY THIS RUN CREATED counts. A previous run of THIS test
    # kills its child and therefore leaves one behind, and matching that stale
    # one made the test pass in 0.7s without the child ever reaching its
    # mutation window — measured, while mutation-proving this very assertion.
    # Look where the probe ACTUALLY writes, not where /tmp happens to be. The
    # probe reserves its scratch through _crash_safe_scratch, whose root is
    # `tempfile.gettempdir()` — i.e. it honours TMPDIR. This test hardcoded
    # "/tmp", so under any harness that sets TMPDIR (pytest's own --basetemp
    # wrapper, tox, CI, and every run in this repo's pinned invocation) the
    # scratch was created somewhere this loop never looked. The failure that
    # produced was not "not found": it was the assertion below announcing that
    # the mutation is being applied to the REPOSITORY — the single most alarming
    # message this file can emit, fired by an environment variable. Measured,
    # single variable, same commit and same worktree:
    #     TMPDIR set    -> 1 failed
    #     TMPDIR unset  -> 1 passed
    # Importing the probe's own root keeps the two from drifting apart again.
    import _crash_safe_scratch as _scratch_root
    tmp_root = _scratch_root._tmp_root()
    prior = set(tmp_root.glob("gate_cli_probe_*"))
    child = sp.Popen(
        [sys.executable, "-c",
         "import sys;sys.path.insert(0, %r)\n"
         "import gate_cli_mutation_probe as P\n"
         "P.probe('hold_area_budget_check')\n" % str(PROGRAMS_DIR)],
        start_new_session=True, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    try:
        # Wait for the mutation to be ON DISK somewhere. Killing before the
        # write would make this test pass without ever entering the window.
        scratch = None
        deadline = time.time() + _PROBE_TIMEOUT_S
        while time.time() < deadline and child.poll() is None:
            for d in set(tmp_root.glob("gate_cli_probe_*")) - prior:
                if (d / "programs" / ("hold_area_budget_check.py"
                                      + PROBE._BACKUP_SUFFIX)).exists():
                    scratch = d
                    break
            if scratch:
                break
            time.sleep(0.02)
        assert scratch is not None, (
            "the probe never entered its mutation window in a NEW scratch "
            "directory, so the kill below would prove nothing — which is what "
            "happens when the mutation is being applied to the repository "
            "instead")
        os.killpg(os.getpgid(child.pid), signal.SIGKILL)
    finally:
        # KILL FIRST, then wait. A bare `wait` here leaves the child running
        # when the assertion above fails — and if the probe is mutating the
        # SHIPPED tree at that moment (which is precisely the state that makes
        # the assertion fail), the orphan goes on doing it into the next test.
        # Measured while mutation-proving this file: it turned the restored run
        # red for a reason that belonged to the harness.
        try:
            os.killpg(os.getpgid(child.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        child.wait(timeout=_PROBE_TIMEOUT_S)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before, (
        "a SIGKILL mid-probe changed a shipped gate — the exact state found "
        "by hand twice on 2026-08-04")
    assert not list(PROGRAMS_DIR.glob("*" + PROBE._BACKUP_SUFFIX)), (
        "a killed probe left a sidecar in the repository")
    # The killed child could not clean up after itself; the reaper does. Run it
    # here so this test does not leave the litter it is written about.
    import _crash_safe_scratch as _S
    _S.reap(PROBE._SCRATCH_PREFIX)
    assert not scratch.exists(), (
        "the killed run's scratch survived the reaper: %s" % scratch)


def test_there_is_no_flag_that_mutates_the_shipped_tree():
    """`--in-place` was the escape hatch, and it is the one that got used.

    Driven through argparse rather than read out of the source: a flag can be
    removed from the help text and still be accepted.
    """
    import subprocess as sp
    r = sp.run([sys.executable, str(PROGRAMS_DIR / "gate_cli_mutation_probe.py"),
                "--in-place", "spec_declaration_emit"],
               cwd=str(PLUGIN_ROOT), capture_output=True, text=True,
               timeout=_PROBE_TIMEOUT_S)
    assert r.returncode == 2 and "unrecognized arguments" in r.stderr, (
        "the probe still accepts a flag that mutates the shipped tree; there "
        "is no crash-safe version of that, which is why it was removed:\n"
        + r.stdout + r.stderr)


def test_the_probe_can_still_report_SILENT(tmp_path):
    """CONTROL. Without this, CAUGHT on every real gate is indistinguishable
    from a probe that always says CAUGHT. Same gate, a copy whose test file
    keeps the NAME (so it is still selected) but has been blunted."""
    import shutil, subprocess as sp
    root = tmp_path / "programs"
    shutil.copytree(PROGRAMS_DIR, root,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    hit = 0
    for f in (root / "tests").glob("test_*.py"):
        if "spec_declaration_emit" in f.read_text():
            f.write_text("import spec_declaration_emit  # noqa: F401\n\n"
                         "def test_placeholder():\n    assert True\n")
            hit += 1
    assert hit, "no test file names the program — the control is vacuous"
    r = sp.run([sys.executable, str(PROGRAMS_DIR / "gate_cli_mutation_probe.py"),
                "spec_declaration_emit", "--programs-root", str(root)],
               cwd=PLUGIN_ROOT, capture_output=True, text=True,
               timeout=_PROBE_TIMEOUT_S)
    assert "SILENT" in r.stdout, (
        "a gate whose tests cannot see it was neutered still reported CAUGHT — "
        "the probe is asserting, not measuring:\n" + r.stdout + r.stderr)


def test_the_probe_finds_tests_when_they_sit_beside_the_programs():
    """`--programs-root` exists to point this probe at another tree, and it only
    half worked.

    vibeic-eda keeps its gates and its tests in the SAME directory, so all five
    of its gates came back NO_TEST — reported honestly as "a gap in the
    MEASUREMENT, not a verdict", and still five gates unprobed for a reason
    belonging to this program rather than to them. Pointed properly it found two
    SILENT gates immediately, one of them real: `check_pins_current` had eleven
    tests and none drove `main()`.
    """
    import gate_cli_mutation_probe as P
    import inspect
    src = inspect.getsource(P.probe if hasattr(P, "probe") else P)
    assert 'root / "tests" if (root / "tests").is_dir() else root' in src, \
        ("tests_dir is pinned to root/tests, so a tree that keeps its tests "
         "beside its programs reports NO_TEST for every gate")


def test_naming_tests_accepts_an_explicit_directory(tmp_path):
    """The parameter that makes the fallback usable — asserted by driving it."""
    import gate_cli_mutation_probe as P
    t = tmp_path / "test_thing.py"
    t.write_text("import my_gate as M\n\ndef test_x():\n    M.main([])\n")
    found = P.naming_tests("my_gate", tmp_path)
    assert [p.name for p in found] == ["test_thing.py"]
    assert P.naming_tests("other_gate", tmp_path) == []
