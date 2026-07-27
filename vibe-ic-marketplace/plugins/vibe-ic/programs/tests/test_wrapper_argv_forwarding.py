#!/usr/bin/env python3
"""The remaining `eda_report_audit` wrappers that discarded the caller's argv.

THE DEFECT. `sta_report_check` and `em_report_check` were fixed in PR #473;
`drc_report_check`, `ir_drop_report_check` and `antenna_report_check` were left
as `main([sys.argv[1], "--mode", <fixed>])`, which discards every token past
`sys.argv[1]` — including the `--json <path>` the flow yaml declares for steps
21, 24, 26 and 31. Measured on a project holding real reports::

    ir_drop_report_check  proj --mode ir_drop --json <path>   rc=0  no file
    antenna_report_check  proj --mode antenna --json <path>   rc=0  no file
    drc_report_check      proj --mode drc     --json <path>   rc=1  no file

and on the real completed run `campaign_pr427/spm/converge_ihp-sg13g2`,
`find reports/phase3 -iname '*drc*'` returns only `.rpt` files — the declared
`drc_router.json` / `drc_signoff.json` audit trail was never written by anything.

TWO THINGS THE DROPPED FLAG WAS HIDING, both fixed in the same change:

(1) OUTPUT-PATH COLLISION. Steps 24 and 26 declared their audit output at
    `reports/phase3/ir_drop.json` / `reports/phase3/antenna.json` — the
    PRODUCER's measurement files, which `phase3_one_shot_runner._read_verdict`
    reads back as those steps' evidence and which step 24 also lists in its own
    `required_outputs`. Honouring the flag without moving the path would have
    destroyed the measurement being audited. This is the same collision PR #473
    found at step 25.

(2) SELF-CONSUMPTION. `eda_report_audit`'s antenna mode globs `*antenna*.json`
    and its ir_drop mode globs `*ir_drop*`, so the audit's own verdict document
    would be re-discovered as an input report on the next run. Measured before
    the guard, on a project with exactly one real antenna.rpt: run 1
    `files_found=1`, run 2 (after writing `antenna_signoff.json`)
    `files_found=2`. `_discover` now skips documents carrying this program's own
    `"program": "eda_report_audit:<mode>"` field.

WHAT IT COSTS. Nothing in the gate verdicts: `program_exit_zero` reads the
subprocess rc, and forwarding argv does not change the rc of any call shape in
the repo (the direction-1 guards below pin that). It costs three more files
written per phase-3 run, and it makes a mis-declared `--mode` visible as an
argparse error instead of being silently absorbed — which is the point.

DIRECTION-1 GUARDS (`test_d1_*`) hold on the pre-fix tree as well.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_RUNNER_SRC = _PROGRAMS / "phase3_one_shot_runner.py"

sys.path.insert(0, str(_PROGRAMS))

_PAD = "# " + ("=" * 78 + "\n") * 40  # ~3.2 KB, clears MIN_REPORT_BYTES

_DRC_RPT = (
    "[INFO DRT-0012] OpenROAD detailed_route started\n"
    "Layer M1 spacing violation at (1.2, 3.4): 0.12 um\n"
    "Layer M2 width violation at (5.0, 2.1): 0.15 um\n"
    "Layer M3 via enclosure error at (3.0, 4.5)\n"
    "Total: 0 violations (3 waived)\nDRC clean\n" + _PAD
)
_IR_RPT = (
    "OpenROAD PSM IR drop analysis\n"
    "power grid mesh nodes: 12458\n"
    "worst voltage drop: 6.8 mV (0.2% Vdd) static IR\n"
    "worst dynamic IR: 9.1 mV (0.3% Vdd)\n" + _PAD
)
_ANT_RPT = (
    "OpenROAD check_antennas (ANT) gate-oxide protection\n"
    "antenna check: 0 net violations, 0 pin violations\n"
    "antenna clean: YES\n"
    "gate oxide ratio 12.0 antenna ratio\n" + _PAD
)

# The PRODUCER payloads the runner reads back as step 24/26 evidence.
_IR_MEASUREMENT = {
    "tool": "openroad-psm", "mode": "static_ir_drop",
    "worst_ir_uv": 6800.0, "budget_uv": 180000.0, "verdict": "PASS",
}
_ANT_MEASUREMENT = {
    "tool": "openroad", "mode": "antenna_check_in_session_post_repair",
    "net_violations": 0, "pin_violations": 0, "clean": True, "verdict": "PASS",
}

_WRAPPERS = {
    "drc_report_check.py": "drc",
    "ir_drop_report_check.py": "ir_drop",
    "antenna_report_check.py": "antenna",
}


def _run(prog: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_PROGRAMS / prog), *args],
                          capture_output=True, text=True, timeout=120)


def _project(tmp: Path) -> Path:
    rp = tmp / "reports" / "phase3"
    rp.mkdir(parents=True, exist_ok=True)
    (rp / "drc_router.rpt").write_text(_DRC_RPT)
    (rp / "ir_drop.rpt").write_text(_IR_RPT)
    (rp / "antenna.rpt").write_text(_ANT_RPT)
    (rp / "ir_drop.json").write_text(json.dumps(_IR_MEASUREMENT))
    (rp / "antenna.json").write_text(json.dumps(_ANT_MEASUREMENT))
    return tmp


def _flow_invocations(program: str):
    """Every `<program> ...` command string declared in the flow yaml."""
    return re.findall(rf'"({re.escape(program)} [^"]*)"',
                      _FLOW.read_text(errors="replace"))


# ===========================================================================
# The wrappers honour the output flag the flow declares
# ===========================================================================
@pytest.mark.parametrize("wrapper,mode", sorted(_WRAPPERS.items()))
def test_wrapper_writes_the_json_the_caller_asked_for(tmp_path, wrapper, mode):
    """Pre-fix each of these returned without writing anything at all."""
    proj = _project(tmp_path)
    out = proj / "reports" / "phase3" / f"probe_{mode}.json"
    r = _run(wrapper, str(proj), "--mode", mode, "--json", str(out))
    assert out.is_file(), (
        f"{wrapper} discarded --json: the audit trail step declares has no "
        f"producer (rc={r.returncode})\n{r.stdout}\n{r.stderr}")
    doc = json.loads(out.read_text())
    assert doc["program"] == f"eda_report_audit:{mode}", doc


@pytest.mark.parametrize("wrapper,mode", sorted(_WRAPPERS.items()))
def test_wrapper_does_not_swallow_an_invalid_mode(tmp_path, wrapper, mode):
    """A mode that is not an eda_report_audit choice is a broken declaration.
    It must reach argparse (rc 2) instead of being silently replaced by the
    wrapper's own hardcoded mode."""
    r = _run(wrapper, str(_project(tmp_path)), "--mode", "phase3/stage3/sta")
    assert r.returncode == 2, (
        f"{wrapper} is still absorbing an invalid --mode")
    assert "invalid choice" in (r.stderr + r.stdout)


# ===========================================================================
# (1) The declared audit path must not be the PRODUCER's measurement
# ===========================================================================
@pytest.mark.parametrize("program,producer_path", [
    ("ir_drop_report_check", "reports/phase3/ir_drop.json"),
    ("antenna_report_check", "reports/phase3/antenna.json"),
    ("em_report_check", "reports/phase3/em.json"),
])
def test_flow_audit_json_does_not_clobber_the_producers_measurement(
        program, producer_path):
    invocations = _flow_invocations(program)
    assert invocations, f"{program} is no longer declared in the flow"
    for cmd in invocations:
        toks = cmd.split()
        assert "--json" in toks, cmd
        target = toks[toks.index("--json") + 1]
        assert target != producer_path, (
            f"{program}'s audit verdict would overwrite {producer_path}, the "
            f"measurement it audits")
    runner = _RUNNER_SRC.read_text(errors="replace")
    assert f'"{producer_path}"' in runner, (
        f"the producer's measurement path moved — re-check the collision "
        f"for {producer_path}")


def test_audit_run_leaves_the_producer_measurements_intact(tmp_path):
    """The observable property, driven end to end: run every wrapper the way
    the flow declares it and the runner's evidence files must be byte-identical
    afterwards."""
    proj = _project(tmp_path)
    rp = proj / "reports" / "phase3"
    before = {p.name: p.read_text() for p in
              (rp / "ir_drop.json", rp / "antenna.json")}
    _run("ir_drop_report_check.py", str(proj), "--mode", "ir_drop",
         "--json", str(rp / "ir_drop_signoff.json"))
    _run("antenna_report_check.py", str(proj), "--mode", "antenna",
         "--json", str(rp / "antenna_signoff.json"))
    after = {p.name: p.read_text() for p in
             (rp / "ir_drop.json", rp / "antenna.json")}
    assert after == before, "an audit overwrote the measurement it audits"


@pytest.mark.parametrize("program", sorted(
    w.replace(".py", "") for w in _WRAPPERS))
def test_flow_declares_a_real_report_mode(program):
    """Now that the mode reaches argparse, a mis-declared mode is an rc-2
    argparse error, which flow_compliance_check reads as VACUOUS_PASS — i.e. a
    broken declaration would buy PASS credit. Pin every declaration."""
    import eda_report_audit  # noqa: WPS433
    valid = set(eda_report_audit.MODE_MAP)
    invocations = _flow_invocations(program)
    assert invocations, f"{program} is no longer declared in the flow"
    for cmd in invocations:
        toks = cmd.split()
        assert "--mode" in toks, cmd
        mode = toks[toks.index("--mode") + 1]
        assert mode in valid, (
            f"flow declares `--mode {mode}` for {program}; valid modes are "
            f"{sorted(valid)}")


# ===========================================================================
# (2) The audit must not ingest its own verdict document
# ===========================================================================
def test_audit_does_not_rediscover_its_own_verdict_document(tmp_path):
    """`*antenna*.json` matches the audit's own output. Measured pre-fix:
    files_found 1 -> 2 on a project holding exactly one real antenna report."""
    import eda_report_audit as A
    proj = tmp_path / "p"
    rp = proj / "reports" / "phase3"
    rp.mkdir(parents=True)
    (rp / "antenna.rpt").write_text(_ANT_RPT)

    first = A.main([str(proj), "--mode", "antenna",
                    "--json", str(rp / "antenna_signoff.json")])
    assert first == 0
    assert (rp / "antenna_signoff.json").is_file()

    found = A._discover(proj, ["*antenna*.rpt", "*antenna*.json", "*ANT*.rpt"])
    names = sorted(p.name for p in found)
    assert names == ["antenna.rpt"], (
        f"the audit re-discovered its own verdict document: {names}")


def test_self_document_guard_is_content_based_not_name_based(tmp_path):
    """A name rule would only move the landmine — the caller picks the path."""
    import eda_report_audit as A
    proj = tmp_path / "p"
    rp = proj / "reports" / "phase3"
    rp.mkdir(parents=True)
    (rp / "antenna.rpt").write_text(_ANT_RPT)
    # Same content, a name that shares nothing with the default.
    A.main([str(proj), "--mode", "antenna",
            "--json", str(rp / "zzz_step26_audit_trail.json")])
    found = A._discover(proj, ["*.json"])
    assert [p.name for p in found] == [], found


def test_a_real_tool_json_report_is_still_discovered(tmp_path):
    """Direction check on the guard itself: it must exclude ONLY this
    program's own documents, never a genuine tool report that happens to be
    JSON."""
    import eda_report_audit as A
    proj = tmp_path / "p"
    rp = proj / "reports" / "phase3"
    rp.mkdir(parents=True)
    (rp / "antenna.json").write_text(json.dumps(_ANT_MEASUREMENT))
    found = A._discover(proj, ["*antenna*.json"])
    assert [p.name for p in found] == ["antenna.json"], found


# ===========================================================================
# DIRECTION-1 GUARDS — these hold on the pre-fix tree too
# ===========================================================================
@pytest.mark.parametrize("wrapper", sorted(_WRAPPERS))
def test_d1_bare_wrapper_call_shape_still_works(tmp_path, wrapper):
    """`<wrapper> <project>` with no mode and no --json is the call shape
    test_report_wrappers.py drives. Forwarding argv must not break it."""
    proj = _project(tmp_path)
    assert _run(wrapper, str(proj)).returncode == 0
    assert _run(wrapper, str(tmp_path / "empty")).returncode == 1


@pytest.mark.parametrize("wrapper,mode", sorted(_WRAPPERS.items()))
def test_d1_explicit_mode_still_selects_that_mode(tmp_path, wrapper, mode):
    """The wrapper's own mode is what a declaration states, so stating it
    explicitly must behave identically to the bare call."""
    proj = _project(tmp_path)
    bare = _run(wrapper, str(proj))
    explicit = _run(wrapper, str(proj), "--mode", mode)
    assert bare.returncode == explicit.returncode == 0
    assert (json.loads(bare.stdout)["program"]
            == json.loads(explicit.stdout)["program"]
            == f"eda_report_audit:{mode}")


def test_no_argument_defaults_to_the_current_directory():
    """`main([])` must never happen — the wrapper substitutes ".". (Not a
    direction-1 guard: `build_argv` is introduced by this change, so it cannot
    hold on the pre-fix tree.)"""
    import drc_report_check as W
    assert W.build_argv([]) == [".", "--mode", "drc"]
