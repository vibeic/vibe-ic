"""§4.05 must be a mechanism, not a rule someone enforces by noticing. #1079.

THE RED ARM IS THE DELIVERABLE. `test_a_step_reaching_for_the_golden_SUCCEEDS_
with_enforcement_off` is not a test of this change — it is the demonstration
that today, on main, a step can read the golden and nothing stops it. If that
test ever fails, the hole closed by some other route and this file should be
re-derived rather than repaired.

The paired arm (`..._FAILS_with_enforcement_on`) is the same step, the same
path, the same process, one environment variable apart.

WHAT IS AND IS NOT COVERED — asserted here, not only described in prose, so the
bound cannot quietly widen into an implied guarantee:

  * a NON-Python child is NOT covered (`test_a_non_python_child_is_not_covered`).
    A Python audit hook does not exist inside an OpenROAD/Tcl process;
  * a child that resets PYTHONPATH or runs `-S`/`-I` is NOT covered
    (`test_a_child_that_drops_pythonpath_is_not_covered`);
  * paths OUTSIDE the project are NOT covered, deliberately, so the hook stays
    cheap and cannot break the interpreter's own imports.

Those three tests exist to keep the limit HONEST. A future reader who deletes
them because "they assert a weakness" removes the only executable statement of
where this mechanism stops.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PROGRAMS))
import step_input_scope as sis  # noqa: E402
import _watchdog as wd          # noqa: E402


GOLDEN_REL = "score/testbench.v"
GOLDEN_BODY = "// the oracle\nmodule tb; endmodule\n"
INPUT_REL = "phase2/stage1/rtl/top.v"
INPUT_BODY = "module top; endmodule\n"


@pytest.fixture()
def project(tmp_path):
    p = tmp_path / "proj"
    (p / "score").mkdir(parents=True)
    (p / GOLDEN_REL).write_text(GOLDEN_BODY)
    (p / INPUT_REL).parent.mkdir(parents=True)
    (p / INPUT_REL).write_text(INPUT_BODY)
    return p


def _reader(tmp_path, rel):
    """A step that reaches for `rel` and prints what it got."""
    f = tmp_path / f"reader_{abs(hash(rel))}.py"
    f.write_text(textwrap.dedent(f"""
        import os, sys
        root = os.environ["PROJ"]
        with open(os.path.join(root, {rel!r})) as fh:
            sys.stdout.write("READ:" + fh.read())
    """))
    return f


def _run(script, project, *, on, step="14", guard=None, extra_env=None):
    env = dict(os.environ)
    env["PROJ"] = str(project)
    env.pop(sis.ENV_SWITCH, None)
    if on:
        env[sis.ENV_SWITCH] = "1"
    env.update(extra_env or {})
    return wd.run_supervised(
        [sys.executable, str(script)], env=env,
        scope_project=project, scope_step=step,
        scope_guard_dir=guard or (Path(project).parent / f"guard_{on}_{step}"),
        stall_grace_s=120, hard_ceiling_s=180)


# ---------------------------------------------------------------------------
# THE TWO ARMS
# ---------------------------------------------------------------------------
def test_a_step_reaching_for_the_golden_SUCCEEDS_with_enforcement_off(
        tmp_path, project):
    """TODAY'S HOLE, executed. Nothing here is asserted about our fix; this is
    the state of main, and it is the reason #1079 exists."""
    res = _run(_reader(tmp_path, GOLDEN_REL), project, on=False)
    assert res.rc == 0, res.err
    assert "READ:" in res.out and "the oracle" in res.out, res.out
    assert res.scope.get("enforced") is False, res.scope


def test_the_same_step_FAILS_with_enforcement_on(tmp_path, project):
    res = _run(_reader(tmp_path, GOLDEN_REL), project, on=True)
    assert res.rc != 0, (
        "the step read the golden with enforcement ON — the mechanism did not "
        f"act.\nout={res.out}\nerr={res.err}")
    assert "the oracle" not in res.out, res.out
    assert "4.05" in res.err or "PermissionError" in res.err, res.err
    assert res.scope.get("enforced") is True, res.scope


def test_a_legitimate_step_reading_a_declared_input_still_passes(
        tmp_path, project):
    """THE PAIRED GUARD. Without this arm the above is a ban, not a check."""
    res = _run(_reader(tmp_path, INPUT_REL), project, on=True)
    assert res.rc == 0, (
        f"enforcement broke a step reading an ordinary, non-oracle input.\n"
        f"out={res.out}\nerr={res.err}")
    assert "module top" in res.out, res.out


def test_a_declared_required_input_overrides_the_deny(tmp_path, project):
    """The declaration site is the flow, and it WINS. A step that declares an
    oracle-shaped path in `required_inputs` may read it — otherwise the
    mechanism would forbid what the flow requires."""
    specs = [GOLDEN_REL]
    assert sis.denies(GOLDEN_REL, []) is not None, "premise: normally denied"
    assert sis.denies(GOLDEN_REL, specs) is None, (
        "a declared input was still denied; the declaration must override")


# ---------------------------------------------------------------------------
# THE STATED LIMITS, asserted so they cannot widen silently
# ---------------------------------------------------------------------------
def test_a_non_python_child_is_not_covered(tmp_path, project):
    """An OpenROAD/Tcl/yosys child is not subject to a Python audit hook.
    Asserted, because a mechanism that implies completeness is a new lie."""
    sh = tmp_path / "reader.sh"
    sh.write_text(f'#!/bin/sh\ncat "$PROJ/{GOLDEN_REL}"\n')
    sh.chmod(0o755)
    env = dict(os.environ, PROJ=str(project))
    env[sis.ENV_SWITCH] = "1"
    res = wd.run_supervised(
        ["sh", str(sh)], env=env, scope_project=project, scope_step="14",
        scope_guard_dir=tmp_path / "g_sh", stall_grace_s=120,
        hard_ceiling_s=180)
    assert res.rc == 0 and "the oracle" in res.out, (
        "the non-Python child was blocked — good news, but the module's stated "
        "limit is now wrong and must be rewritten rather than left claiming "
        "less than it does")


def test_a_child_that_skips_site_is_not_covered(tmp_path, project):
    """The guard rides on `sitecustomize`, so a child started with `-S` never
    installs it.

    The first draft of this test asserted the limit as "a child that clears
    PYTHONPATH escapes", and it FAILED: `child_env` prepends the guard dir
    AFTER the caller's environment is assembled, so clearing the variable
    upstream does not defeat it. Recording that here because the correction
    runs the other way from the usual one — the mechanism was stronger than
    the limit I wrote for it, and an unfixed test would have understated it.
    """
    env = dict(os.environ, PROJ=str(project))
    env[sis.ENV_SWITCH] = "1"
    res = wd.run_supervised(
        [sys.executable, "-S", str(_reader(tmp_path, GOLDEN_REL))],
        env=env, scope_project=project, scope_step="14",
        scope_guard_dir=tmp_path / "g_S", stall_grace_s=120,
        hard_ceiling_s=180)
    assert res.rc == 0 and "the oracle" in res.out, (
        "`-S` was blocked too — the stated limit is wrong and must be "
        f"rewritten rather than left claiming less than it does.\n{res.err}")


def test_a_path_outside_the_project_is_not_covered(tmp_path, project):
    outside = tmp_path / "elsewhere_test.v"
    outside.write_text("// outside\n")
    script = tmp_path / "outside_reader.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        with open({str(outside)!r}) as fh:
            sys.stdout.write("READ:" + fh.read())
    """))
    res = _run(script, project, on=True)
    assert res.rc == 0 and "outside" in res.out, res.err


# ---------------------------------------------------------------------------
# OFF is BYTE-IDENTICAL — the blast-radius property
# ---------------------------------------------------------------------------
def test_with_the_switch_unset_the_environment_is_untouched():
    base = {"A": "1", "PATH": "/usr/bin"}
    env, meta = sis.child_env(base, project=Path("/tmp"), step_id="14")
    assert env is base and meta == {"enforced": False}


def test_a_caller_passing_no_env_still_inherits_when_off(monkeypatch):
    """`None` must stay `None`. Turning it into a dict would change what every
    unscoped child inherits — the way to break every step at once.

    The switch is cleared EXPLICITLY rather than assumed absent: with
    `base_env=None`, `enforcement_enabled` falls back to `os.environ`, so this
    test read the ambient switch and failed when the blast-radius measurement
    exported it globally. The premise has to be established, not inherited.
    """
    monkeypatch.delenv(sis.ENV_SWITCH, raising=False)
    env, meta = sis.child_env(None, project=Path("/tmp"), step_id="14")
    assert env is None and meta["enforced"] is False


def test_run_supervised_without_a_step_id_does_not_scope():
    res = wd.run_supervised([sys.executable, "-c", "print('hi')"])
    assert res.rc == 0 and res.scope == {"enforced": False}


# ---------------------------------------------------------------------------
# the declaration comes from the FLOW, not a second list
# ---------------------------------------------------------------------------
def test_the_scope_is_read_from_the_flow_yaml():
    specs = sis.declared_scope("14", FLOW)
    assert specs, "step 14 declares required_inputs in the flow; none were read"


def test_an_unknown_step_declares_nothing_rather_than_everything():
    """Fail CLOSED: an id the flow does not carry gets no carve-out, so the
    deny-list still applies. The opposite would make a typo an exemption."""
    assert sis.declared_scope("no-such-step", FLOW) == []


def test_env_values_naming_the_oracle_are_removed(tmp_path, project):
    env = {"GOLDEN": str(project / GOLDEN_REL), "RTL": str(project / INPUT_REL)}
    out, removed = sis.scrub_env(env, project, [])
    assert "GOLDEN" not in out and removed == ["GOLDEN"], (out, removed)
    assert out["RTL"] == env["RTL"], "a legitimate path was stripped"


# ---------------------------------------------------------------------------
# THE BYPASS — recovered from #1105, retargeted to THIS mechanism
# ---------------------------------------------------------------------------
# #1105 (`step_input_scope_enforce.py`, independent lineage) carried
# `test_the_hook_sees_a_read_that_BYPASSES_the_python_open_name`. Consolidating
# onto #1158's `step_input_scope.py` cannot port that file — it imports a module
# this branch does not carry, and a straight copy aborts COLLECTION, which greps
# as zero failures and reads as a clean baseline.
#
# The PROPERTY, though, survives the change of mechanism and was the one thing
# genuinely lost. This module already relies on it in writing:
#
#   :56  "FILESYSTEM covered for PYTHON children, by an audit hook
#         (`sys.addaudithook`, …)"
#   :70  a stated limit — "a read through a route that is not the `open` audit
#         event"
#
# A rebound `builtins.open` would be defeated by a child that never touches the
# NAME. `sys.addaudithook` is not, because CPython raises the `open` event from
# C under `os.open` too. Nothing on this branch drove a descriptor-level read,
# so the difference between "we hooked a name" and "we hooked the event" was
# unmeasured — and those two have identical behaviour on every other test here.
def test_a_descriptor_level_read_does_not_get_past_the_hook(tmp_path, project):
    """`os.open` never touches `builtins.open`, and must still be denied.

    This is what distinguishes the audit-hook mechanism from rebinding a name:
    every other test in this file would pass equally well against a rebound
    `builtins.open`, and this one would not.
    """
    script = tmp_path / "descriptor_reader.py"
    script.write_text(textwrap.dedent(f"""
        import os, sys
        root = os.environ["PROJ"]
        try:
            fd = os.open(os.path.join(root, {GOLDEN_REL!r}), os.O_RDONLY)
        except PermissionError:
            sys.exit(3)
        os.close(fd)
        sys.stdout.write("READ-BY-DESCRIPTOR")
        sys.exit(0)
    """))
    res = _run(script, project, on=True, step="14", guard=tmp_path / "g_fd")
    assert res.rc != 0, (
        "a descriptor-level read of the oracle was allowed with enforcement ON "
        "— the boundary is hooking the `open` NAME rather than the audit "
        f"event, so any child using os.open walks past it.\nout={res.out}\n"
        f"err={res.err}")
    assert "READ-BY-DESCRIPTOR" not in res.out, (
        f"the descriptor was handed out.\nout={res.out}")
    assert res.scope.get("enforced") is True, res.scope


def test_the_SAME_descriptor_read_is_allowed_with_enforcement_OFF(
        tmp_path, project):
    """The paired half. Without it the test above would also pass on a
    mechanism that denies `os.open` unconditionally, which is not a boundary —
    the sibling `test_a_boundary_that_denies_EVERYTHING_is_not_a_boundary`
    makes the same point for the deny list."""
    script = tmp_path / "descriptor_reader_off.py"
    script.write_text(textwrap.dedent(f"""
        import os, sys
        root = os.environ["PROJ"]
        fd = os.open(os.path.join(root, {GOLDEN_REL!r}), os.O_RDONLY)
        os.close(fd)
        sys.stdout.write("READ-BY-DESCRIPTOR")
    """))
    res = _run(script, project, on=False, step="14", guard=tmp_path / "g_fd_off")
    assert res.rc == 0, res.err
    assert "READ-BY-DESCRIPTOR" in res.out, res.out
    assert res.scope.get("enforced") is False, res.scope
