#!/usr/bin/env python3
"""#czl9docs — L9 carried ZERO characters of prose, so every prose rule
downstream was dormant.

`_frame_contract.input_prose_from_json` assembles the prose an L9 contract
carries by walking it for the declared prose keys, and `spec_conformance_check`
feeds that channel to the frame-contract rules. The L9 emitter never wrote a
single one of those keys, so the channel was empty. Measured on this base with
the flow's own step-2 clause and one RTL body violating all three elements:

    L9 as the front door emitted it                  PASS rc=0, 0 findings
    the SAME L9 + the input's own prose in `notes`   FAIL rc=1, 3 errors

A verdict over ZERO characters — the same shape as a verdict over zero ports,
one field along.

Pinned in BOTH directions, and on BOTH branches, because a rule with an
unexercised branch is a rule nobody has measured:
  * WHOLE   — input inside the budget: carried whole.
  * ANCHORED— input over the budget: only blocks naming a declared port.
  * neither — nothing carried: the honest-null, never an empty string.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402

_SPEC = ("Implement a framed serial receiver.\n"
         "\n"
         " - input  clk\n"
         " - output cmd_out (4 bits)\n"
         " - output frame_done\n"
         "\n"
         "The low three bits of the payload are the type field, which is\n"
         "decoded to `cmd_out` as follows:\n"
         "\n"
         "  3'b000 -> 4'h6\n"
         "  3'b001 -> 4'h9\n"
         "\n"
         "`cmd_out` must be valid in the same clock cycle that `frame_done`\n"
         "asserts.\n")

_PORTS = [{"name": "clk", "mode": "input"},
          {"name": "cmd_out", "mode": "output"},
          {"name": "frame_done", "mode": "output"}]


def _emit(text, ports=None):
    fn = getattr(R, "_czl9_emit_interface_prose", None)
    assert fn is not None, ("_czl9_emit_interface_prose is absent — L9 has no "
                            "interface-prose channel at all")
    content = {"ports": list(ports if ports is not None else _PORTS)}
    fn(content, {"spec.md": text})
    return content


def test_a_short_input_is_carried_whole_so_selection_cannot_lose_a_clause():
    c = _emit(_SPEC)
    assert c["interface_prose_provenance"]["selection"] == "whole"
    # verbatim, not paraphrased
    assert c["notes"] == _SPEC.strip()
    assert c["interface_prose_provenance"]["truncated"] is False
    assert "no_interface_prose_in_input" not in c


def test_the_prose_is_the_inputs_own_characters_never_invented():
    c = _emit(_SPEC)
    for clause in ("must be valid in the same clock cycle",
                   "decoded to `cmd_out` as follows",
                   "3'b001 -> 4'h9"):
        assert clause in c["notes"]


def test_over_budget_the_anchored_branch_keeps_only_port_bearing_blocks():
    filler = "\n\n".join(
        f"Section {i}. Packaging, ordering and storage handling. This states "
        f"nothing whatever about the interface of the part."
        for i in range(200))
    c = _emit(_SPEC + "\n\n" + filler)
    pv = c["interface_prose_provenance"]
    assert pv["selection"] == "anchored"
    # the interface clauses survive …
    assert "must be valid in the same clock cycle" in c["notes"]
    # … the colon lead-in drags its table in with it …
    assert "3'b001 -> 4'h9" in c["notes"]
    # … and not one filler paragraph is carried.
    assert "Packaging, ordering and storage" not in c["notes"]


def test_the_bullet_port_table_is_not_repeated_into_the_prose_channel():
    # L9 already carries the port list structurally; repeating it as prose adds
    # no constraint and only inflates the channel.
    filler = "\n\n".join(f"Section {i}. Nothing about the interface."
                         for i in range(300))
    c = _emit(_SPEC + "\n\n" + filler)
    assert c["interface_prose_provenance"]["selection"] == "anchored"
    assert "- output cmd_out (4 bits)" not in c["notes"]


def test_nothing_carried_is_an_honest_null_not_an_empty_string():
    filler = "\n\n".join(f"Section {i}. Nothing about the interface."
                         for i in range(300))
    c = _emit(filler)
    assert c.get("notes") in (None,)
    assert c["no_interface_prose_in_input"] is True


def test_over_budget_with_no_declared_port_is_NOT_MEASURED():
    # Too big to carry whole and no anchor to select with. That is not "the
    # input said nothing" — it must say which it is.
    filler = "\n\n".join(f"Section {i}. Nothing about the interface."
                         for i in range(300))
    c = _emit(filler, ports=[])
    pv = c["interface_prose_provenance"]
    assert pv["selection"] == "none"
    assert "not_measured" in pv
    assert c["no_interface_prose_in_input"] is True
    assert c.get("notes") is None


def test_a_portless_design_still_gets_its_prose_when_it_fits():
    # The port list is only needed to SELECT from prose too big to carry whole.
    # A purely behavioural spec has prose worth carrying and no ports at all.
    c = _emit("Each frame is one start bit, an 8-bit payload and one stop "
              "bit.\n", ports=[])
    assert c["interface_prose_provenance"]["selection"] == "whole"
    assert "one start bit" in c["notes"]


def test_notes_is_a_key_the_consumer_actually_walks():
    # A prose channel the consumer does not read is not a channel. Pin the key
    # against `_frame_contract`'s own declared set rather than restating it.
    import _frame_contract as FC
    assert "notes" in FC._PROSE_KEYS
    c = _emit(_SPEC)
    import json
    assert "must be valid in the same clock cycle" in \
        FC.input_prose_from_json(json.dumps(c))


def test_the_emitter_is_wired_into_the_l9_generator():
    src = (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()
    gen = src.split("def gen_l9_integration_spec(")[1].split("\ndef ")[0]
    assert "_czl9_emit_interface_prose(content, extracted)" in gen


def test_the_flows_own_step2_clause_reaches_the_rules_through_this_channel(
        tmp_path):
    """The payoff, end to end, both directions.

    This is the finding itself: the flow's step-2 clause read PASS rc=0 with 0
    findings on RTL violating every element of the declared contract, because
    the L9 it was handed carried no prose. Same RTL, same L9 ports, channel
    open vs closed."""
    import json
    import subprocess

    rtl = tmp_path / "rtl"
    rtl.mkdir()
    # Violates the declared contract: forwards the raw field instead of
    # applying the decode table, and registers cmd_out one cycle late.
    (rtl / "dut.v").write_text(
        "module TopModule(input clk, input rst, input rx,\n"
        "                 output [3:0] cmd_out, output frame_done);\n"
        "  reg [8:0] sh; reg [3:0] bitcnt; reg done_q; reg [3:0] cmd_q;\n"
        "  wire [2:0] ftype = sh[2:0];\n"
        "  always @(posedge clk) begin\n"
        "    if (rst) begin sh <= 0; bitcnt <= 0; done_q <= 0; end\n"
        "    else begin\n"
        "      sh <= {rx, sh[8:1]};\n"
        "      bitcnt <= (bitcnt == 8) ? 0 : bitcnt + 1;\n"
        "      done_q <= (bitcnt == 8);\n"
        "    end\n"
        "  end\n"
        "  always @(posedge clk) if (done_q) cmd_q <= ftype;\n"
        "  assign cmd_out = cmd_q;\n"
        "  assign frame_done = done_q;\n"
        "endmodule\n")

    spec_text = _SPEC + (
        "\nConsecutive frames must be separated by at least 3 idle bit "
        "periods; a start bit seen sooner is not the start of a frame.\n")
    ports = [{"name": "clk", "mode": "input", "direction": "input"},
             {"name": "rst", "mode": "input", "direction": "input"},
             {"name": "rx", "mode": "input", "direction": "input"},
             {"name": "cmd_out", "mode": "output", "direction": "output",
              "width": 4},
             {"name": "frame_done", "mode": "output", "direction": "output"}]

    def _run(l9: dict) -> subprocess.CompletedProcess:
        p = tmp_path / "L9_INTEGRATION_SPEC.json"
        p.write_text(json.dumps(l9))
        return subprocess.run(
            [sys.executable, str(PROGRAMS / "spec_conformance_check.py"),
             "--rtl-dir", str(rtl), "--spec", str(p)],
            capture_output=True, text=True, timeout=120)

    closed = _run({"schema_version": 2, "ic_name": "dut",
                   "top_module": "TopModule", "ports": ports})
    content = {"ports": list(ports)}
    R._czl9_emit_interface_prose(content, {"spec.md": spec_text})
    opened = _run({"schema_version": 2, "ic_name": "dut",
                   "top_module": "TopModule", "ports": ports,
                   "notes": content["notes"]})

    # channel CLOSED — the pre-fix state: a verdict over zero characters.
    assert closed.returncode == 0, closed.stdout + closed.stderr
    assert "PASS" in closed.stdout
    # channel OPEN — the same RTL is judged against the same input's clauses.
    assert opened.returncode == 1, opened.stdout + opened.stderr
    assert "FAIL" in opened.stdout
    for rule in ("frame-field-mapping-not-applied",
                 "frame-output-latency-added",
                 "frame-interframe-space-unenforced"):
        assert rule in opened.stdout, opened.stdout
