"""Tests for mixed_signal_signoff_check.py (M4 — hardened roll-up).

The hardened M4 gate must verify that ``ready_for_tapeout`` is *justified*:
it INDEPENDENTLY re-checks the substance of every upstream M1–M3 mixed-signal
report and rolls them up, rather than trusting the self-asserted boolean.

These tests pin:
  * PASS  — signoff claims ready AND every upstream report substantively PASSes.
  * FAIL  — the anti-fabrication catch: signoff claims ready=true but an
            upstream report (e.g. an unprotected power-domain crossing) does
            NOT roll up PASS.  This is the silicon hole the gate guards.
  * FAIL  — ready_for_tapeout false / absent.
  * FAIL  — required signoff.json missing while the mixed-signal track applies.
  * SKIP  — genuinely digital-only project (no analog blocks, no signoff).
  * FAIL  — missing or malformed upstream report (never a vacuous PASS).
  * WAIVED— explicit waivers.json entry.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "mixed_signal_signoff_check.py"


# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------
def _write(project: Path, rel: str, obj) -> Path:
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2) + "\n")
    return p


def _declare_analog_blocks(project: Path, n: int = 2) -> None:
    _write(project, "phase1/analog/analog_block_list.json",
           {"blocks": [f"block_{i}" for i in range(n)]})


def _good_upstream(project: Path) -> None:
    """Write a full, substantively-PASSing set of M1–M3 reports."""
    _write(project, "reports/analog/mixed_signal/merge.json",
           {"gate": "mixed_signal_merge_check", "verdict": "PASS"})
    _write(project, "reports/analog/mixed_signal/power_domain.json",
           {"all_crossings_protected": True})
    _write(project, "reports/analog/mixed_signal/level_shifter.json",
           {"all_required_inserted": True})
    _write(project, "reports/analog/mixed_signal/isolation.json",
           {"all_required_inserted": True})
    _write(project, "phase3/mixed_signal/cosim/mixed_signal_results.json",
           {"all_scenarios_passed": True})
    _write(project, "reports/analog/mixed_signal/interface_si.json",
           {"all_interfaces_clean": True})


def _signoff(project: Path, ready: bool) -> None:
    _write(project, "reports/analog/mixed_signal/signoff.json",
           {"ready_for_tapeout": ready})


def _run(project: Path, tmp_path: Path):
    out_json = tmp_path / "out.json"
    r = subprocess.run(
        [sys.executable, str(PROG), str(project), "--json", str(out_json)],
        capture_output=True, text=True,
    )
    report = json.loads(out_json.read_text()) if out_json.exists() else {}
    return r.returncode, report, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# PASS — substance good
# ---------------------------------------------------------------------------
def test_pass_when_ready_and_all_upstream_substance_pass(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    _good_upstream(project)
    _signoff(project, ready=True)

    rc, report, _ = _run(project, tmp_path)
    assert rc == 0, report
    assert report["verdict"] == "PASS"
    assert report["ready_for_tapeout_claimed"] is True
    # Every upstream report must have been independently re-checked PASS.
    assert len(report["upstream_rollup"]) == 6
    assert all(r["status"] == "PASS" for r in report["upstream_rollup"])


def test_pass_accepts_waived_merge_and_alias_paths(tmp_path):
    """M1 verdict WAIVED is acceptable; bare reports/mixed_signal/ alias works."""
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    # M1 waived
    _write(project, "reports/analog/mixed_signal/merge.json",
           {"verdict": "WAIVED"})
    # M2 at the bare alias path (no analog/ segment)
    _write(project, "reports/mixed_signal/power_domain.json",
           {"all_crossings_protected": True})
    _write(project, "reports/mixed_signal/level_shifter.json",
           {"all_required_inserted": True})
    _write(project, "reports/mixed_signal/isolation.json",
           {"all_required_inserted": True})
    _write(project, "phase3/mixed_signal/cosim/mixed_signal_results.json",
           {"all_scenarios_passed": True})
    _write(project, "reports/analog/mixed_signal/interface_si.json",
           {"all_interfaces_clean": True})
    _signoff(project, ready=True)

    rc, report, _ = _run(project, tmp_path)
    assert rc == 0, report
    assert report["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# FAIL — the anti-fabrication catch (silicon hole the gate guards)
# ---------------------------------------------------------------------------
def test_fail_overclaim_when_power_domain_crossing_unprotected(tmp_path):
    """signoff claims ready=true but a power-domain crossing is UNPROTECTED.

    A blind json_field_true on ready_for_tapeout would PASS this — and a chip
    with an unprotected analog/digital domain crossing would tape out. The
    hardened roll-up must FAIL it.
    """
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    _good_upstream(project)
    # Corrupt ONLY the power-domain substance — everything else still PASSes.
    _write(project, "reports/analog/mixed_signal/power_domain.json",
           {"all_crossings_protected": False})
    _signoff(project, ready=True)  # producer over-claims

    rc, report, _ = _run(project, tmp_path)
    assert rc == 1, report
    assert report["verdict"] == "FAIL"
    assert report["ready_for_tapeout_claimed"] is True  # claim was made…
    rules = {f["rule"] for f in report["findings"]}
    assert "OVERCLAIM_UNJUSTIFIED_SIGNOFF" in rules
    bad = [r for r in report["upstream_rollup"]
           if r["key"] == "power_domain"][0]
    assert bad["status"] == "FAIL_SUBSTANCE"


def test_fail_overclaim_when_level_shifter_not_inserted(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    _good_upstream(project)
    _write(project, "reports/analog/mixed_signal/level_shifter.json",
           {"all_required_inserted": False})
    _signoff(project, ready=True)

    rc, report, _ = _run(project, tmp_path)
    assert rc == 1, report
    assert report["verdict"] == "FAIL"
    assert "OVERCLAIM_UNJUSTIFIED_SIGNOFF" in {f["rule"] for f in report["findings"]}


def test_fail_overclaim_when_cosim_scenarios_failed(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    _good_upstream(project)
    _write(project, "phase3/mixed_signal/cosim/mixed_signal_results.json",
           {"all_scenarios_passed": False})
    _signoff(project, ready=True)

    rc, report, _ = _run(project, tmp_path)
    assert rc == 1, report
    assert report["verdict"] == "FAIL"


def test_fail_overclaim_when_merge_verdict_fail(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    _good_upstream(project)
    _write(project, "reports/analog/mixed_signal/merge.json",
           {"verdict": "FAIL"})
    _signoff(project, ready=True)

    rc, report, _ = _run(project, tmp_path)
    assert rc == 1, report
    bad = [r for r in report["upstream_rollup"] if r["key"] == "merge"][0]
    assert bad["status"] == "FAIL_SUBSTANCE"


# ---------------------------------------------------------------------------
# FAIL — ready_for_tapeout not true
# ---------------------------------------------------------------------------
def test_fail_when_not_ready_for_tapeout(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    _good_upstream(project)
    _signoff(project, ready=False)

    rc, report, _ = _run(project, tmp_path)
    assert rc == 1, report
    assert report["verdict"] == "FAIL"
    assert "NOT_READY_FOR_TAPEOUT" in {f["rule"] for f in report["findings"]}


def test_fail_when_ready_field_absent(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    _good_upstream(project)
    _write(project, "reports/analog/mixed_signal/signoff.json", {})  # no field

    rc, report, _ = _run(project, tmp_path)
    assert rc == 1, report
    assert report["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# missing-data behaviour — honest FAIL or SKIP, never vacuous PASS
# ---------------------------------------------------------------------------
def test_fail_when_signoff_missing_but_track_applies(tmp_path):
    """Analog blocks declared but no signoff.json ⇒ required artefact missing."""
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    _good_upstream(project)
    # NO signoff.json written

    rc, report, _ = _run(project, tmp_path)
    assert rc == 1, report
    assert report["verdict"] == "FAIL"
    assert "REQUIRED_SIGNOFF_MISSING" in {f["rule"] for f in report["findings"]}


def test_skip_when_no_analog_blocks_and_no_signoff(tmp_path):
    """Genuinely digital-only project ⇒ explicit SKIP, not vacuous PASS."""
    project = tmp_path / "proj"
    project.mkdir()
    # no analog_block_list.json, no signoff.json

    rc, report, _ = _run(project, tmp_path)
    assert rc == 2, report
    assert report["verdict"] == "SKIP"
    assert report["analog_applicable"] is False


def test_fail_when_signoff_present_but_upstream_report_missing(tmp_path):
    """ready=true but an upstream report file is entirely absent ⇒ FAIL,
    never a vacuous PASS on the absence of evidence."""
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    _good_upstream(project)
    # Delete one required upstream report (isolation).
    (project / "reports/analog/mixed_signal/isolation.json").unlink()
    _signoff(project, ready=True)

    rc, report, _ = _run(project, tmp_path)
    assert rc == 1, report
    miss = [r for r in report["upstream_rollup"] if r["key"] == "isolation"][0]
    assert miss["status"] == "FAIL_MISSING"
    assert "OVERCLAIM_UNJUSTIFIED_SIGNOFF" in {f["rule"] for f in report["findings"]}


def test_fail_when_upstream_report_malformed(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    _good_upstream(project)
    # Corrupt the interface_si report into non-JSON.
    bad = project / "reports/analog/mixed_signal/interface_si.json"
    bad.write_text("{ this is not valid json")
    _signoff(project, ready=True)

    rc, report, _ = _run(project, tmp_path)
    assert rc == 1, report
    mal = [r for r in report["upstream_rollup"] if r["key"] == "interface_si"][0]
    assert mal["status"] == "FAIL_MALFORMED"


def test_fail_when_signoff_itself_malformed(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    _good_upstream(project)
    p = project / "reports/analog/mixed_signal/signoff.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json at all")

    rc, report, _ = _run(project, tmp_path)
    assert rc == 1, report
    assert report["verdict"] == "FAIL"
    assert "SIGNOFF_MALFORMED" in {f["rule"] for f in report["findings"]}


# ---------------------------------------------------------------------------
# WAIVED — explicit, ticketed
# ---------------------------------------------------------------------------
def test_waived_when_step_waived(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    # No signoff, but an explicit waiver carries the step.
    _write(project, "waivers.json", {"waived_steps": [
        {"id": "mixed_signal_signoff", "ticket": "JIRA-123",
         "reason": "mixed-signal sign-off aggregator deferred to A-spin"},
    ]})

    rc, report, _ = _run(project, tmp_path)
    assert rc == 0, report
    assert report["verdict"] == "WAIVED"


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------
def test_nonexistent_project_dir_returns_2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nope")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


def test_does_not_echo_ready_field_blindly(tmp_path):
    """Regression guard: a true ready_for_tapeout with NO upstream evidence
    must NOT pass.  This is exactly the blind-echo anti-pattern the gate
    replaces."""
    project = tmp_path / "proj"
    project.mkdir()
    _declare_analog_blocks(project)
    _signoff(project, ready=True)  # claim with ZERO upstream reports present

    rc, report, _ = _run(project, tmp_path)
    assert rc == 1, report
    assert report["verdict"] == "FAIL"
    # All six upstream reports should be reported missing.
    assert all(r["status"] == "FAIL_MISSING" for r in report["upstream_rollup"])
