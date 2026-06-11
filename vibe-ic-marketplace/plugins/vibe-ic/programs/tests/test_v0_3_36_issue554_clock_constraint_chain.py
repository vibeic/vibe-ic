"""ORGANIC #554 — clock-constraint source-of-truth chain.

(a) Staged input/constraints/*.sdc / input/reference_flow/**/*.sdc are
    upstream-verified ground truth: phase1 must ingest them into
    L8.clock_domains[].freq_mhz/freq_hz/period_ns and
    L19.fields.constraints_present/sdc_constraints_path; phase3's
    _resolve_clock_spec must use them (not the 20ns fallback).
(b) An EXPLICIT config.json CLOCK_PORT (even when its value equals the
    runner default "clk") must not be silently overridden by L8/L9/RTL
    escalation.
(c) The L8 doc loader must prefer a sibling L8_*.json file that carries
    `clocks`/`clock_domains` evidence over an alphabetically-earlier
    file that does not.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import sdc_constraints as sdc  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402
import phase1_doc_one_shot_runner as P1  # noqa: E402


def _stage_sdc(project: Path, period_ns: float = 10.0, port: str = "clk") -> Path:
    cdir = project / "input" / "constraints"
    cdir.mkdir(parents=True, exist_ok=True)
    sdc_path = cdir / "constraint.sdc"
    sdc_path.write_text(
        f"create_clock -name {port} -period {period_ns} [get_ports {port}]\n"
    )
    return sdc_path


# ── (a) shared sdc_constraints helper ──────────────────────────────────────

def test_primary_clock_reads_staged_sdc(tmp_path):
    _stage_sdc(tmp_path, period_ns=10.0, port="clk")
    primary = sdc.primary_clock(tmp_path)
    assert primary is not None
    assert primary["period_ns"] == 10.0
    assert primary["port_name"] == "clk"


def test_primary_clock_none_without_sdc(tmp_path):
    assert sdc.primary_clock(tmp_path) is None


def test_primary_clock_picks_smallest_period(tmp_path):
    cdir = tmp_path / "input" / "constraints"
    cdir.mkdir(parents=True)
    (cdir / "multi.sdc").write_text(
        "create_clock -name clk_slow -period 20 [get_ports clk_slow]\n"
        "create_clock -name clk_fast -period 5 [get_ports clk_fast]\n"
    )
    primary = sdc.primary_clock(tmp_path)
    assert primary["period_ns"] == 5.0
    assert primary["port_name"] == "clk_fast"


# ── (a) real ibex constraint.sdc uses Tcl `set` vars + `[get_ports $var]` ──
# Verbatim copy of
# benchmark_ic/6th__ibex/input/constraints/constraint.sdc — the defect
# artifact named in issue #554's `## 證據`. A pure-literal regex parser
# returns primary_clock() == None for this file (silently falling back to
# 20ns), because `-period $clk_period` is not numeric and
# `[get_ports $clk_port_name]` (via `set clk_port [get_ports
# $clk_port_name]`) doesn't match a literal `get_ports <name>` pattern.
_IBEX_CONSTRAINT_SDC = """\
current_design ibex_core

set clk_name core_clock
set clk_port_name clk_i
set clk_period 10.0
set clk_io_pct 0.2

set clk_port [get_ports $clk_port_name]

create_clock -name $clk_name -period $clk_period $clk_port

set non_clock_inputs [all_inputs -no_clocks]

set_input_delay [expr $clk_period * $clk_io_pct] -clock $clk_name $non_clock_inputs
set_output_delay [expr $clk_period * $clk_io_pct] -clock $clk_name [all_outputs]
"""


def test_primary_clock_resolves_tcl_variable_sdc(tmp_path):
    cdir = tmp_path / "input" / "constraints"
    cdir.mkdir(parents=True)
    (cdir / "constraint.sdc").write_text(_IBEX_CONSTRAINT_SDC)

    primary = sdc.primary_clock(tmp_path)
    assert primary is not None
    assert primary["period_ns"] == 10.0
    assert primary["port_name"] == "clk_i"
    assert primary["name"] == "core_clock"


def test_resolve_clock_spec_resolves_tcl_variable_sdc(tmp_path):
    cdir = tmp_path / "input" / "constraints"
    cdir.mkdir(parents=True)
    (cdir / "constraint.sdc").write_text(_IBEX_CONSTRAINT_SDC)

    period_ns, port_name = R._resolve_clock_spec(tmp_path, top="ibex_core")
    assert period_ns == 10.0
    assert port_name == "clk_i"


# ── (a) phase3 _resolve_clock_spec uses staged SDC, not the 20ns fallback ──

def test_resolve_clock_spec_uses_staged_sdc_period(tmp_path):
    _stage_sdc(tmp_path, period_ns=10.0, port="clk")
    period_ns, port_name = R._resolve_clock_spec(tmp_path, top="chip_top")
    assert period_ns == 10.0
    assert port_name == "clk"


def test_resolve_clock_spec_falls_back_to_20ns_without_sdc(tmp_path):
    period_ns, _ = R._resolve_clock_spec(tmp_path, top="chip_top")
    assert period_ns == 20.0


# ── (b) explicit config.json CLOCK_PORT == default "clk" survives ─────────

def test_config_clock_port_equal_to_default_not_overridden(tmp_path):
    # Stage L8 evidence that would otherwise escalate the port name to
    # `wb_clk_i`.
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "clock_domains": [
            {"name": "wb_clk_i", "source_pin": "wb_clk_i",
             "domain_kind": "primary", "role": "master"},
        ],
    }))
    (tmp_path / "config.json").write_text(json.dumps({"CLOCK_PORT": "clk"}))

    _, port_name = R._resolve_clock_spec(tmp_path, top="chip_top")
    assert port_name == "clk"


def test_config_clock_port_absent_allows_l8_escalation(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "clock_domains": [
            {"name": "wb_clk_i", "source_pin": "wb_clk_i",
             "domain_kind": "primary", "role": "master"},
        ],
    }))
    _, port_name = R._resolve_clock_spec(tmp_path, top="chip_top")
    assert port_name == "wb_clk_i"


# ── (c) L8 loader prefers the file that carries clock evidence ────────────

def test_l8_loader_prefers_file_with_clock_domains(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    # Alphabetically first, but no clock evidence.
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({"foo": "bar"}))
    # Alphabetically later, carries the clock evidence.
    (gd / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "clock_domains": [
            {"name": "clk_i", "source_pin": "clk_i",
             "domain_kind": "primary"},
        ],
    }))
    l8 = R._v1_6_595_load_phase1_doc(tmp_path, "L8")
    assert l8 is not None
    assert l8.get("clock_domains")
    port = R._v1_6_595_extract_clock_port_from_l8(l8)
    assert port == "clk_i"


def test_l8_extract_port_from_clock_domains_key(tmp_path):
    l8 = {"clock_domains": [{"name": "core clock", "source_pin": "i_clk"}]}
    port = R._v1_6_595_extract_clock_port_from_l8(l8)
    # 'core clock' fails the port-name regex; 'i_clk' matches.
    assert port == "i_clk"


# ── (a) phase1 ingestion: staged 10ns SDC -> L8 freq=100MHz, L19 present ──

def test_phase1_post_emit_sdc_constraints(tmp_path):
    _stage_sdc(tmp_path, period_ns=10.0, port="clk")
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "clock_domains": [
            {"name": "clk", "source_pin": "clk",
             "domain_kind": "primary", "role": "master",
             "freq_hz": None, "freq_mhz": None, "period_ns": None},
        ],
    }))
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({
        "fields": {"constraints_present": False,
                    "sdc_constraints_path": None},
    }))

    P1._post_emit_sdc_constraints(tmp_path)

    l8 = json.loads((gd / "L8_RTL_CONSTANTS.json").read_text())
    primary = l8["clock_domains"][0]
    assert primary["freq_mhz"] == 100.0
    assert primary["period_ns"] == 10.0

    l19 = json.loads((gd / "L19_CONSTRAINTS_PDK.json").read_text())
    assert l19["fields"]["constraints_present"] is True
    assert l19["fields"]["sdc_constraints_path"] == "input/constraints/constraint.sdc"


def test_phase1_post_emit_sdc_constraints_noop_without_sdc(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({
        "fields": {"constraints_present": False},
    }))
    P1._post_emit_sdc_constraints(tmp_path)
    l19 = json.loads((gd / "L19_CONSTRAINTS_PDK.json").read_text())
    assert l19["fields"]["constraints_present"] is False


# ── defect_artifact_fixture gate: sdc_constraints.main() CLI end-state ──────
# Uses the ibex constraint.sdc verbatim fixture (config.json project root) so
# the defect_artifact_fixture_check.py gate's E2 path (main() call + == 0
# verdict) passes alongside the fixture-write (F1) and artifact-name (F3).

def test_sdc_constraints_main_cli_ibex_sdc(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"CLOCK_PORT": "clk_i"}))
    cdir = tmp_path / "input" / "constraints"
    cdir.mkdir(parents=True)
    (cdir / "constraint.sdc").write_text(_IBEX_CONSTRAINT_SDC)
    rc = sdc.main([str(tmp_path)])
    assert rc == 0
