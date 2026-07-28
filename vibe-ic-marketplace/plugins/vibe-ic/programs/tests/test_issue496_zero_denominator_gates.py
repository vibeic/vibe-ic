#!/usr/bin/env python3
"""#496 — no PASS without a denominator, and what each zero actually means.

#492 disqualified eight registered structural gates: six reporting an explicit
zero denominator on all 107 tracked ``rtl`` directories, and two disclosing no
denominator at all.  This file holds the two halves of the answer:

  1. THE PRECONDITION. Every one of the eight must state what it examined, and
     a zero must carry a reason. A PASS that does not say what it looked at is
     indistinguishable from a PASS over nothing, and the second is the one that
     reads as coverage while being blind.

  2. THE CLASSIFICATION. Each gate's trigger condition was taken back to the
     corpus. Three of the eight turned out to be blind rather than unemployed,
     and their repairs are pinned here with the witness that proves each — a
     positive fixture the gate must now SEE, and a negative fixture it must now
     FAIL. A repair proved only by "the denominator went up" is not proved.

DISCIPLINE — every fixture here is built in ``tmp_path``. No test points a gate
at ``benchmark-data``: the tracked corpus is read-only evidence, gates write
into what they audit, and gate outcomes are path-sensitive.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _gate_denominator as GD  # noqa: E402
import flow_compliance_check as F  # noqa: E402


# The eight gates #496 is about. Value = the extra argv each needs beyond
# --rtl-dir (all of them take only --rtl-dir, which is why #492 could measure
# them in one sweep).
ISSUE_496_GATES = (
    "bit_count_modulo_check",
    "cmd_arg_range_validation_check",
    "l12_sequence_implementation_check",
    "otp_write_lock_gate_check",
    "pulse_decoder_edge_check",
    "response_payload_template_check",
    "transient_signal_latch_check",
    "tristate_self_rx_mask_check",
)


def _run(gate: str, rtl_dir: Path):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / f"{gate}.py"), "--rtl-dir", str(rtl_dir)],
        capture_output=True, text=True, timeout=60)


def _summary(gate: str, rtl_dir: Path) -> dict:
    """The gate's own summary, via its real CLI.

    ``transient_signal_latch_check`` prints prose rather than JSON, so it is
    read through ``--out-dir``; every other gate prints its report on stdout.
    """
    r = _run(gate, rtl_dir)
    assert "Traceback" not in r.stderr, f"{gate} crashed:\n{r.stderr[-800:]}"
    if gate == "transient_signal_latch_check":
        out = rtl_dir.parent / "_rep"
        r2 = subprocess.run(
            [sys.executable, str(PROGRAMS / f"{gate}.py"),
             "--rtl-dir", str(rtl_dir), "--out-dir", str(out)],
            capture_output=True, text=True, timeout=60)
        assert "Traceback" not in r2.stderr, r2.stderr[-800:]
        return json.loads((out / f"{gate}.json").read_text())
    return json.loads(r.stdout)["summary"]


def _rtl(tmp_path: Path, **files: str) -> Path:
    d = tmp_path / "rtl"
    d.mkdir(exist_ok=True)
    for name, body in files.items():
        (d / name.replace("__", ".")).write_text(body)
    return d


# ── 1. THE PRECONDITION ─────────────────────────────────────────────────────

def test_the_type_refuses_a_silent_zero():
    """The contract is enforced by construction, not by each gate remembering.

    A gate cannot regress into silence by omission — only by writing a reason
    down, and a written reason is reviewable where an absent one is not."""
    with pytest.raises(ValueError, match="not_applicable_reason"):
        GD.Denominator(unit="files", examined=0)
    # Non-zero needs no reason; zero WITH a reason is fine.
    assert GD.Denominator(unit="files", examined=3).is_vacuous is False
    assert GD.Denominator(unit="files", examined=0,
                          not_applicable_reason="none present").is_vacuous


def test_the_type_refuses_an_unnamed_unit():
    """`inout_ports: []` was read as the denominator of a rule denominated in
    driven buses. A bare count with no unit is how that happens."""
    with pytest.raises(ValueError, match="unit"):
        GD.Denominator(unit="  ", examined=5)


@pytest.mark.parametrize("gate", ISSUE_496_GATES)
def test_every_gate_discloses_what_it_examined(gate, tmp_path):
    """THE precondition of #496, checked against each gate's REAL output.

    An empty-but-valid RTL directory is the case that matters: it is where all
    eight used to answer PASS, and where six of them answered it with a bare
    zero and two with nothing at all."""
    rtl = _rtl(tmp_path, top__v="module top(input clk);\nendmodule\n")
    summary = _summary(gate, rtl)
    problems = GD.disclosure_violations(summary)
    assert not problems, f"{gate}: {problems}\nsummary={summary}"


@pytest.mark.parametrize("gate", ISSUE_496_GATES)
def test_the_zero_reason_names_what_was_searched_for(gate, tmp_path):
    """A reason that says "nothing found" is not a reason. It has to name the
    thing, or a reader cannot tell category (a) from category (b) — which is
    the whole question #496 asks."""
    rtl = _rtl(tmp_path, top__v="module top(input clk);\nendmodule\n")
    d = _summary(gate, rtl)[GD.DENOMINATOR_KEY]
    if d["examined"]:
        pytest.skip("gate found something to examine in the empty fixture")
    reason = d["not_applicable_reason"]
    assert len(reason) > 60, f"{gate} reason is not substantive: {reason!r}"


def test_transient_gate_states_its_denominator_on_stdout(tmp_path):
    """This gate's whole output is one line, so the JSON is not enough — the
    line is what a human reads. It said `PASS — 0 errors, 0 warns` whether it
    had cleared a thousand pairs or evaluated none."""
    rtl = _rtl(tmp_path, top__v="module top(input clk);\nendmodule\n")
    r = _run("transient_signal_latch_check", rtl)
    assert r.returncode == 0
    assert "examined 0" in r.stdout, r.stdout
    assert "transient producer" in r.stdout, r.stdout


def test_transient_gate_still_writes_nothing_without_out_dir(tmp_path):
    """#494's property must survive #496's edit: a read-only validator writes
    no file unless a caller asks for one."""
    rtl = _rtl(tmp_path, top__v="module top(input clk);\nendmodule\n")
    before = {p for p in tmp_path.rglob("*")}
    _run("transient_signal_latch_check", rtl)
    assert {p for p in tmp_path.rglob("*")} == before


def test_dispatcher_count_is_not_published_as_the_denominator(tmp_path):
    """`cmd_arg_range_validation_check` had exactly one non-zero count to its
    name, and it is not the denominator. Publishing it as one would have
    claimed 4/107 coverage for a rule that ran on 0/107."""
    rtl = _rtl(tmp_path, disp__v=(
        "module disp;\n"
        "  always @(*) begin\n"
        "    case (cmd_op)\n"
        "      8'hA0: addr_reg = 1;\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"))
    summary = _summary("cmd_arg_range_validation_check", rtl)
    assert len(summary["dispatcher_files"]) == 1, summary
    d = summary[GD.DENOMINATOR_KEY]
    assert d["examined"] == 0, "fixture has no command buffer; rule cannot run"
    assert d["considered"] == 1, "the dispatcher was seen and must be counted"
    assert "command buffer" in d["not_applicable_reason"]


# ── 2. THE CLASSIFICATION RECORD ────────────────────────────────────────────

def test_every_gate_carries_a_classification():
    """v1.7.69 retired six K5 checks by recording the reason in code, not in a
    commit message, so a future producer cannot silently resurrect a check
    nobody re-validated. Same precedent, same requirement."""
    assert set(F._ZERO_DENOMINATOR_CLASSIFICATION) == set(ISSUE_496_GATES)


@pytest.mark.parametrize("gate", ISSUE_496_GATES)
def test_the_classification_is_substantive(gate):
    """A verdict with no measurement behind it is the thing #496 was filed
    against: "it cannot be done by reading exit codes"."""
    entry = F._ZERO_DENOMINATOR_CLASSIFICATION[gate]
    assert set(entry) >= {"verdict", "gate_denominator", "corpus_probe",
                          "disposition"}
    assert any(k in entry["verdict"] for k in
               ("TRIGGER_ABSENT", "EXTRACTION_BROKEN", "ADVISORY_ONLY")), entry
    assert len(entry["corpus_probe"]) > 120, (
        f"{gate}: the probe that distinguishes absence from blindness must be "
        f"described, not asserted: {entry['corpus_probe']!r}")
    assert len(entry["disposition"]) > 60


def test_no_gate_from_this_issue_was_wired_into_the_umbrella():
    """#492's two-condition bar governs, and none of the eight clears it.

    Two of them are now MORE dangerous to wire than they were, because
    repairing their extraction gave them real findings — converting a gate that
    FAILs on the corpus is the first bar, not the second."""
    for gate in ISSUE_496_GATES:
        assert gate not in F._STRUCTURAL_GATE_ARGV_ADAPTERS, (
            f"{gate} was wired into the P0 umbrella; #496 explicitly does not "
            "license that")


# ── 3. THE REPAIRS, EACH WITH A WITNESS ─────────────────────────────────────

_GPIO_DIR_BUS = """\
module apb_gpio #(parameter W = 8) (
  input  wire         clk,
  inout  wire [W-1:0] gpio,
  output wire [W-1:0] gpio_int
);
  reg  [W-1:0] gpio_dir;
  reg  [W-1:0] reg_dout;
  wire [W-1:0] gpio_in;
  genvar gi;
  generate
    for (gi = 0; gi < W; gi = gi + 1) begin : gpio_buf
      assign gpio[gi] = gpio_dir[gi] ? reg_dout[gi] : 1'bz;
    end
  endgenerate
  assign gpio_in = gpio;
  assign gpio_int = gpio_in;
endmodule
"""


def test_tristate_now_examines_a_bus_driven_through_a_dir_register(tmp_path):
    """THE #496 witness. #492 recorded this gate as `inout_ports: []` on all
    107; it actually collects 24 across 4 of them and then drops every one at
    an output-enable lookup that knew a single spelling. This shape — an inout
    driven through `<name>_dir` and tapped raw — is in the tracked tree."""
    rtl = _rtl(tmp_path, gpio__v=_GPIO_DIR_BUS)
    summary = _summary("tristate_self_rx_mask_check", rtl)
    assert summary["inout_ports"] == ["gpio"]
    assert summary["checked"] == 1, (
        f"the driven bus was skipped again: {summary}")
    assert summary["oe_companions"]["gpio"] == "gpio_dir"
    assert summary[GD.DENOMINATOR_KEY]["examined"] == 1
    cats = [f["category"] for f in
            json.loads(_run("tristate_self_rx_mask_check", rtl).stdout)["findings"]]
    assert "RAW_TAP_ASSIGN" in cats, "the raw self-RX tap was not reported"


def test_widening_what_is_examined_did_not_widen_what_is_failed(tmp_path):
    """The masked form this rule enforces assumes an ACTIVE-HIGH enable. For
    `_dir` / `_oeb` the correct mask arm is not determinable statically, so the
    finding is a WARNING. A gate that starts examining more must not start
    failing more by accident."""
    rtl = _rtl(tmp_path, gpio__v=_GPIO_DIR_BUS)
    r = _run("tristate_self_rx_mask_check", rtl)
    assert r.returncode == 0, "a polarity-undeterminable tap became a FAIL"
    sev = {f["severity"] for f in json.loads(r.stdout)["findings"]}
    assert sev == {"WARNING"}, sev


def test_tristate_still_fails_the_active_high_form_it_was_derived_from(tmp_path):
    """The negative half. Renaming the enable to the `_oe` spelling — where the
    polarity IS known — must restore the ERROR, or the widening has quietly
    disarmed the rule."""
    rtl = _rtl(tmp_path, gpio__v=_GPIO_DIR_BUS.replace("gpio_dir", "gpio_oe"))
    r = _run("tristate_self_rx_mask_check", rtl)
    assert r.returncode == 1, "the active-high raw tap no longer FAILs"
    assert {f["severity"] for f in json.loads(r.stdout)["findings"]} == {"ERROR"}


def test_a_port_the_gate_skips_records_why(tmp_path):
    """`checked: 0` was mis-attributed to `inouts: []` for a whole release
    because nothing recorded the drop. Power pads are a legitimate skip — but
    a legitimate skip still has to be legible."""
    rtl = _rtl(tmp_path, pads__v=(
        "module pads(inout wire vccd1, inout wire vssd1);\nendmodule\n"))
    summary = _summary("tristate_self_rx_mask_check", rtl)
    assert summary["inout_ports"] == ["vccd1", "vssd1"]
    assert summary["checked"] == 0 and summary["skipped"] == 2
    for port in ("vccd1", "vssd1"):
        assert "output-enable companion" in summary["skip_reasons"][port]
    d = summary[GD.DENOMINATOR_KEY]
    assert d["examined"] == 0 and d["considered"] == 2
    assert "inout_ports: []" in d["not_applicable_reason"], (
        "the reason should name the mis-measurement it prevents")


_FALLING_EDGE_DECODER = """\
module pulse_rx(input wire clk, input wire rst_n, input wire sin, output reg [3:0] val);
  reg [1:0] sin_sync;
  always @(posedge clk) sin_sync <= {sin_sync[0], sin};
  wire sin_s = sin_sync[1];
  reg sin_s_d;
  always @(posedge clk) sin_s_d <= sin_s;
  wire falling = (~sin_s) & sin_s_d;
  reg [15:0] period_cnt;
  reg [15:0] last_period;
  always @(posedge clk) begin
    if (falling) begin last_period <= period_cnt; period_cnt <= 16'd1; end
    else period_cnt <= period_cnt + 1'b1;
  end
  wire [15:0] ticks_meas = last_period >> 3;
  always @(posedge clk) begin
    if (ticks_meas >= 16'd12) val <= ticks_meas[3:0];
    else if (last_period >= 16'd400) val <= 4'd0;
  end
endmodule
"""


def test_pulse_decoder_now_selects_a_period_measuring_classifier(tmp_path):
    """Bug 1 of two. The selector required the literal token `low_cnt`, so a
    decoder measuring falling-to-falling PERIODS — the shape SENT, DALI and
    1-Wire receivers actually use — was never a candidate at all."""
    rtl = _rtl(tmp_path, dec__v=_FALLING_EDGE_DECODER)
    summary = _summary("pulse_decoder_edge_check", rtl)
    assert summary["files_checked"] == 1, (
        f"the pulse classifier was not selected: {summary}")
    assert summary[GD.DENOMINATOR_KEY]["examined"] == 1


def test_pulse_decoder_recognises_a_falling_edge_detector(tmp_path):
    """Bug 2, and the reason Bug 1 could not be fixed alone. Every existing
    pattern put the negation on the SECOND operand; a LOW-pulse decoder writes
    `(~sig) & sig_d`. Fixing only the selector would have produced a confident
    NO_EDGE_DETECTOR against a design whose detector is right there."""
    rtl = _rtl(tmp_path, dec__v=_FALLING_EDGE_DECODER)
    r = _run("pulse_decoder_edge_check", rtl)
    assert r.returncode == 0, (
        f"false NO_EDGE_DETECTOR on a correct falling-edge decoder:\n{r.stdout}")


def test_pulse_decoder_still_fails_a_level_triggered_classifier(tmp_path):
    """The negative half: the mutation is the defect the rule exists to catch —
    classify on the LEVEL instead of the edge, so the classifier re-fires every
    cycle the line stays low."""
    rtl = _rtl(tmp_path, dec__v=_FALLING_EDGE_DECODER.replace(
        "wire falling = (~sin_s) & sin_s_d;", "wire falling = ~sin_s;"))
    r = _run("pulse_decoder_edge_check", rtl)
    assert r.returncode == 1, f"level-triggered classifier passed:\n{r.stdout}"
    cats = [f["category"] for f in json.loads(r.stdout)["findings"]]
    assert cats == ["NO_EDGE_DETECTOR"], cats


def test_fuzzy_pairing_still_rejects_unrelated_names(tmp_path):
    """The falling-edge pattern reuses `_is_fuzzy_edge_pair`, so the
    adversarial cases v0.119.26 closed must stay closed: `(~food) & foo_d` is
    not an edge detector."""
    rtl = _rtl(tmp_path, dec__v=_FALLING_EDGE_DECODER.replace(
        "wire falling = (~sin_s) & sin_s_d;",
        "wire food = 1'b0; wire foo_d = 1'b0; wire falling = (~food) & foo_d;"))
    r = _run("pulse_decoder_edge_check", rtl)
    assert r.returncode == 1, "unrelated names counted as an edge detector"


# Shaped after the tracked hdlc_core.v: an explicit bit counter, a symbol
# strobe spelled `frame_valid` (NOT one of the five literals the extraction
# used to require), a frame-end state, and — the defect — no test that the
# payload ended on an octet boundary before the frame is declared valid.
_HDLC_SHAPED_ASSEMBLER = """\
module rx_core(input wire clk, input wire rx_bit, output reg frame_valid,
               output reg fcs_ok, output reg rx_done);
  reg [2:0] rx_bit_cnt;
  reg [7:0] rx_octet;
  reg       closing_flag;
  always @(posedge clk) begin
    frame_valid <= 1'b0;
    if (closing_flag) begin
      frame_valid <= 1'b1;
      fcs_ok      <= 1'b1;
      rx_done     <= 1'b1;
    end else begin
      rx_octet <= {rx_bit, rx_octet[7:1]};
      if (rx_bit_cnt == 3'd7) rx_bit_cnt <= 3'd0;
      else rx_bit_cnt <= rx_bit_cnt + 3'd1;
    end
  end
endmodule
"""


def test_bit_count_now_sees_an_assembler_that_does_not_say_byte_valid(tmp_path):
    """The extraction required a symbol-valid strobe spelled as one of five
    literals. The corpus receivers spell it `frame_valid` / `rx_char_valid` /
    `rd_valid`, so a bit assembler with a frame end and no alignment check read
    as a clean PASS. One in the tracked tree does exactly that."""
    rtl = _rtl(tmp_path, rx__v=_HDLC_SHAPED_ASSEMBLER)
    summary = _summary("bit_count_modulo_check", rtl)
    assert summary["checked"] == 1, (
        f"the assembler is still invisible: {summary}")
    assert summary[GD.DENOMINATOR_KEY]["examined"] == 1


def test_bit_count_fails_a_frame_end_with_no_alignment_test(tmp_path):
    """The defect: `frame_valid` is raised at the closing flag without testing
    that the de-stuffed payload ended on an octet boundary, so a truncated
    frame is accepted with its residual bits silently dropped."""
    rtl = _rtl(tmp_path, rx__v=_HDLC_SHAPED_ASSEMBLER)
    r = _run("bit_count_modulo_check", rtl)
    assert r.returncode == 1, f"missing alignment check passed:\n{r.stdout}"
    report = json.loads(r.stdout)
    assert [f["category"] for f in report["findings"]] == \
        ["NO_BIT_ALIGNMENT_CHECK"]
    assert report["findings"][0]["line"] > 0, (
        "a finding reported at line 0 is not actionable")


def test_bit_count_passes_once_the_alignment_test_is_added(tmp_path):
    """The positive half — the gate must be answering the question, not just
    reacting to the file. Adding the octet-boundary test is the whole fix."""
    fixed = _HDLC_SHAPED_ASSEMBLER.replace(
        "      frame_valid <= 1'b1;\n",
        "      frame_valid <= (rx_bit_cnt == 3'd0);\n")
    assert fixed != _HDLC_SHAPED_ASSEMBLER
    rtl = _rtl(tmp_path, rx__v=fixed)
    r = _run("bit_count_modulo_check", rtl)
    assert r.returncode == 0, f"alignment check not credited:\n{r.stdout}"


def test_bit_count_reason_points_at_the_conjunct_that_rejected(tmp_path):
    """When the rule stops because of the symbol-valid conjunct — the one that
    reported 0 corpus-wide while 125 bit-counter matches existed — the reason
    has to say so, or the next reader repeats the measurement from scratch."""
    rtl = _rtl(tmp_path, rx__v=(
        "module m(input clk);\n  reg [2:0] bit_cnt;\n"
        "  always @(posedge clk) bit_cnt <= bit_cnt + 1;\nendmodule\n"))
    d = _summary("bit_count_modulo_check", rtl)[GD.DENOMINATOR_KEY]
    assert d["examined"] == 0
    assert d["considered"] == 1, "the bit-counter candidate must be counted"
    assert "symbol-complete strobe" in d["not_applicable_reason"]


def test_l12_zero_blames_the_missing_input_not_the_design(tmp_path):
    """This gate reported `sequences_checked: 0` because nothing hands it
    `--l12-json`, while 105 of 106 project trees ship a reachable L12 document.
    The zero must not read as 'every declared sequence is implemented'."""
    rtl = _rtl(tmp_path, top__v="module top(input clk);\nendmodule\n")
    d = _summary("l12_sequence_implementation_check", rtl)[GD.DENOMINATOR_KEY]
    assert d["examined"] == 0
    assert "--l12-json" in d["not_applicable_reason"]
    assert "not checked" in d["not_applicable_reason"].lower()


def test_l12_reports_a_real_denominator_when_given_its_input(tmp_path):
    """And when it IS handed the file, the denominator is real — which is the
    evidence that the zero was plumbing, not absence."""
    rtl = _rtl(tmp_path, cc_reset_ctrl__v=(
        "module cc_reset_ctrl(input clk);\n"
        "  always @(posedge clk) begin\n"
        "    case (1'b1) default: ;\n    endcase\n  end\nendmodule\n"))
    l12 = tmp_path / "L12.json"
    l12.write_text(json.dumps({"behavioral_sequences": [{"id": "CC_RESET_700MS"}]}))
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "l12_sequence_implementation_check.py"),
         "--rtl-dir", str(rtl), "--l12-json", str(l12)],
        capture_output=True, text=True, timeout=60)
    d = json.loads(r.stdout)["summary"][GD.DENOMINATOR_KEY]
    assert d["examined"] == 1, r.stdout
    assert d["not_applicable_reason"] == ""


def test_response_payload_declares_itself_advisory(tmp_path):
    """Every finding it can emit is WARN and `pass` is `not any(ERROR)`, so on
    any readable directory it cannot return non-zero. A checker structurally
    incapable of failing should say so where a consumer can read it."""
    rtl = _rtl(tmp_path, top__v="module top(input clk);\nendmodule\n")
    assert _summary("response_payload_template_check", rtl)["advisory_only"]


def test_response_payload_cannot_fail_even_on_its_own_worst_case(tmp_path):
    """Not a claim from reading the source — driven. A dispatcher whose reply
    is entirely hardcoded is the maximum-severity input this program has, and
    it still exits 0."""
    rtl = _rtl(tmp_path, disp__v=(
        "module disp(input clk);\n  reg [7:0] rsp_buf [0:3];\n"
        "  always @(posedge clk) begin\n    case (cmd_op)\n"
        "      8'hA0: begin\n"
        "        rsp_buf[0] <= 8'h00;\n        rsp_buf[1] <= 8'h00;\n"
        "        rsp_buf[2] <= 8'h00;\n      end\n"
        "    endcase\n  end\nendmodule\n"))
    r = _run("response_payload_template_check", rtl)
    assert r.returncode == 0
    report = json.loads(r.stdout)
    assert report["summary"][GD.DENOMINATOR_KEY]["examined"] == 3
    assert report["findings"], "the advisory should still have something to say"
    assert {f["severity"] for f in report["findings"]} == {"WARN"}
