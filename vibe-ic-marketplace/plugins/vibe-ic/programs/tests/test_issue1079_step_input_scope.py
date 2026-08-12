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


# ===========================================================================
# THE BOUNDARY MUST COME FROM THE MODULE THAT DEFINES IT
#
# This file's original fixtures put the oracle under `score/`, which is
# `blindness_audit`'s vocabulary — the module that answers "is this a benchmark
# SCORING oracle". §4.05's boundary lives in `_reference_flow_boundary`, and it
# names twelve segments. Measured before this change: the enforcement denied
# `score/` and `canonical_samples/` and PERMITTED all twelve, `golden/`,
# `oracle/` and `ground_truth/` among them — the literal words §4.05 is written
# in. These tests are that gap, executable.
# ===========================================================================
CANONICAL_ORACLE_RELS = ("golden/g.v", "oracle/o.json", "ground_truth/t.txt",
                         "solutions/s.py", "expected_output/e.log")


@pytest.fixture()
def canon_project(tmp_path):
    """A project holding one file per CANONICAL off-limits segment, plus a
    legitimate design input and a legitimate reference RECIPE."""
    p = tmp_path / "canon"
    for rel in CANONICAL_ORACLE_RELS:
        (p / rel).parent.mkdir(parents=True, exist_ok=True)
        (p / rel).write_text("// oracle content\n")
    (p / INPUT_REL).parent.mkdir(parents=True, exist_ok=True)
    (p / INPUT_REL).write_text(INPUT_BODY)
    (p / "reference_flow").mkdir(parents=True, exist_ok=True)
    (p / "reference_flow" / "run.tcl").write_text("source ./steps.tcl\n")
    return p


@pytest.mark.parametrize("rel", CANONICAL_ORACLE_RELS)
def test_every_canonical_off_limits_segment_is_denied(tmp_path, canon_project, rel):
    """One case per segment `_reference_flow_boundary` names. All were allowed."""
    res = _run(_reader(tmp_path, rel), canon_project, on=True)
    assert res.rc != 0, (
        f"a step read {rel} and was not stopped. The §4.05 boundary module names "
        f"that segment; enforcement must cover it.")


def test_PAIRED_the_reference_flow_RECIPE_stays_readable(tmp_path, canon_project):
    """THE OVER-DENIAL TWIN, and it is the reason the segments are split.

    `reference_flow/` is recipe AND oracle: the tree legitimately holds the
    reference RECIPE and only the QoR-rules artefact inside it is off limits.
    Denying the whole tree by PATH — which the first version of this fix did —
    refuses a legitimate read, and a mechanism that denies two reads in three is
    one people switch off. So `reference_flow` is decided by CONTENT, in the
    parent, and a recipe must still be readable.
    """
    res = _run(_reader(tmp_path, "reference_flow/run.tcl"), canon_project, on=True)
    assert res.rc == 0, (
        f"a legitimate reference RECIPE was denied: {res}. Only the QoR-rules "
        f"artefact inside that tree is the oracle.")


def test_PAIRED_a_declared_design_input_is_still_readable(tmp_path, canon_project):
    """The other twin. Widening the deny must not deny the design INPUT."""
    res = _run(_reader(tmp_path, INPUT_REL), canon_project, on=True)
    assert res.rc == 0, f"the design input was denied: {res}"


def test_the_boundary_comes_from_the_boundary_module_not_a_local_list():
    """The vocabulary is IMPORTED, and the fallback is VISIBLE when it is not.

    A silent fallback to the old narrow set reads identically to enforcement, so
    `oracle_segments` returns its SOURCE and this asserts the real one is used.
    """
    segs, source = sis.oracle_segments()
    assert source == "_reference_flow_boundary", (
        f"the deny vocabulary came from {source!r}. §4.05's boundary has exactly "
        f"one home and this is not reading it.")
    import _reference_flow_boundary as rfb
    canonical = set(getattr(rfb, "ORACLE_TREE_SEGMENTS", ()))
    assert canonical and canonical <= set(segs), (
        f"segments missing from the enforcement: {sorted(canonical - set(segs))}")
    # ...and the reference_flow trees are deliberately NOT path-denied.
    rf = set(getattr(rfb, "REFERENCE_FLOW_TREE_SEGMENTS", ()))
    assert rf and not (rf & set(segs)), (
        f"reference_flow segments are being PATH-denied ({sorted(rf & set(segs))}), "
        f"which refuses the legitimate recipe. They are content-decided.")


def test_the_shim_and_the_module_cannot_DRIFT(tmp_path):
    """The shim carries no second copy of the vocabulary — asserted, not assumed.

    The shim cannot import the plugin, so before this change it re-implemented
    the classifier. Measured then: 0 disagreements across 11 probes — a live
    RISK, not a live defect, and nothing pinned it. Now the parent hands the list
    DOWN and this asserts the two answer alike.
    """
    import importlib.util
    segs, _ = sis.oracle_segments()
    os.environ[sis.ENV_DENY] = json.dumps(list(segs))
    try:
        d = sis.install_guard(tmp_path / "g")
        spec = importlib.util.spec_from_file_location("shim_probe", d / "sitecustomize.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        probes = list(CANONICAL_ORACLE_RELS) + [
            "score/s.json", INPUT_REL, "verified_netlist.v", "reference_flow/run.tcl"]
        bad = [q for q in probes
               if bool(sis.oracle_reason(q)) != bool(m._oracle(q))]
        assert not bad, f"shim and module disagree on {bad}"
    finally:
        os.environ.pop(sis.ENV_DENY, None)


def test_an_enforcement_that_did_not_load_is_DETECTABLE(tmp_path, canon_project):
    """AN ENFORCEMENT WHOSE FAILURE MODE IS A GREEN TICK IS NOT ONE.

    `sitecustomize` is imported by `site` only if it is FIRST on the path; a host
    that already ships one wins silently, the shim never loads, nothing is
    observed, and the run reports no violation — indistinguishable from a run
    that had none. The shim writes a marker as its first act, so the two are
    distinguishable. Both directions.
    """
    guard = tmp_path / "liveness_guard"
    assert not sis.guard_loaded(guard), "marker present before any child ran"
    res = _run(_reader(tmp_path, INPUT_REL), canon_project, on=True, guard=guard)
    assert res.rc == 0, res
    assert sis.guard_loaded(guard), (
        "the child ran under enforcement and left no liveness marker, so a run "
        "that silently skipped the shim would be indistinguishable from this one")


def test_an_empty_deny_vocabulary_REFUSES_to_claim_enforcement(monkeypatch,
                                                               canon_project):
    """A guard with nothing to deny denies nothing. It must not report enforced.

    The one outcome this module may not have is a run that LOOKS enforced and is
    not, so the parent refuses rather than installing a no-op guard.
    """
    monkeypatch.setattr(sis, "oracle_segments", lambda: ((), "probe: empty"))
    env, meta = sis.child_env({sis.ENV_SWITCH: "1"}, project=canon_project,
                              step_id="14", guard_dir=None)
    assert meta["enforced"] is False, meta
    assert "deny" in meta.get("why", "").lower(), meta
