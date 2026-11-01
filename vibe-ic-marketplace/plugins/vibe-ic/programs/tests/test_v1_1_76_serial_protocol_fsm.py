"""v1.1.76 — serial_protocol_fsm_synth deterministic SOLVER for the SERIAL /
PROTOCOL receiver FSM family (bucket-② prose spec -> bucket-① RTL).

full_moore_fsm_synth owns prompts that WRITE OUT a Moore transition table; this
module owns prompts that describe a PRECISE serial/protocol receiver in PROSE —
the machine is mechanically buildable from the STATED parameters even though no
transition table is given:

  * SERIAL FRAMING RECEIVER (start bit 0, 8 data bits, stop bit 1, idle high,
    LSB-first) -> done                                         — Prob137_fsm_serial
  * SAME + byte capture (out_byte valid when done)             — Prob146_fsm_serialdata
  * HDLC CONSECUTIVE-1s COUNTER (5+0 -> disc, 6 -> flag, 7+ -> err), Moore — Prob140_fsm_hdlc
  * SERIAL 2's COMPLEMENTER (LSB-first Moore, carry-derived)   — Prob089_ece241_2014_q5a
  * PATTERN-DETECT + DELAY TIMER (detect 1101, shift 4 MSB-first delay bits,
    count (delay+1)*1000 cycles, done/ack)                     — Prob156_review2015_fancytimer

Positives are host-scored (iverilog -g2012 dut + ref + test; vvp; 0 mismatches)
when the dataset + tools are present. §4.05 NO-LEAK: >=5 negative fixtures that
MUST return None (SKIP), plus a corpus sweep proving the fire set is EXACTLY the
five intended problems and nothing else in the 156-prompt benchmark, with EVERY
fire host-scoring to 0 mismatches.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import pytest
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import serial_protocol_fsm_synth as SP  # noqa: E402
import spec_artifact_registry as REG    # noqa: E402  (Moore-solver steal check)
from _hostpaths import corpus_path  # noqa: E402

DS = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")
HAVE_DS = DS.is_dir()
IVERILOG = shutil.which("iverilog")
VVP = shutil.which("vvp")

_HDR = ("I would like you to implement a module named TopModule with the following\n"
        "interface. All input and output ports are one bit unless otherwise specified.\n\n")


# --------------------------------------------------------------------------- #
# host-score helper
# --------------------------------------------------------------------------- #
def _host_score(prob, rtl):
    """iverilog-compile dut(rtl)+ref+test, run vvp, assert 0 mismatches."""
    ref = DS / f"{prob}_ref.sv"
    test = DS / f"{prob}_test.sv"
    assert ref.is_file() and test.is_file(), f"dataset missing for {prob}"
    with tempfile.TemporaryDirectory() as d:
        dut = Path(d) / "dut.sv"
        dut.write_text(rtl)
        vvp_out = Path(d) / "sim.vvp"
        c = subprocess.run(
            [IVERILOG, "-g2012", "-o", str(vvp_out), str(dut), str(ref), str(test)],
            capture_output=True, text=True)
        assert c.returncode == 0, f"{prob} compile failed:\n{c.stderr}"
        r = subprocess.run([VVP, str(vvp_out)], capture_output=True, text=True)
        out = r.stdout + r.stderr
        m = re.search(r"Mismatches:\s*(\d+)", out, re.I)
        assert m is not None, f"{prob}: no Mismatches line in:\n{out}"
        assert int(m.group(1)) == 0, f"{prob}: {m.group(1)} mismatches\n{out}"


# --------------------------------------------------------------------------- #
# POSITIVE fixtures (host-scored against the real dataset when present)
# --------------------------------------------------------------------------- #
POSITIVES = [
    "Prob137_fsm_serial",
    "Prob146_fsm_serialdata",
    "Prob140_fsm_hdlc",
    "Prob089_ece241_2014_q5a",
    "Prob156_review2015_fancytimer",
]


def test_positives_fire_and_hostscore():
    """Every known family member FIREs and (if dataset+tools present) host-PASSes
    to 0 mismatches — the §4.05 condition for a legitimate FIRE."""
    if not HAVE_DS:
        import pytest
        pytest.skip("verilog-eval dataset not present")
    for prob in POSITIVES:
        prompt = (DS / f"{prob}_prompt.txt").read_text()
        rtl = SP.synth(prompt)
        assert rtl is not None, f"{prob} should FIRE but SKIPped"
        assert "module TopModule" in rtl
        if IVERILOG and VVP:
            _host_score(prob, rtl)


def test_no_moore_solver_steal():
    """Every fire here must be a prompt the existing registry does NOT already
    solve (none of these are written-table Moore FSMs) — no steal from the
    full_moore_fsm / table solvers."""
    if not HAVE_DS:
        import pytest
        pytest.skip("verilog-eval dataset not present")
    for prob in POSITIVES:
        t = (DS / f"{prob}_prompt.txt").read_text()
        foreign = [a.key for a in REG.REGISTRY if a.key != "serial_protocol_fsm"
                   and a.generate and a.generate(t, "TopModule")]
        assert foreign == [], f"{prob} also solved by {foreign} — would steal"


# --------------------------------------------------------------------------- #
# Self-contained positives (no dataset needed) — pin the emitted structure
# --------------------------------------------------------------------------- #
def test_framing_emits_idle_start_data_stop():
    p = _HDR + (" - input  clk\n - input  reset\n - input  in\n - output done\n\n"
                "One common scheme is to use one start bit (0), 8 data bits, and 1 "
                "stop bit (1). The line is also at logic 1 when nothing is being "
                "transmitted (idle). Identify the start bit, wait for all 8 data "
                "bits, then verify the stop bit. Include a active-high synchronous "
                "reset. Note that the serial protocol sends the least significant "
                "bit first.\n")
    rtl = SP.synth(p)
    assert rtl is not None
    assert "IDLE" in rtl and "STOP" in rtl and "DONE" in rtl and "ERR" in rtl
    assert "D0=" in rtl and "D7=" in rtl                 # 8 data states D0..D7
    assert "if (reset) state <= IDLE;" in rtl            # sync active-high reset
    assert "always @(posedge clk)" in rtl
    assert "assign done = (state == DONE);" in rtl


def test_framing_with_byte_capture():
    p = _HDR + (" - input  clk\n - input  in\n - input  reset\n"
                " - output out_byte (8 bits)\n - output done\n\n"
                "One common scheme is to use one start bit (0), 8 data bits, and 1 "
                "stop bit (1). The line is also at logic 1 when nothing is being "
                "transmitted (idle). The module will also output the correctly-"
                "received data byte. out_byte needs to be valid when done is 1. "
                "Include a active-high synchronous reset. Note that the serial "
                "protocol sends the least significant bit first.\n")
    rtl = SP.synth(p)
    assert rtl is not None
    assert "output [7:0] out_byte" in rtl
    assert "sh <= {in, sh[" in rtl                       # LSB-first shift capture
    assert "assign out_byte = done ? sh[8:1] : 8'hx;" in rtl


def test_hdlc_emits_run_counter_and_three_outputs():
    p = _HDR + (" - input  clk\n - input  reset\n - input  in\n"
                " - output disc\n - output flag\n - output err\n\n"
                "Seeing exactly 6 consecutive 1s is a flag. To avoid the data "
                "stream from accidentally containing flags, the sender inserts a "
                "zero after every 5 consecutive 1s which the receiver must detect "
                "and discard. We also need to signal an error if there are 7 or "
                "more consecutive 1s. Create a Moore-type finite state machine. "
                "The reset signal is active high synchronous.\n")
    rtl = SP.synth(p)
    assert rtl is not None
    assert "C0=" in rtl and "C6=" in rtl                 # count states C0..C6
    assert "SDISC" in rtl and "SFLAG" in rtl and "SERR" in rtl
    assert "C5: nstate = in ? C6 : SDISC;" in rtl        # 5 ones + 0 -> discard
    assert "C6: nstate = in ? SERR : SFLAG;" in rtl      # 6 ones + 1 -> err, +0 -> flag
    assert "assign disc = (state == SDISC);" in rtl


def test_2s_complement_emits_carry_moore():
    p = _HDR + (" - input  clk\n - input  areset\n - input  x\n - output z\n\n"
                "The module should implement a one-input one-output serial 2's "
                "complementer Moore state machine. The input (x) is a series of "
                "bits beginning with the least-significant bit of the number. The "
                "circuit requires a positive edge triggered asynchronous reset.\n")
    rtl = SP.synth(p)
    assert rtl is not None
    assert "posedge clk or posedge areset" in rtl        # async, positive-edge
    assert "if (areset) state <= P;" in rtl
    assert "P: state <= x ? Q : P;" in rtl
    assert "assign z = (state == Q);" in rtl


def test_pattern_timer_emits_detect_shift_count():
    p = (DS / "Prob156_review2015_fancytimer_prompt.txt").read_text() if HAVE_DS else (
        _HDR + (" - input  clk\n - input  reset\n - input  data\n"
                " - output count (4 bits)\n - output counting\n - output done\n"
                " - input  ack\n\n"
                "When the pattern 1101 is detected, shift in the next 4 bits, "
                "most-significant-bit first; these determine delay[3:0]. The state "
                "machine must count for exactly (delay[3:0] + 1) * 1000 clock "
                "cycles. Output the remaining time on count. Assert done and wait "
                "for ack. The reset signal is active high synchronous.\n"))
    rtl = SP.synth(p)
    assert rtl is not None
    assert "P0=" in rtl and "B0=" in rtl                 # pattern + shift states
    assert "CNT" in rtl and "WAIT" in rtl
    assert "scount" in rtl and "fcount" in rtl           # whole-unit + fast counter
    assert re.search(r"fcount==\d+'d999", rtl)           # (delay+1)*1000 -> 0..999
    assert "assign counting = (state == CNT);" in rtl
    assert "assign done = (state == WAIT);" in rtl


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK negatives — MUST return None (SKIP) (>=5)
# --------------------------------------------------------------------------- #
def test_neg_framing_data_count_unstated():
    # framing prose but the DATA-BIT count is not stated -> can't size N -> SKIP.
    p = _HDR + (" - input  clk\n - input  reset\n - input  in\n - output done\n\n"
                "Use one start bit (0) and 1 stop bit (1). The line is at logic 1 "
                "when idle. Include a active-high synchronous reset. The serial "
                "protocol sends the least significant bit first.\n")
    assert SP.synth(p) is None


def test_neg_framing_idle_unstated():
    # framing prose but the IDLE level is not stated -> SKIP (we never guess idle).
    p = _HDR + (" - input  clk\n - input  reset\n - input  in\n - output done\n\n"
                "Use one start bit (0), 8 data bits, and 1 stop bit (1). Include a "
                "active-high synchronous reset. The serial protocol sends the "
                "least significant bit first.\n")
    assert SP.synth(p) is None


def test_neg_framing_idle_disagrees_with_stop():
    # idle level stated but DISAGREES with the stop polarity -> a different machine
    # than the one we build -> SKIP.
    p = _HDR + (" - input  clk\n - input  reset\n - input  in\n - output done\n\n"
                "Use one start bit (0), 8 data bits, and 1 stop bit (1). The line "
                "is at logic 0 when idle. Include a active-high synchronous reset. "
                "The serial protocol sends the least significant bit first.\n")
    assert SP.synth(p) is None


def test_neg_framing_no_lsb_order():
    # framing but the bit ORDER (LSB/MSB-first) is not stated -> byte alignment is
    # a guess -> SKIP.
    p = _HDR + (" - input  clk\n - input  reset\n - input  in\n"
                " - output out_byte (8 bits)\n - output done\n\n"
                "Use one start bit (0), 8 data bits, and 1 stop bit (1). The line "
                "is at logic 1 when idle. Output the received byte. Include a "
                "active-high synchronous reset.\n")
    assert SP.synth(p) is None


def test_neg_framing_extra_unmodeled_output():
    # framing but an EXTRA output we don't model -> SKIP rather than drop it.
    p = _HDR + (" - input  clk\n - input  reset\n - input  in\n"
                " - output done\n - output busy\n\n"
                "Use one start bit (0), 8 data bits, and 1 stop bit (1). The line "
                "is at logic 1 when idle. Include a active-high synchronous reset. "
                "The serial protocol sends the least significant bit first.\n")
    assert SP.synth(p) is None


def test_neg_hdlc_thresholds_noncanonical():
    # run-counter prose but thresholds aren't the canonical consecutive 5/6/7
    # (the action-per-threshold mapping is then undefined for us) -> SKIP.
    p = _HDR + (" - input  clk\n - input  reset\n - input  in\n"
                " - output disc\n - output flag\n - output err\n\n"
                "Seeing exactly 8 consecutive 1s is a flag. The sender inserts a "
                "zero after every 5 consecutive 1s. Signal an error if there are "
                "10 or more consecutive 1s. Create a Moore-type finite state "
                "machine. The reset is active high synchronous.\n")
    assert SP.synth(p) is None


def test_neg_hdlc_missing_output():
    # HDLC thresholds stated but the err output is missing from the interface ->
    # SKIP (we never invent a port).
    p = _HDR + (" - input  clk\n - input  reset\n - input  in\n"
                " - output disc\n - output flag\n\n"
                "Seeing exactly 6 consecutive 1s is a flag. The sender inserts a "
                "zero after every 5 consecutive 1s. Signal an error if there are 7 "
                "or more consecutive 1s. Create a Moore-type finite state machine. "
                "The reset is active high synchronous.\n")
    assert SP.synth(p) is None


def test_neg_2s_complement_not_serial():
    # a 2's-complement that is NOT the serial LSB-first Moore machine -> SKIP.
    p = _HDR + (" - input  a (8 bits)\n - output b (8 bits)\n\n"
                "Compute the 2's complement of the 8-bit input a.\n")
    assert SP.synth(p) is None


def test_neg_2s_complement_no_reset_polarity():
    # serial 2's complementer but the reset POLARITY is not stated -> SKIP.
    p = _HDR + (" - input  clk\n - input  areset\n - input  x\n - output z\n\n"
                "Implement a one-input one-output serial 2's complementer Moore "
                "state machine. x arrives least-significant-bit first. The circuit "
                "uses an asynchronous reset.\n")
    assert SP.synth(p) is None


def test_neg_pattern_timer_multiplier_unstated():
    # pattern-timer prose but the cycle MULTIPLIER is not the stated (delay+1)*M
    # form -> SKIP (we never guess the count datapath).
    p = _HDR + (" - input  clk\n - input  reset\n - input  data\n"
                " - output count (4 bits)\n - output counting\n - output done\n"
                " - input  ack\n\n"
                "When the pattern 1101 is detected, shift in the next 4 bits, "
                "most-significant-bit first. The machine then counts down. Assert "
                "done and wait for ack. The reset is active high synchronous.\n")
    assert SP.synth(p) is None


def test_neg_unrelated_prompt():
    p = _HDR + (" - input  a\n - input  b\n - output out\n\n"
                "Implement an AND gate.\n")
    assert SP.synth(p) is None


def test_neg_written_moore_table_left_to_moore_solver():
    # a prompt that WRITES OUT a Moore transition table is the full_moore_fsm
    # solver's job, not this prose-protocol solver's -> SKIP.
    p = _HDR + (" - input  clk\n - input  reset\n - input  in\n - output out\n\n"
                "Build this Moore FSM with active-high synchronous reset to state A:\n"
                "A (0) --0--> A\n"
                "A (0) --1--> B\n"
                "B (1) --0--> A\n"
                "B (1) --1--> B\n")
    assert SP.synth(p) is None


# --------------------------------------------------------------------------- #
# corpus no-leak sweep — exactly the 5 intended fires, nothing else, and EVERY
# fire host-scores to 0 mismatches (the §4.05 absolute).
# --------------------------------------------------------------------------- #
def test_corpus_no_leak_sweep():
    if not HAVE_DS:
        import pytest
        pytest.skip("verilog-eval dataset not present")
    fires = []
    for f in sorted(DS.glob("*_prompt.txt")):
        prob = f.name[:-len("_prompt.txt")]
        rtl = SP.synth(f.read_text())
        if rtl is not None:
            fires.append(prob)
            if IVERILOG and VVP:
                _host_score(prob, rtl)   # every fire MUST be 0-mismatch
            # and must not be claimed by any FOREIGN registry generator (no steal)
            foreign = [a.key for a in REG.REGISTRY if a.key != "serial_protocol_fsm"
                       and a.generate and a.generate(f.read_text(), "TopModule")]
            assert foreign == [], f"{prob} also solved by {foreign} — steal"
    assert set(fires) == set(POSITIVES), f"unexpected fire set: {sorted(fires)}"


def test_recognize_matches_synth():
    """recognize() must agree with synth() (present iff synth fires)."""
    yes = _HDR + (" - input  clk\n - input  reset\n - input  in\n - output done\n\n"
                  "Use one start bit (0), 8 data bits, and 1 stop bit (1). The line "
                  "is at logic 1 when idle. Include a active-high synchronous reset. "
                  "The serial protocol sends the least significant bit first.\n")
    no = _HDR + " - input  a\n - output out\n\nImplement a buffer.\n"
    assert SP.recognize(yes) == {"present": True}
    assert SP.recognize(no) is None


# Neutral source-bound word-message contract; no external corpus is involved.
def _word_message_prompt(width=4, count=2, marker=1, *, msb_first=True,
                         active_high=True, table=True, reset_alias=False, marker_level=1):
    total = width * count
    positions = []
    for index, ordinal in enumerate(('first', 'second', 'third', 'fourth')[:count]):
        low = (count - 1 - index) * width if msb_first else index * width
        positions.append(f'packet[{low+width-1}:{low}] is the {ordinal} word')
    text = (f'Receive messages of {count} words from a continuous input word stream. '
            f'Discard words until sample_word[{marker}]={marker_level}. That is the first word '
            f'of a message; receive the next {count-1} words regardless of marker. '
            f'Assert done one clock cycle after the final word is received. '
            'done is asserted for exactly one clock cycle. '
            + ', '.join(positions) + '. '
            'packet needs to be valid whenever done is asserted; packet may be '
            'anything at other times. A new first word may be accepted in the '
            'reporting cycle. Words are sampled on the positive edge of clock. '
            f'The reset signal is active {"high" if active_high else "low"} synchronous. '
            'Reset clears any partial message and pending completion. '
            'All multi-bit waveform values are hexadecimal.\n\n')
    if table:
        mask = (1 << width) - 1
        marker_value = (1 << marker) if marker_level else 0
        samples = [(0, not active_high), (marker_value, not active_high)]
        for message in range(5):
            words = [(marker_value | (message * 3)) & mask]
            words += [((message * 5 + index * 7) ^ mask) & mask
                      for index in range(1, count)]
            samples += [(value, not active_high) for value in words]
        samples += [(0, not active_high)] * (count + 1)
        samples += [(marker_value, not active_high), (mask, active_high),
                    (0, active_high), (0, not active_high)]
        samples += [(marker_value, not active_high)] + [(mask, not active_high)] * (count - 1)
        samples += [(0, not active_high)] * 2
        # Interrupt every partial position, including the pending-report cycle.
        for accepted in range(count + 1):
            samples += [(marker_value, not active_high)]
            samples += [(mask, not active_high)] * max(0, accepted - 1)
            samples += [(mask, active_high), (0, not active_high)]
        samples += [(marker_value, not active_high)] + [(mask, not active_high)] * (count - 1)
        samples += [(0, not active_high)] * 2
        rst = 'rst' if reset_alias else 'reset'
        text += f'time clock {rst} sample_word done packet\n'
        text += f'0ns 0 {int(active_high)} 0 x x\n5ns 1 {int(active_high)} 0 0 x\n10ns 0 {int(active_high)} 0 0 x\n'
        partial, pending = [], None
        for index, (value, reset_value) in enumerate(samples):
            reset_value = int(reset_value)
            output = pending
            pending = None
            if reset_value == int(active_high):
                partial, output = [], None
            elif partial or ((value >> marker) & 1) == marker_level:
                partial.append(value)
                if len(partial) == count:
                    shifts = range(count - 1, -1, -1) if msb_first else range(count)
                    pending = sum(word << (width * shift)
                                  for word, shift in zip(partial, shifts))
                    partial = []
            valid = int(output is not None)
            result = f'{output:x}' if valid else 'x'
            rise = 15 + 10 * index
            text += f'{rise}ns 1 {reset_value} {value:x} {valid} {result}\n'
            text += f'{rise+5}ns 0 {reset_value} {value:x} {valid} {result}\n'
        text += '\n'
    return text + (f'module WordCollector (\n input clock,\n input reset,\n'
                   f' input [{width-1}:0] sample_word,\n'
                   f' output [{total-1}:0] packet,\n output done\n);\n')


_WORD_MESSAGE_RTL = '''module WordCollector (
 input clock, input reset, input [3:0] sample_word,
 output reg [7:0] packet, output reg done
);
 reg collecting, pending;
 reg [3:0] first;
 reg [7:0] finished;
 always @(posedge clock) begin
  if (reset) begin
   collecting <= 0; pending <= 0; done <= 0;
   first <= 0; finished <= 0; packet <= 0;
  end else begin
   done <= pending;
   if (pending) packet <= finished;
   pending <= 0;
   if (collecting) begin
    finished <= {first, sample_word};
    pending <= 1; collecting <= 0;
   end else if (sample_word[1]) begin
    first <= sample_word; collecting <= 1;
   end
  end
 end
endmodule
'''


def test_word_message_producer_and_registry_accept_closed_contract():
    prompt = _word_message_prompt()
    rtl = SP.synth(prompt, 'WordCollector')
    assert ('EMITTED' if rtl else 'DECLINED') == 'EMITTED'
    kind, registered = REG.generate(prompt, 'WordCollector')
    assert kind == 'serial_protocol_fsm', {'observed': kind}
    assert registered is not None


def test_word_message_plain_design_document_needs_no_waveform():
    rtl = SP.synth(_word_message_prompt(table=False), 'WordCollector')
    assert ('EMITTED' if rtl else 'DECLINED') == 'EMITTED'


def _word_message_check(tmp_path, prompt, rtl):
    source, design = tmp_path/'prompt.txt', tmp_path/'design.sv'
    source.write_text(prompt); design.write_text(rtl)
    return subprocess.run([sys.executable, str(PROG_DIR/'waveform_table_conformance_check.py'),
                           '--prompt', str(source), '--rtl', str(design), '--top',
                           'WordCollector', '--require-tools'], capture_output=True, text=True)


@pytest.mark.parametrize('width,count,marker,msb,high,alias,falling,plain', [
    (4, 2, 1, True, True, False, False, False),
    (8, 3, 3, True, True, True, False, False),
    (12, 4, 0, False, False, False, False, False),
    (5, 3, 4, False, True, True, True, False),
    (3, 16, 2, True, False, False, False, False),
    (64, 2, 63, False, True, False, False, False),
    (4, 2, 1, True, True, False, False, True),
])
@pytest.mark.skipif(not (IVERILOG and VVP), reason='iverilog/vvp required')
def test_word_message_registry_emission_obeys_temporal_source(tmp_path, width, count, marker,
                                                            msb, high, alias, falling, plain):
    source = _word_message_prompt(width, count, marker, msb_first=msb,
                                  active_high=high, reset_alias=alias)
    prompt = (_word_message_prompt(width, count, marker, msb_first=msb,
                                   active_high=high, table=False) if plain else source)
    if falling:
        prompt = re.sub(r'^(\d+ns) ([01]) ', lambda m: m[1]+' '+str(1-int(m[2]))+' ', prompt, flags=re.M)
        prompt = prompt.replace('positive edge', 'negative edge')
        source = prompt
    kind, rtl = REG.generate(prompt, 'WordCollector')
    assert kind == 'serial_protocol_fsm', {'observed_value': kind}
    assert rtl
    result = _word_message_check(tmp_path, source, rtl)
    assert result.returncode == 0 and 'WTC_PASS' in result.stdout, result.stdout+result.stderr


@pytest.mark.parametrize('before,after', [
    ('messages of 2 words', 'messages of 3 words'),
    ('next 1 words', 'next 2 words'),
    ('sample_word[1]=1', 'sample_word[4]=1'),
    ('sample_word[1]=1', 'sample_word[1]=0 and sample_word[1]=1'),
    ('packet[3:0] is the second word', 'packet[7:4] is the second word'),
    ('final word', 'third word'),
    ('one clock cycle after', 'two clock cycles after'),
    ('A new first word may be accepted in the reporting cycle.',
     'Words in the reporting cycle are ignored.'),
    ('active high synchronous', 'active high asynchronous and synchronous'),
    ('positive edge', 'positive and negative edge'),
    ('input [3:0] sample_word', 'input [4:1] sample_word'),
    ('output done', 'output done, output busy'),
    ('done is asserted for exactly one clock cycle.', 'done is held high until reset.'),
])
def test_word_message_conflicts_decline_normally(before, after):
    prompt = _word_message_prompt(table=False)
    assert before in prompt
    rtl = SP.synth(prompt.replace(before, after), 'WordCollector')
    assert ('EMITTED' if rtl else 'DECLINED') == 'DECLINED'


def test_word_message_conflicting_later_packed_slice_declines():
    prompt = _word_message_prompt(8, 3, 2, table=False)
    assert SP.synth(prompt, 'WordCollector')
    prompt = prompt.replace('packet[7:0] is the third word', 'packet[15:8] is the third word')
    assert ('EMITTED' if SP.synth(prompt, 'WordCollector') else 'DECLINED') == 'DECLINED'


def test_word_message_table_contradiction_declines():
    prompt = _word_message_prompt()
    # Corrupt an actually valid packet observation, retaining a valid table.
    prompt = re.sub(r'^(\d+ns [01] [01] [0-9a-f]+ 1) [0-9a-f]+$', r'\1 0', prompt, flags=re.M)
    assert ('EMITTED' if SP.synth(prompt, 'WordCollector') else 'DECLINED') == 'DECLINED'


def test_word_message_public_header_preserved():
    prompt = _word_message_prompt(table=False)
    header = prompt[prompt.index('module WordCollector'):]
    rtl = SP.synth(prompt, 'WordCollector')
    assert rtl
    assert re.sub(r'\s+', '', header) in re.sub(r'\s+', '', rtl)


@pytest.mark.parametrize('low_marker,renamed,asynchronous', [(True, False, False),
                                                        (False, True, False),
                                                        (False, False, True)])
@pytest.mark.skipif(not (IVERILOG and VVP), reason='iverilog/vvp required')
def test_word_message_general_role_variants(tmp_path, low_marker, renamed, asynchronous):
    prompt = _word_message_prompt(marker_level=0 if low_marker else 1)
    if renamed:
        for old, new in [('sample_word', 'PayloadIn'), ('packet', 'FrameOut'), ('done', 'Complete')]:
            prompt = re.sub(r'\b'+old+r'\b', new, prompt)
    if asynchronous:
        prompt = prompt.replace('synchronous', 'asynchronous')
    kind, rtl = REG.generate(prompt, 'WordCollector')
    assert kind == 'serial_protocol_fsm', {'observed_value': kind}
    result = _word_message_check(tmp_path, prompt, rtl)
    assert result.returncode == 0 and 'WTC_PASS' in result.stdout, result.stdout+result.stderr


@pytest.mark.parametrize('clause', [
    'A new first word must not be accepted in the reporting cycle.',
    'A new first word may not be accepted in the reporting cycle.',
    'A new first word is never accepted in the reporting cycle.',
    'A new first word may be accepted in the reporting cycle only when reset is active.',
    'A new first word may be accepted in the reporting cycle. '
    'During the reporting cycle, do not accept a new first word.',
])
@pytest.mark.parametrize('table', [False, True])
def test_word_message_negated_or_conditional_concurrency_declines(clause, table):
    prompt = _word_message_prompt(table=table).replace(
        'A new first word may be accepted in the reporting cycle.', clause)
    kind, rtl = REG.generate(prompt, 'WordCollector')
    assert ('EMITTED' if rtl else 'DECLINED') == 'DECLINED', {'observed_value': kind}


@pytest.mark.parametrize('before,after', [
    ('Discard words until', 'Do not discard words until'),
    ('Assert done one clock cycle after', 'Never assert done one clock cycle after'),
    ('Assert done one clock cycle after', 'done must not be asserted one clock cycle after'),
    ('Reset clears any partial message and pending completion.',
     'Reset must not clear any partial message or pending completion.'),
])
def test_word_message_other_negated_contract_facts_decline(before, after):
    prompt = _word_message_prompt(table=False).replace(before, after)
    kind, rtl = REG.generate(prompt, 'WordCollector')
    assert ('EMITTED' if rtl else 'DECLINED') == 'DECLINED', {'observed_value': kind}
