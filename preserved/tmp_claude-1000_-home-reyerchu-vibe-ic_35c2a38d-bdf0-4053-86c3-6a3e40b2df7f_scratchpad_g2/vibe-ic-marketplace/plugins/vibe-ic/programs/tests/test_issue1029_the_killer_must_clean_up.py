"""A gate killed mid-write leaves the write; the process that killed it must undo it. vibe-ic#1029.

`gate_host_independence_check.audit()` drives EVERY gate in
`repo_hygiene_gates.sh` twice — ARM A with `cwd` = THE WORKING CHECKOUT — under
`subprocess.run(..., timeout=600)`. On expiry `subprocess.run` calls
`Popen.kill()`, which is **SIGKILL**. A SIGKILLed process runs no `finally` and
no signal handler, so a gate inside its own mutation window when the bound lands
leaves the mutation in the tree. `TimeoutExpired` is a `SubprocessError`, so the
loop caught it, filed `GATE_UNRUNNABLE`, and carried on with a corrupt checkout.

REPRODUCED 2026-08-12 from a real landing run on .120 (candidate stack h1c,
`/home/reyerchu/_pg_h1c`), byte for byte:

    parent caught TimeoutExpired after 75s
    porcelain AFTER: 1
     M vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
    -    return _detect_pdk(project, override="sky130A")
    +    return _detect_pdk(project, override="nangate45")

`an argued direction is pinned` needs 543 s here against the 600 s bound, and
`phase3_one_shot_runner.py:8414` is the LAST site it processes in sort order —
so it is the site holding a mutation when the bound lands, which is the file
.120 was left carrying.

WHICH CAUSE IT IS, because the candidates need different fixes and three were
ruled out by measurement rather than by reading:

    exception raised mid-pin      file restored BYTE-IDENTICAL   the `finally` works
    SIGTERM (with #1090)          file restored, child rc -15    the handler works
    subprocess.run(timeout=)      LEFT MUTATED                   <-- this one
    same, with #1090 applied      STILL LEFT MUTATED             SIGKILL is uncatchable

So the fix cannot live in the killed gate: no code of its runs. The only process
still alive is the one that sent the signal, and this is it.

THE ASYMMETRY THAT MAKES IT DANGEROUS: on .120 it failed loudly, but only
because `suite_write_guard` runs at the END of the full tier. Everything between
`gates are host-independent` (`:678`) and that check — ~30 gates, including
`an argued direction is pinned` itself at `:964` — measured a mutated
`phase3_one_shot_runner.py` and reported normally, with nothing saying its
subject had been altered.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import gate_host_independence_check as G  # noqa: E402

#: Fixture gates return instantly or sleep; this only stops a hung one from
#: taking the session down, and stays under the 60 s ceiling
#: `ci_harness_timeout_ceiling_check` enforces.
_T = 55


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "programs").mkdir(parents=True)
    (r / "programs" / "shipped.py").write_text('PDK = "sky130A"\n')
    (r / "programs" / "other.py").write_text("x = 1\n")
    (r / ".gitignore").write_text("__pycache__/\n")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    return r


def _mutating_gate(r: Path, sleep: float = 30.0) -> Path:
    """A gate with the pin gate's shape: mutate a tracked file, then work.

    The script lives OUTSIDE the subject: a harness that writes its own driver
    into the tree it measures is the defect this file is about."""
    p = r.parent / "gate.py"
    p.write_text(textwrap.dedent(f"""\
        import pathlib, time
        t = pathlib.Path({str(r / "programs" / "shipped.py")!r})
        orig = t.read_text()
        try:
            t.write_text(orig.replace("sky130A", "nangate45"))
            time.sleep({sleep})
        finally:
            t.write_text(orig)
        """))
    return p


def _drive_and_repair(r: Path, gate: Path, timeout: float):
    """`audit()`'s ARM A block, verbatim in shape: drive, then repair."""
    before = G._checkout_dirty_paths(r)
    exc = None
    try:
        subprocess.run([sys.executable, str(gate)], cwd=str(r),
                       capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        exc = e
    repaired, refused = G._repair_checkout(r, before, "a mutating gate")
    return exc, repaired, refused


def _porcelain(r: Path) -> str:
    return subprocess.run(["git", "-C", str(r), "status", "--porcelain"],
                          capture_output=True, text=True).stdout.strip()


# --------------------------------------------------------------------------
# the defect, and the red arm the fix has to survive
# --------------------------------------------------------------------------
def test_a_gate_sigkilled_mid_write_is_undone_by_the_process_that_killed_it(tmp_path):
    r = _repo(tmp_path)
    gate = _mutating_gate(r, sleep=30.0)
    exc, repaired, refused = _drive_and_repair(r, gate, timeout=3.0)

    assert isinstance(exc, subprocess.TimeoutExpired), (
        f"the fixture did not reproduce the kill, so it proves nothing: {exc!r}")
    assert "programs/shipped.py" in repaired, (
        "the gate was killed inside its mutation window and the checkout was "
        f"left carrying the mutation:\nrepaired={repaired} refused={refused}\n"
        f"porcelain={_porcelain(r)!r}")
    assert _porcelain(r) == "", (
        f"the tree is still dirty after the repair: {_porcelain(r)!r}")
    assert 'PDK = "sky130A"' in (r / "programs" / "shipped.py").read_text()


def test_without_the_repair_the_mutation_survives(tmp_path):
    """The bidirectional control. If the kill did not actually leave a write,
    the test above would pass against code that does nothing."""
    r = _repo(tmp_path)
    gate = _mutating_gate(r, sleep=30.0)
    try:
        subprocess.run([sys.executable, str(gate)], cwd=str(r),
                       capture_output=True, text=True, timeout=3.0)
    except subprocess.TimeoutExpired:
        pass
    assert _porcelain(r) != "", (
        "SIGKILL mid-write left the tree CLEAN — then there is no defect here "
        "and the repair above is measuring nothing")
    assert "nangate45" in (r / "programs" / "shipped.py").read_text()


# --------------------------------------------------------------------------
# the boundary: an over-eager repair would destroy a maintainer's work
# --------------------------------------------------------------------------
def test_a_path_already_dirty_before_the_drive_is_never_touched(tmp_path):
    r = _repo(tmp_path)
    (r / "programs" / "other.py").write_text("x = 'my work in flight'\n")
    mine = (r / "programs" / "other.py").read_text()
    gate = _mutating_gate(r, sleep=30.0)
    _drive_and_repair(r, gate, timeout=3.0)
    assert (r / "programs" / "other.py").read_text() == mine, (
        "the repair reverted a file the maintainer had already edited — that "
        "is worse than the leftover it was cleaning up")


def test_an_untracked_path_is_named_and_not_deleted(tmp_path):
    """A gate writing its own report beside the code is doing the thing the
    corpus guard's message recommends. Undoing a modification this run caused
    is one licence; deleting files is another, and it is not held here."""
    r = _repo(tmp_path)
    g = r.parent / "g.py"
    g.write_text(f"import pathlib;"
                 f"pathlib.Path({str(r / 'programs' / 'report.json')!r})"
                 f".write_text('{{}}')\n")
    _, repaired, refused = _drive_and_repair(r, g, timeout=_T)
    assert (r / "programs" / "report.json").exists(), "the repair deleted a file"
    assert any("report.json" in x for x in refused), refused
    assert not repaired, repaired


def test_a_read_only_gate_produces_no_finding(tmp_path):
    """False-positive control. Without it the repair could be `return ['x'], []`."""
    r = _repo(tmp_path)
    g = r.parent / "g.py"
    g.write_text("print('PASS (1 item examined)')\n")
    exc, repaired, refused = _drive_and_repair(r, g, timeout=_T)
    assert exc is None and not repaired and not refused, (
        f"a gate that only reads was reported as corrupting the checkout: "
        f"{repaired} {refused}")


def test_a_gate_that_restores_cleanly_produces_no_finding(tmp_path):
    """The pin gate on a NORMAL run mutates and puts the file back. That must
    not be reported — otherwise this fires on every tier and gets routed
    around."""
    r = _repo(tmp_path)
    gate = _mutating_gate(r, sleep=0.05)
    exc, repaired, refused = _drive_and_repair(r, gate, timeout=_T)
    assert exc is None, exc
    assert not repaired and not refused, (
        f"a gate that restored its own write was flagged: {repaired} {refused}")


def test_an_unreadable_tree_repairs_nothing_rather_than_the_wrong_thing(tmp_path):
    d = tmp_path / "notarepo"
    (d / "programs").mkdir(parents=True)
    (d / "programs" / "shipped.py").write_text("x = 1\n")
    assert G._checkout_dirty_paths(d) == {}
    repaired, refused = G._repair_checkout(d, {}, "x")
    assert not repaired and not refused
