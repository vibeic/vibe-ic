"""Tests for signaltap_stp_completeness_check.py.

Validates the deterministic SignalTap .stp completeness policy extracted from
skills/fpga-signaltap/SKILL.md:
  RULE-2 every DUT input/output + the four BIST signals captured
  RULE-3 trigger + positive sample_depth + capture clock present

Covers PASS, FAIL (each finding kind), and edge/honesty (garbage/absent input).
"""
from __future__ import annotations

import json
from pathlib import Path

import signaltap_stp_completeness_check as M


# --------------------------------------------------------------------------
# .stp builders
# --------------------------------------------------------------------------
def _stp(signals, *, with_trigger=True, depth=1024, clock="CLOCK_50",
         with_signal_set=True):
    sigs = "\n".join(
        f'      <signal name="{s}" tap_mode="classic" node_index="{i}"/>'
        for i, s in enumerate(signals)
    )
    ss_open = '<signal_set name="dut_debug">' if with_signal_set else "<other>"
    ss_close = "</signal_set>" if with_signal_set else "</other>"
    clk = f'<clock name="{clock}" polarity="posedge"/>' if clock else ""
    cfg = f'<config sample_depth="{depth}"/>' if depth is not None else ""
    trig = ("<trigger><basic_trigger>"
            '<trigger_input signal="bist_fail" edge="rising"/>'
            "</basic_trigger></trigger>") if with_trigger else ""
    return f"""<?xml version="1.0"?>
<session stp_version="9.0">
  <instance entity_name="dut_fpga_top">
    {ss_open}
      {clk}
      {cfg}
{sigs}
    {ss_close}
    {trig}
  </instance>
</session>"""


# Standard complete signal list: DUT I/O + 4 BIST signals.
DUT_IO = ["clk", "rst_n", "d", "q", "q_bar"]
BIST = ["bist_state[2:0]", "test_index[4:0]", "pass_count[7:0]",
        "fail_count[7:0]"]
PORTS_STR = "clk:I:1,rst_n:I:1,d:I:1,q:O:1,q_bar:O:1"


# --------------------------------------------------------------------------
# PASS
# --------------------------------------------------------------------------
def test_pass_full_capture(tmp_path: Path):
    f = tmp_path / "ok.stp"
    f.write_text(_stp(DUT_IO + BIST))
    rc = M.main([str(f), "--ports", PORTS_STR])
    assert rc == 0


def test_pass_ports_skipped_when_no_source(tmp_path: Path):
    # No --sv/--ports: port-coverage half SKIPPED, but BIST + trigger/depth/
    # clock still enforced and present -> PASS, ports_checked False.
    f = tmp_path / "ok.stp"
    f.write_text(_stp(DUT_IO + BIST))
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--json", str(out)])
    assert rc == 0
    res = json.loads(out.read_text())
    assert res["status"] == "PASS"
    assert res["ports_checked"] is False


def test_pass_parses_ports_from_sv(tmp_path: Path):
    sv = tmp_path / "dut.sv"
    sv.write_text(
        "module dut (\n"
        "  input  wire clk,\n"
        "  input  wire rst_n,\n"
        "  input  wire d,\n"
        "  output wire q,\n"
        "  output wire q_bar\n"
        ");\nendmodule\n")
    f = tmp_path / "ok.stp"
    f.write_text(_stp(DUT_IO + BIST))
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--sv", str(sv), "--json", str(out)])
    assert rc == 0
    res = json.loads(out.read_text())
    assert res["status"] == "PASS"
    assert res["ports_checked"] is True
    assert set(res["dut_ports"]) == set(DUT_IO)


# --------------------------------------------------------------------------
# FAIL — RULE-2 (missing port / missing BIST)
# --------------------------------------------------------------------------
def test_fail_missing_dut_port(tmp_path: Path):
    # drop 'q_bar' from the capture
    f = tmp_path / "bad.stp"
    f.write_text(_stp(["clk", "rst_n", "d", "q"] + BIST))
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--ports", PORTS_STR, "--json", str(out)])
    assert rc == 1
    res = json.loads(out.read_text())
    assert res["status"] == "FAIL"
    rules = {x["rule"] for x in res["findings"]}
    assert "MISSING_PORT" in rules
    assert any("q_bar" in x["detail"] for x in res["findings"])


def test_fail_missing_bist_signal(tmp_path: Path):
    # drop fail_count
    f = tmp_path / "bad.stp"
    f.write_text(_stp(DUT_IO + ["bist_state[2:0]", "test_index[4:0]",
                                "pass_count[7:0]"]))
    rc = M.main([str(f), "--ports", PORTS_STR])
    assert rc == 1


def test_fail_missing_bist_signal_detail(tmp_path: Path):
    f = tmp_path / "bad.stp"
    f.write_text(_stp(DUT_IO + ["bist_state[2:0]", "test_index[4:0]",
                                "pass_count[7:0]"]))
    out = tmp_path / "r.json"
    M.main([str(f), "--ports", PORTS_STR, "--json", str(out)])
    res = json.loads(out.read_text())
    assert any(x["rule"] == "MISSING_BIST_SIGNAL"
               and "fail_count" in x["detail"] for x in res["findings"])


# --------------------------------------------------------------------------
# FAIL — RULE-3 (trigger / depth / clock)
# --------------------------------------------------------------------------
def test_fail_no_trigger(tmp_path: Path):
    f = tmp_path / "bad.stp"
    f.write_text(_stp(DUT_IO + BIST, with_trigger=False))
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--ports", PORTS_STR, "--json", str(out)])
    assert rc == 1
    assert "NO_TRIGGER" in {x["rule"] for x in json.loads(out.read_text())["findings"]}


def test_fail_bad_depth_zero(tmp_path: Path):
    f = tmp_path / "bad.stp"
    f.write_text(_stp(DUT_IO + BIST, depth=0))
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--ports", PORTS_STR, "--json", str(out)])
    assert rc == 1
    assert "BAD_DEPTH" in {x["rule"] for x in json.loads(out.read_text())["findings"]}


def test_fail_no_clock(tmp_path: Path):
    f = tmp_path / "bad.stp"
    f.write_text(_stp(DUT_IO + BIST, clock=None))
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--ports", PORTS_STR, "--json", str(out)])
    assert rc == 1
    assert "NO_CLOCK" in {x["rule"] for x in json.loads(out.read_text())["findings"]}


# --------------------------------------------------------------------------
# Edge / honesty
# --------------------------------------------------------------------------
def test_skip_no_stp_given(capsys):
    """Nothing to validate -> SKIP, never a vacuous PASS.

    CONTRACT CHANGE (2026-08-03, vibe-ic#693): rc 2, not 0. The old assertion
    contradicted its own comment — rc 0 is exactly the vacuous PASS
    `flow_compliance_check` credits; rc 2 is the disclosed-skip tier.
    """
    assert M.main([]) == 2
    # `gate_skip_routing_check._skip_token` matches at LINE START.
    assert capsys.readouterr().err.lstrip().startswith("[SKIP]")


def test_empty_self_closing_trigger_set_is_not_a_trigger(tmp_path: Path):
    """NO_TRIGGER must fire on `<trigger_set .../>`.

    This is the false negative measured on the artefact the gate's own header
    names as its subject: `eda_rtl_signaltap_autogen` emits an EMPTY
    self-closing `<trigger_set is_expanded="true" name="trigger: trigger_set_1"/>`,
    and a tag-PRESENCE regex called that "a trigger is defined". A trigger that
    triggers on nothing is the free-running capture this rule rejects.
    """
    f = tmp_path / "empty_trigger.stp"
    f.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<session stp_version="9.0">
  <instance entity_name="sld_signaltap" name="auto_signaltap_0">
    <signal_set name="signal_set: signal_set_1">
      <clock name="CLOCK_50" polarity="posedge"/>
      <config sample_depth="2048"/>
      <signal name="bist_state" node_index="0"/>
      <signal name="test_index" node_index="1"/>
      <signal name="pass_count" node_index="2"/>
      <signal name="fail_count" node_index="3"/>
    </signal_set>
    <trigger_set is_expanded="true" name="trigger: trigger_set_1"/>
  </instance>
</session>
""")
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--json", str(out)])
    rep = json.loads(out.read_text())
    assert rc == 1, rep
    assert [x["rule"] for x in rep["findings"]] == ["NO_TRIGGER"], rep
    assert rep["trigger_present"] is False


def test_populated_trigger_set_is_a_trigger(tmp_path: Path):
    """Positive control for the same predicate: a trigger_set WITH content is
    still accepted, so the fix cannot be an accept-nothing regression."""
    f = tmp_path / "real_trigger.stp"
    f.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<session stp_version="9.0">
  <instance entity_name="sld_signaltap" name="auto_signaltap_0">
    <signal_set name="signal_set: signal_set_1">
      <clock name="CLOCK_50" polarity="posedge"/>
      <config sample_depth="1024"/>
      <signal name="bist_state" node_index="0"/>
      <signal name="test_index" node_index="1"/>
      <signal name="pass_count" node_index="2"/>
      <signal name="fail_count" node_index="3"/>
    </signal_set>
    <trigger_set is_expanded="true" name="trigger: trigger_set_1">
      <trigger_input name="bist_fail" condition="rising_edge"/>
    </trigger_set>
  </instance>
</session>
""")
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--json", str(out)])
    rep = json.loads(out.read_text())
    assert rc == 0, rep
    assert rep["trigger_present"] is True


def test_fail_garbage_stp_no_signal_set(tmp_path: Path):
    # A given .stp with NO <signal_set> is a broken artifact -> honest FAIL,
    # NOT a vacuous PASS.
    f = tmp_path / "garbage.stp"
    f.write_text("<?xml version='1.0'?><nonsense>not a signaltap file</nonsense>")
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--json", str(out)])
    assert rc == 1
    res = json.loads(out.read_text())
    assert res["status"] == "FAIL"
    assert "NO_SIGNAL_SET" in {x["rule"] for x in res["findings"]}


def test_missing_stp_file_is_io_error(tmp_path: Path):
    assert M.main([str(tmp_path / "does_not_exist.stp")]) == 2


def test_hierarchical_and_range_names_normalised(tmp_path: Path):
    # Captured as `dut_inst|clk` and `bist_state[2:0]`; the port/BIST match
    # must strip hierarchy + bit-range. Full capture -> PASS.
    sigs = [f"dut_inst|{s}" for s in DUT_IO] + BIST
    f = tmp_path / "ok.stp"
    f.write_text(_stp(sigs))
    rc = M.main([str(f), "--ports", PORTS_STR])
    assert rc == 0


def test_parse_ports_from_sv_widths():
    src = ("module top (input wire clk, input [7:0] data,"
           " output [3:0] cnt, inout sda); endmodule")
    ports = M.parse_ports_from_sv(src)
    by = {p.name: p for p in ports}
    assert by["clk"].width == 1 and by["clk"].direction == "input"
    assert by["data"].width == 8
    assert by["cnt"].width == 4 and by["cnt"].direction == "output"
    assert by["sda"].direction == "inout"
