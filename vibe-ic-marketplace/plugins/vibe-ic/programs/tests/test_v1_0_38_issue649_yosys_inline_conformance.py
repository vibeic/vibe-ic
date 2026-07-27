#!/usr/bin/env python3
"""ORGANIC #649 — inline `yosys -p` hilomap conformance is no longer a
structural VACUOUS_PASS.

Before #649, the two Step-14 Yosys gates (`yosys_hilomap_required_check`,
`yosys_script_template_check`) emitted ``verdict: VACUOUS_PASS`` whenever no
``.ys`` script existed, on the assumption the project used the runner's
inline ``yosys -p '<cmds>'`` mode. `flow_compliance_check._run_yosys_gates`
then returned an unconditional PASS (`ys_path is None → return True, []`),
so hilomap conformance (the zero_-net tie-cell guard) was NEVER checked for
ANY inline-yosys flow. A real-PDK inline synth that skipped hilomap shipped a
netlist OpenROAD detailed_route crashes on (DRT-0305 'zero_ GROUND').

The fix EXTRACTS the actual inline command yosys echoed into
``phase{2,3}/stage2/synth/{yosys,synth}.log`` (the ``-- Running command
`...` `` lines) and verifies hilomap / -flatten conformance against THAT
command:

  * real-PDK inline synth (binds a Liberty library) WITHOUT hilomap → FAIL
  * real-PDK inline synth WITH hilomap (+ flatten)                  → PASS
  * simulation-only inline synth (no Liberty)                       → PASS
    (hilomap legitimately waived, mirroring --simulation-only)

These tests pin the STRENGTHENING: a synthetic inline yosys.log missing
hilomap FAILs the gate, one with hilomap PASSes — proving the bypass is gone.

chip-AGNOSTIC: every command uses placeholder cell/lib names — no chip /
vendor / SKU literals.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS_DIR = Path(__file__).resolve().parent.parent
if str(_PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS_DIR))

import flow_compliance_check as fcc  # noqa: E402
import _yosys_inline_mode_detect as mod  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _running_cmd_line(body: str) -> str:
    """Wrap an inline yosys command body in the exact echo format yosys
    emits to its log.

    v1.7.64 FIXED FIXTURE — this helper used to emit
    ``-- Running command `<body>` --`` (closing BACKTICK), a format yosys
    has NEVER produced. yosys uses GNU-style asymmetric quoting and prints
    ``-- Running command `<body>' --`` (closing APOSTROPHE); verified
    against a real converged run's phase2/stage2/synth/synth.log. Because
    the fixture matched the buggy `_RUNNING_CMD_RE`, this whole suite
    certified an extractor that returned NO_INLINE_COMMAND on every real
    log — the test pinned a fiction and that is why the regex survived.
    The fixture now emits the real format; every assertion below is
    unchanged.
    """
    return f"-- Running command `{body}' --"


def _make_inline_project(tmp_path: Path, log_body: str,
                         log_name: str = "yosys.log") -> Path:
    """Build a tmp project whose only synth evidence is an inline-yosys log
    under phase2/stage2/synth/ (NO .ys script). Returns the project root."""
    syn = tmp_path / "phase2" / "stage2" / "synth"
    syn.mkdir(parents=True)
    (syn / log_name).write_text(
        "Yosys 0.40 (git sha placeholder)\n"
        + _running_cmd_line(log_body) + "\n"
        "End of script.\n"
    )
    return tmp_path


# A real-PDK inline command (binds a Liberty library) MISSING hilomap — the
# exact #649 bypass case. Placeholder lib/cell names → chip-AGNOSTIC.
_REAL_PDK_NO_HILOMAP = (
    "read_verilog -sv top.v; "
    "synth -top top -flatten; "
    "dfflibmap -liberty /pdk/lib/placeholder_tt.lib; "
    "abc -liberty /pdk/lib/placeholder_tt.lib; "
    "write_verilog -noattr out.v; stat"
)

# Same, but WITH hilomap → conformant.
_REAL_PDK_WITH_HILOMAP = (
    "read_verilog -sv top.v; "
    "synth -top top -flatten; "
    "dfflibmap -liberty /pdk/lib/placeholder_tt.lib; "
    "abc -liberty /pdk/lib/placeholder_tt.lib; "
    "hilomap -hicell TIEHI_CELL Y -locell TIELO_CELL Y; "
    "write_verilog -noattr out.v; stat"
)

# Simulation-only inline command: no Liberty binding, generic mapping.
_SIM_ONLY = (
    "read_verilog -sv -DSIMULATION top.v; "
    "synth -top top -flatten; techmap; opt; dffunmap; abc -g cmos2; "
    "write_verilog -noexpr -nostr -noattr netlist_yosys.v; stat"
)


# ===========================================================================
# Strengthening proof: the gate now FAILs the non-conformant inline command
# ===========================================================================
def test_real_pdk_inline_missing_hilomap_FAILS(tmp_path):
    """The #649 bypass: a real-PDK inline synth with no hilomap used to
    VACUOUS_PASS. It must now FAIL the gate."""
    proj = _make_inline_project(tmp_path, _REAL_PDK_NO_HILOMAP)
    # No .ys script exists — confirm we're exercising the inline path.
    assert fcc._find_synth_ys(proj) is None
    passed, reasons = fcc._run_yosys_gates(proj)
    assert passed is False, (
        "real-PDK inline synth missing hilomap must FAIL, not VACUOUS_PASS"
    )
    blob = "\n".join(reasons).lower()
    assert "hilomap" in blob
    assert "drt-0305" in blob or "zero_" in blob


def test_real_pdk_inline_with_hilomap_PASSES(tmp_path):
    """A conformant real-PDK inline synth (hilomap + flatten present) must
    PASS — the gate is strengthened, not over-strict."""
    proj = _make_inline_project(tmp_path, _REAL_PDK_WITH_HILOMAP)
    assert fcc._find_synth_ys(proj) is None
    passed, reasons = fcc._run_yosys_gates(proj)
    assert passed is True, f"conformant inline synth must PASS; got {reasons}"
    assert reasons == []


def test_simulation_only_inline_PASSES(tmp_path):
    """A simulation-only inline synth (no Liberty binding) legitimately
    waives hilomap — must PASS (mirrors --simulation-only)."""
    proj = _make_inline_project(tmp_path, _SIM_ONLY)
    passed, reasons = fcc._run_yosys_gates(proj)
    assert passed is True, f"sim-only inline synth must PASS; got {reasons}"


def test_real_pdk_inline_in_synth_log_also_audited(tmp_path):
    """The runner echoes the REAL-PDK synth into synth.log (the sim-only
    synth goes to yosys.log). A missing-hilomap real-PDK synth.log must
    FAIL even when no yosys.log is present."""
    proj = _make_inline_project(tmp_path, _REAL_PDK_NO_HILOMAP,
                                log_name="synth.log")
    passed, reasons = fcc._run_yosys_gates(proj)
    assert passed is False
    assert "hilomap" in "\n".join(reasons).lower()


def test_mixed_simonly_yosyslog_plus_realpdk_synthlog(tmp_path):
    """The real runner shape: yosys.log = sim-only (no hilomap, no Liberty),
    synth.log = real-PDK. A real-PDK synth.log MISSING hilomap must FAIL even
    though the sim-only yosys.log would, on its own, waive hilomap. Proves a
    sim-only command cannot mask a non-conformant real-PDK command."""
    syn = tmp_path / "phase2" / "stage2" / "synth"
    syn.mkdir(parents=True)
    (syn / "yosys.log").write_text(_running_cmd_line(_SIM_ONLY) + "\n")
    (syn / "synth.log").write_text(
        _running_cmd_line(_REAL_PDK_NO_HILOMAP) + "\n")
    passed, reasons = fcc._run_yosys_gates(proj := tmp_path)
    assert passed is False, "non-conformant real-PDK synth.log must FAIL"
    assert "hilomap" in "\n".join(reasons).lower()


def test_mixed_simonly_plus_conformant_realpdk_PASSES(tmp_path):
    """Same mixed shape but the real-PDK synth.log HAS hilomap → PASS. This
    is the real conformant-runner shape (e.g. subservient/spm)."""
    syn = tmp_path / "phase2" / "stage2" / "synth"
    syn.mkdir(parents=True)
    (syn / "yosys.log").write_text(_running_cmd_line(_SIM_ONLY) + "\n")
    (syn / "synth.log").write_text(
        _running_cmd_line(_REAL_PDK_WITH_HILOMAP) + "\n")
    passed, reasons = fcc._run_yosys_gates(tmp_path)
    assert passed is True, f"conformant mixed shape must PASS; got {reasons}"


# ===========================================================================
# No-regression: genuinely-no-yosys flow stays a legitimate PASS
# ===========================================================================
def test_no_inline_command_no_ys_stays_pass(tmp_path):
    """A project with no .ys script AND no inline-yosys log at all (e.g. a
    non-Yosys Cadence/GF flow) is a legitimate PASS — #649 does not turn the
    genuine no-Yosys case into a FAIL."""
    passed, reasons = fcc._run_yosys_gates(tmp_path)
    assert passed is True
    assert reasons == []


def test_inline_log_without_synth_command_is_not_audited(tmp_path):
    """A log that echoes only non-synth utility commands (no synth/abc/
    techmap/dfflibmap) is not an inline synth → no false FAIL."""
    proj = _make_inline_project(
        tmp_path, "read_verilog -sv top.v; stat; write_verilog out.v")
    passed, reasons = fcc._run_yosys_gates(proj)
    assert passed is True
    assert reasons == []


# ===========================================================================
# Unit-level coverage of the extraction / classification helpers
# ===========================================================================
def test_extract_pulls_command_from_backticks(tmp_path):
    proj = _make_inline_project(tmp_path, _REAL_PDK_WITH_HILOMAP)
    cmds = mod.extract_inline_yosys_commands(proj)
    assert len(cmds) == 1
    rel, cmd = cmds[0]
    assert rel.endswith("yosys.log")
    assert "hilomap" in cmd
    # The wrapping `-- Running command` / ` --` framing must be stripped.
    assert "Running command" not in cmd


def test_classification_real_pdk_vs_sim_only():
    ok_bad, cls_bad, reasons_bad = \
        mod.check_inline_command_conformance(_REAL_PDK_NO_HILOMAP)
    assert cls_bad == "real_pdk"
    assert ok_bad is False
    assert any("hilomap" in r.lower() for r in reasons_bad)

    ok_good, cls_good, reasons_good = \
        mod.check_inline_command_conformance(_REAL_PDK_WITH_HILOMAP)
    assert cls_good == "real_pdk"
    assert ok_good is True
    assert reasons_good == []

    ok_sim, cls_sim, reasons_sim = \
        mod.check_inline_command_conformance(_SIM_ONLY)
    assert cls_sim == "simulation_only"
    assert ok_sim is True


def test_negated_no_liberty_not_classified_real_pdk():
    """`--no-liberty`-style tokens must NOT trip the Liberty real-PDK
    classifier (negative lookbehind on the hyphen)."""
    cmd = "read_verilog -sv top.v; synth -top top -flatten; " \
          "abc --no-liberty; write_verilog out.v; stat"
    ok, cls, reasons = mod.check_inline_command_conformance(cmd)
    assert cls == "simulation_only"
    assert ok is True


def test_audit_no_inline_command_sentinel(tmp_path):
    verdict, evidence, reasons = mod.audit_inline_yosys(tmp_path)
    assert verdict == "NO_INLINE_COMMAND"
    assert evidence == []
    assert reasons == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
