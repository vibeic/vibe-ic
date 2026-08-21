#!/usr/bin/env python3
"""v1.7.64 — Step 14 (d5): the inline-yosys command extractor matched a log
format yosys never emits, and the gate the flow YAML declares never ran the
content audit at all.

Two independent defects, both reproduced on v1.7.36 against a real converged
run (``phase2/stage2/synth/synth.log`` of an ihp-sg13g2 project):

1. ``_yosys_inline_mode_detect._RUNNING_CMD_RE`` demanded a CLOSING BACKTICK
   (``-- Running command `<cmd>` --``). yosys uses GNU-style asymmetric
   quoting and prints ``-- Running command `<cmd>' --``. Measured on the real
   log: the pattern captured 817 characters instead of the command's 664,
   terminating only on an unrelated backtick 153 characters into the FOLLOWING
   log prose. On a log with no stray backtick it captured nothing at all, so
   ``audit_inline_yosys`` returned ``NO_INLINE_COMMAND`` and a real-PDK inline
   synth that skipped ``hilomap`` was reported as a pass.

2. The #649 content audit had exactly ONE call site,
   ``flow_compliance_check._run_yosys_gates``. That in-process copy governs
   Step 14 only when it FAILs (``suppress_yaml_step14 = pre_pnr_result is not
   None``). The gates the flow YAML literally declares —
   ``yosys_hilomap_required_check .`` and ``yosys_script_template_check .`` —
   ran only the weak file-existence ``detect_inline_mode`` confirmer and
   printed ``VACUOUS_PASS`` rc=0 for the same non-conformant command.

chip-AGNOSTIC: every command uses placeholder lib / cell names.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS_DIR = Path(__file__).resolve().parent.parent
if str(_PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS_DIR))

import _yosys_inline_mode_detect as mod  # noqa: E402

_HILOMAP_GATE = _PROGRAMS_DIR / "yosys_hilomap_required_check.py"
_TEMPLATE_GATE = _PROGRAMS_DIR / "yosys_script_template_check.py"


# ---------------------------------------------------------------------------
# fixtures — the REAL yosys echo format: opening backtick, closing apostrophe
# ---------------------------------------------------------------------------
def _gnu_running_cmd_line(body: str) -> str:
    return f"-- Running command `{body}' --"


_REAL_PDK_NO_HILOMAP = (
    "read_verilog -sv /p/rtl/top.v; hierarchy -check -top top; proc; "
    "flatten; synth -top top -flatten; "
    "dfflibmap -liberty /pdk/lib/placeholder_tt.lib; "
    "abc -liberty /pdk/lib/placeholder_tt.lib; clean; "
    "write_verilog -noattr /p/synth/top_synth.v"
)

_REAL_PDK_WITH_HILOMAP = (
    "read_verilog -sv /p/rtl/top.v; hierarchy -check -top top; proc; "
    "flatten; synth -top top -flatten; "
    "dfflibmap -liberty /pdk/lib/placeholder_tt.lib; "
    "abc -liberty /pdk/lib/placeholder_tt.lib; "
    "hilomap -hicell PLACEHOLDER_TIEHI L_HI -locell PLACEHOLDER_TIELO L_LO; "
    "clean; write_verilog -noattr /p/synth/top_synth.v"
)

_SIM_ONLY = (
    "read_verilog -sv -DSIMULATION /p/rtl/top.v; hierarchy -check -top top; "
    "proc; flatten; synth -top top -flatten; dffunmap; abc -g cmos2; "
    "write_verilog -noattr /p/synth/netlist_yosys.v"
)

# The log prose yosys prints immediately AFTER the command echo. It contains a
# stray BACKTICK (yosys quotes the source path the same GNU way), which is the
# only reason the pre-v1.7.64 regex ever terminated at all.
_TRAILING_PROSE_WITH_STRAY_BACKTICK = (
    "\n"
    "1. Executing Verilog-2005 frontend: /p/rtl/top.v\n"
    "Parsing SystemVerilog input from `/p/rtl/top.v' to AST representation.\n"
    "Generating RTLIL representation for module `\\top'.\n"
)


def _make_project(tmp_path: Path, body: str, *, log_name: str = "synth.log",
                  trailer: str = "\n1. Executing Verilog-2005 frontend.\n"
                  ) -> Path:
    syn = tmp_path / "phase2" / "stage2" / "synth"
    syn.mkdir(parents=True, exist_ok=True)
    (syn / log_name).write_text(
        "Yosys 0.67+ (git sha1 placeholder, Release)\n"
        + _gnu_running_cmd_line(body)
        + trailer
        + "End of script. Logfile hash: placeholder\n"
    )
    return tmp_path


def _run_gate(gate: Path, project: Path, out_json: Path):
    proc = subprocess.run(
        [sys.executable, str(gate), str(project), "--json", str(out_json)],
        capture_output=True, text=True,
    )
    payload = {}
    if out_json.is_file():
        payload = json.loads(out_json.read_text())
    return proc.returncode, payload, proc.stdout + proc.stderr


# ===========================================================================
# DEFECT 1 — extraction against the format yosys actually emits
# ===========================================================================
def test_extractor_reads_gnu_quoted_command(tmp_path):
    """A log in yosys' real GNU quoting must yield exactly one command,
    byte-identical to what was run. Pre-fix this returned []."""
    proj = _make_project(tmp_path, _REAL_PDK_WITH_HILOMAP)
    cmds = mod.extract_inline_yosys_commands(proj)
    assert len(cmds) == 1, f"expected 1 extracted command, got {cmds}"
    rel, cmd = cmds[0]
    assert rel.endswith("synth.log")
    assert cmd == _REAL_PDK_WITH_HILOMAP, (
        "extraction must be exact — no under- or over-capture"
    )


def test_extraction_does_not_bleed_into_trailing_log_prose(tmp_path):
    """With trailing prose containing a stray backtick, the pre-fix regex ran
    past the command end and swallowed log text. The capture must stop at
    yosys' own ``' --`` framing."""
    proj = _make_project(tmp_path, _REAL_PDK_WITH_HILOMAP,
                         trailer=_TRAILING_PROSE_WITH_STRAY_BACKTICK)
    cmds = mod.extract_inline_yosys_commands(proj)
    assert len(cmds) == 1
    _, cmd = cmds[0]
    assert cmd == _REAL_PDK_WITH_HILOMAP
    assert "Executing Verilog" not in cmd
    assert "Parsing SystemVerilog" not in cmd


def test_trailing_prose_mentioning_hilomap_cannot_launder_a_missing_hilomap(
        tmp_path):
    """The sharpest discriminator. A real-PDK command with NO hilomap, whose
    following log prose happens to mention the word hilomap plus a stray
    backtick: the pre-fix over-capture pulled that prose INTO the command and
    the conformance test passed on text yosys never ran."""
    trailer = (
        "\n"
        "1. Executing Verilog-2005 frontend: /p/rtl/top.v\n"
        "Note: no hilomap pass was requested for this run.\n"
        "Parsing SystemVerilog input from `/p/rtl/top.v' to AST.\n"
    )
    proj = _make_project(tmp_path, _REAL_PDK_NO_HILOMAP, trailer=trailer)
    verdict, evidence, reasons = mod.audit_inline_yosys(proj)
    assert verdict == "FAIL", (
        "a real-PDK command missing hilomap must FAIL even when later log "
        f"prose mentions hilomap; got {verdict} / {reasons}"
    )
    assert any("hilomap" in r.lower() for r in reasons)
    assert evidence == ["phase2/stage2/synth/synth.log"]


# ===========================================================================
# DEFECT 2 — the gates the flow YAML declares now carry the content check
# ===========================================================================
@pytest.mark.parametrize("gate", [_HILOMAP_GATE, _TEMPLATE_GATE],
                         ids=["hilomap_required", "script_template"])
def test_declared_step14_cli_fails_nonconformant_inline_synth(tmp_path, gate):
    """`<gate> . --json ...` is the literal command in flow yaml Step 14. It
    must exit non-zero for a real-PDK inline synth that skipped hilomap."""
    proj = _make_project(tmp_path, _REAL_PDK_NO_HILOMAP)
    rc, payload, out = _run_gate(gate, proj, tmp_path / "gate.json")
    assert rc == 1, (
        f"declared Step-14 gate must FAIL the #649 case; rc={rc} out={out}"
    )
    assert payload.get("verdict") == "FAIL"
    assert payload.get("reason_class") == "inline_yosys_p_mode_nonconformant"
    assert any("hilomap" in m.lower() for m in payload.get("messages", []))


@pytest.mark.parametrize("gate", [_HILOMAP_GATE, _TEMPLATE_GATE],
                         ids=["hilomap_required", "script_template"])
def test_declared_step14_cli_reports_positively_verified_conformance(
        tmp_path, gate):
    """A conformant inline synth is still rc=0, but the verdict now records
    that the COMMAND was inspected rather than merely that a log file
    exists."""
    proj = _make_project(tmp_path, _REAL_PDK_WITH_HILOMAP)
    rc, payload, out = _run_gate(gate, proj, tmp_path / "gate.json")
    assert rc == 0, out
    assert payload.get("verdict") == "VACUOUS_PASS"
    assert payload.get("reason_class") == "inline_yosys_p_mode_conformant"
    assert payload.get("inline_evidence") == ["phase2/stage2/synth/synth.log"]


def test_template_gate_simulation_only_flag_cannot_waive_a_real_pdk_command(
        tmp_path):
    """`--simulation-only` describes a .ys script's intent. It must not be
    able to waive a command that objectively binds a Liberty library, or the
    #649 bypass returns through a flag."""
    proj = _make_project(tmp_path, _REAL_PDK_NO_HILOMAP)
    out_json = tmp_path / "gate.json"
    proc = subprocess.run(
        [sys.executable, str(_TEMPLATE_GATE), str(proj),
         "--simulation-only", "--json", str(out_json)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1, (
        "--simulation-only must not launder a real-PDK inline command; "
        f"rc={proc.returncode} out={proc.stdout + proc.stderr}"
    )


# ===========================================================================
# DIRECTION-1 GUARDS — behaviour that must NOT change
# ===========================================================================
def test_guard_simulation_only_inline_synth_still_passes(tmp_path):
    """A no-Liberty inline synth legitimately waives hilomap. Must stay rc=0
    on both trees — the tightening must not start failing sim-only synth."""
    proj = _make_project(tmp_path, _SIM_ONLY)
    rc, payload, out = _run_gate(_HILOMAP_GATE, proj, tmp_path / "g.json")
    assert rc == 0, out
    assert payload["verdict"] == "VACUOUS_PASS"


def test_guard_no_synth_evidence_stays_vacuous_pass_unconfirmed(tmp_path):
    """A project with neither .ys script nor any synth log keeps the
    VACUOUS_PASS_UNCONFIRMED tier at rc=0 (non-Yosys flows are legitimate)."""
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
    rc, payload, out = _run_gate(_HILOMAP_GATE, tmp_path, tmp_path / "g.json")
    assert rc == 0, out
    assert payload["verdict"] == "VACUOUS_PASS_UNCONFIRMED"
    assert payload["reason_class"] == "inline_yosys_p_mode_unconfirmed"


def test_guard_file_existence_confirmer_tier_survives(tmp_path):
    """A project whose only marker is a runner artefact with no `-- Running
    command` echo keeps the pre-#649 `inline_yosys_p_mode_confirmed` tier."""
    syn = tmp_path / "phase2" / "stage2" / "synth"
    syn.mkdir(parents=True)
    (syn / "synth.log").write_text("Yosys 0.67+\nEnd of script.\n")
    rc, payload, out = _run_gate(_HILOMAP_GATE, tmp_path, tmp_path / "g.json")
    assert rc == 0, out
    assert payload["verdict"] == "VACUOUS_PASS"
    assert payload["reason_class"] == "inline_yosys_p_mode_confirmed"


def test_guard_ys_script_path_untouched(tmp_path):
    """When a real .ys script exists the gate must still take the per-file
    audit path and never enter the inline branch."""
    syn = tmp_path / "phase2" / "stage2" / "synth"
    syn.mkdir(parents=True)
    (syn / "synth.ys").write_text(
        "read_verilog -sv /p/rtl/top.v\n"
        "synth -top top -flatten\n"
        "dfflibmap -liberty /pdk/lib/placeholder_tt.lib\n"
        "abc -liberty /pdk/lib/placeholder_tt.lib\n"
        "techmap\n"
        "hilomap -hicell PLACEHOLDER_TIEHI L_HI "
        "-locell PLACEHOLDER_TIELO L_LO\n"
        "write_verilog -noattr /p/synth/top_synth.v\n"
    )
    rc, payload, out = _run_gate(_HILOMAP_GATE, tmp_path, tmp_path / "g.json")
    assert rc == 0, out
    assert payload["verdict"] == "PASS"
    assert payload.get("ys_files_audited") == 1


def test_guard_detect_inline_mode_semantics_unchanged(tmp_path):
    """`detect_inline_mode` is still the file-existence confirmer; the
    strengthening lives above it, not inside it."""
    syn = tmp_path / "phase2" / "stage2" / "synth"
    syn.mkdir(parents=True)
    (syn / "synth.log").write_text("anything\n")
    status, evidence = mod.detect_inline_mode(tmp_path)
    assert status == "confirmed"
    assert "phase2/stage2/synth/synth.log" in evidence
    assert mod.detect_inline_mode(tmp_path / "nope") == ("unconfirmed", [])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
