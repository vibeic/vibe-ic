"""v1.0.93 #784 — program-first escalation of two prose "MANDATORY pre-emit
self-TB" discriminators into DETERMINISTIC emit-asserts.

ORGANIC-20260617-escalate-prose-mandatory-discriminator-selftbs-to-deterministic-
emit-gates (program-first escalation of #718/#733/#741/#776). The lessons corpus
already PRESCRIBES the discriminators, but a fresh clean-room author reads the
lesson, cites it, then overrides it via §4-E round after round — advisory prose
cannot reach zero. This mechanizes the two discriminators the lessons name as
deterministic emit-asserts the author cannot override:

  (1) shift-implemented-as-rotate  — spec describes a SHIFTER (not explicitly
      rotate-only) but the RTL is an unambiguous barrel-ROTATE wrap. The prose
      "'shifts or rotates' is NOT rotate-only → logical shift" + the mandatory
      all-ones>>max self-TB were prose-only.
  (2) waveform-peak-hold-dropped   — spec requires a triangle/ramp peak-HOLD but
      the RTL drops it (immediate direction toggle at the extreme, no
      hold/dwell state). The prose "keep peak-hold unless spec forbids" was
      prose-only.

ZERO-FALSE-FIRE is the binding constraint (these BLOCK emit; a false block
breaks a CORRECT sample). Every §4.05 negative is pinned below. Both rule names
are asserted present in gates_atomic._BLOCKING_CONFORMANCE_RULES.

chip-AGNOSTIC: fixtures use generic TopModule / din / dout / wave shapes only.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import spec_conformance_check as scc  # noqa: E402
from _specrtl_common import (extract_spec_contract, parse_rtl_ports,  # noqa: E402
                             strip_comments)

HARNESS = Path(__file__).resolve().parent.parent.parent / "benchmark"
GATES = HARNESS / "gates_atomic.py"
PROGRAM = Path(__file__).resolve().parent.parent / "spec_conformance_check.py"

RULE_SHIFT = "shift-implemented-as-rotate"
RULE_HOLD = "waveform-peak-hold-dropped"


def _findings(spec_text: str, rtl: str, rule: str = None):
    spec = extract_spec_contract(spec_text, confirm=False)
    src = strip_comments(rtl)
    nm, ports = parse_rtl_ports(src, "TopModule")
    fs = scc.check(spec, nm, ports, scc.classify_rtl_resets(src),
                   scc._rtl_output_is_registered(src, ports), "t.sv", src,
                   spec_text=spec_text)
    return [f for f in fs if (rule is None or f.rule == rule)]


# ===========================================================================
# (1) shift-implemented-as-rotate
# ===========================================================================
_SHIFT_SPEC = ("Build an 8-bit barrel SHIFTER. The shift amount arrives on "
               "ctrl; shift the input by ctrl positions.\n\n"
               " - input  [7:0] din\n - input  [2:0] ctrl\n"
               " - output [7:0] dout\n")

# unambiguous wrap-around rotate via OR of two OPPOSITE shifts of one signal
_ROTATE_OR_RTL = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
                  "                 output [7:0] dout);\n"
                  "  assign dout = (din >> ctrl) | (din << (8-ctrl));\n"
                  "endmodule\n")
# unambiguous wrap-around rotate via a fill-free same-vector concat
_ROTATE_CONCAT_RTL = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
                      "                 output reg [7:0] dout);\n"
                      "  always @* dout = {din[0], din[7:1]};\n"
                      "endmodule\n")
# correct LOGICAL shift (zero-fill) — must NEVER fire
_LOGICAL_SHIFT_RTL = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
                      "                 output [7:0] dout);\n"
                      "  assign dout = din >> ctrl;\n"
                      "endmodule\n")
# correct logical shift expressed as a ZERO-fill concat — must NEVER fire
_ZEROFILL_CONCAT_RTL = ("module TopModule(input [7:0] din,\n"
                        "                 output reg [7:0] dout);\n"
                        "  always @* dout = {din[6:0], 1'b0};\n"
                        "endmodule\n")


def test_shift_rule_fires_on_or_rotate_under_shift_spec():
    fs = _findings(_SHIFT_SPEC, _ROTATE_OR_RTL, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs
    assert "ROTATE" in fs[0].message
    assert "all-ones" in fs[0].message  # the named mandatory self-TB


def test_shift_rule_fires_on_concat_rotate_under_shift_spec():
    fs = _findings(_SHIFT_SPEC, _ROTATE_CONCAT_RTL, RULE_SHIFT)
    assert [f.severity for f in fs] == ["ERROR"], fs


# §4.05 negatives — must NOT fire
def test_shift_rule_silent_on_correct_logical_shift():
    assert _findings(_SHIFT_SPEC, _LOGICAL_SHIFT_RTL, RULE_SHIFT) == []


def test_shift_rule_silent_on_zerofill_concat_shift():
    assert _findings(_SHIFT_SPEC, _ZEROFILL_CONCAT_RTL, RULE_SHIFT) == []


def test_shift_rule_silent_on_explicit_rotate_only_spec():
    # §4.05: a genuine rotate-only spec + rotate RTL is CORRECT — disarmed
    rot_spec = ("Build an 8-bit barrel ROTATOR: rotate the input left by ctrl "
                "positions (a circular shift — the bits wrap around).\n\n"
                " - input  [7:0] din\n - input  [2:0] ctrl\n"
                " - output [7:0] dout\n")
    assert _findings(rot_spec, _ROTATE_OR_RTL, RULE_SHIFT) == []
    assert _findings(rot_spec, _ROTATE_CONCAT_RTL, RULE_SHIFT) == []


def test_shift_or_rotates_disjunction_spec_BLOCKS_rotate_rtl():
    # ORGANIC-20260618 (RTLLM round-19 barrel_shifter): a spec that OFFERS BOTH
    # operations in a disjunction ("shifts or rotates") is NOT rotate-only — the
    # lessons corpus binds it to a LOGICAL shift with zero-fill. A rotate RTL
    # under such a spec is WRONG and MUST be blocked. (Supersedes the prior
    # conservative under-firing pin, which let the wrong rotate design pass the
    # hidden right-shift TB.)
    spec = _SHIFT_SPEC.replace("Build an 8-bit barrel SHIFTER",
                               "Build an 8-bit unit that shifts or rotates")
    fs = _findings(spec, _ROTATE_OR_RTL, RULE_SHIFT)
    assert any(f.rule == "shift-implemented-as-rotate" for f in fs), fs


def test_shift_rule_still_silent_on_rotate_ONLY_spec_no_leak():
    # §4.05 NO-LEAK: a GENUINE rotate-only spec (rotate / circular present, NO
    # shift-or-rotate disjunction) still disarms — a correct rotate design must
    # NOT be false-blocked.
    rot_only = ("Build an 8-bit barrel ROTATOR: rotate the input left by ctrl "
                "positions (a circular shift — the bits wrap around).\n\n"
                " - input  [7:0] din\n - input  [2:0] ctrl\n"
                " - output [7:0] dout\n")
    assert _findings(rot_only, _ROTATE_OR_RTL, RULE_SHIFT) == []


def test_shift_or_rotates_disjunction_silent_on_correct_logical_shift():
    # §4.05 NO-FALSE-BLOCK: the SAME "shifts or rotates" spec with a CORRECT
    # logical-shift RTL (zero-fill) must stay silent — only the rotate form fires.
    spec = _SHIFT_SPEC.replace("Build an 8-bit barrel SHIFTER",
                               "Build an 8-bit unit that shifts or rotates")
    good = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
            "                 output [7:0] dout);\n"
            "  assign dout = din >> ctrl;\n"
            "endmodule\n")
    assert _findings(spec, good, RULE_SHIFT) == []


def test_shift_rule_silent_on_or_with_nonshift_mask():
    # logical shift OR-ed with a non-shift operand is NOT a wrap rotate
    rtl = ("module TopModule(input [7:0] din, input [2:0] ctrl,\n"
           "                 input [7:0] mask, output [7:0] dout);\n"
           "  assign dout = (din << ctrl) | mask;\n"
           "endmodule\n")
    assert _findings(_SHIFT_SPEC, rtl, RULE_SHIFT) == []


def test_shift_rule_silent_on_same_direction_or():
    # two SAME-direction shifts OR-ed (a funnel build) is NOT a rotate
    rtl = ("module TopModule(input [7:0] a, input [7:0] b,\n"
           "                 output [7:0] dout);\n"
           "  assign dout = (a << 2) | (b << 4);\n"
           "endmodule\n")
    assert _findings(_SHIFT_SPEC, rtl, RULE_SHIFT) == []


# ===========================================================================
# (2) waveform-peak-hold-dropped
# ===========================================================================
_TRI_HOLD_SPEC = ("Build a triangle waveform generator. The output ramps up to "
                  "the maximum, then HOLDS the peak for 4 cycles, then ramps "
                  "down to the minimum and repeats.\n\n"
                  " - input  clk\n - input  rst\n - output [7:0] wave\n")

# drops the hold: direction toggles the instant the extreme is hit, no dwell
_NO_HOLD_RTL = ("module TopModule(input clk, input rst,\n"
                "                 output reg [7:0] wave);\n"
                "  reg dir;\n"
                "  always @(posedge clk) begin\n"
                "    if (rst) begin wave <= 0; dir <= 1; end\n"
                "    else begin\n"
                "      if (wave == 8'd255) dir <= ~dir;\n"
                "      else if (wave == 8'd0) dir <= ~dir;\n"
                "      wave <= dir ? wave + 1 : wave - 1;\n"
                "    end\n"
                "  end\n"
                "endmodule\n")

# correct peak-hold: carries a dwell counter — must NEVER fire
_PEAK_HOLD_RTL = ("module TopModule(input clk, input rst,\n"
                  "                 output reg [7:0] wave);\n"
                  "  reg dir; reg [1:0] hold_cnt;\n"
                  "  always @(posedge clk) begin\n"
                  "    if (rst) begin wave <= 0; dir <= 1; hold_cnt <= 0; end\n"
                  "    else if (wave == 8'd255 && hold_cnt < 3)\n"
                  "      hold_cnt <= hold_cnt + 1;\n"
                  "    else if (wave == 8'd255) begin\n"
                  "      dir <= ~dir; hold_cnt <= 0;\n"
                  "    end else wave <= dir ? wave + 1 : wave - 1;\n"
                  "  end\n"
                  "endmodule\n")


def test_hold_rule_fires_on_dropped_hold_under_hold_spec():
    fs = _findings(_TRI_HOLD_SPEC, _NO_HOLD_RTL, RULE_HOLD)
    assert [f.severity for f in fs] == ["ERROR"], fs
    assert fs[0].symbol == "dir"
    assert "hold" in fs[0].message.lower()


# §4.05 negatives — must NOT fire
def test_hold_rule_silent_on_correct_peak_hold_rtl():
    assert _findings(_TRI_HOLD_SPEC, _PEAK_HOLD_RTL, RULE_HOLD) == []


def test_hold_rule_silent_on_explicit_no_hold_spec():
    # §4.05: a spec that EXPLICITLY forbids the hold must not fire
    spec = ("Build a triangle waveform generator. Ramp up to the maximum then "
            "immediately reverse — do NOT hold the peak.\n\n"
            " - input  clk\n - input  rst\n - output [7:0] wave\n")
    assert _findings(spec, _NO_HOLD_RTL, RULE_HOLD) == []


def test_hold_rule_silent_on_plain_sawtooth_spec():
    # a plain sawtooth / no explicit hold spec must not fire
    spec = ("Build a sawtooth ramp generator: the output ramps up to the "
            "maximum then resets to zero and repeats.\n\n"
            " - input  clk\n - output [7:0] wave\n")
    assert _findings(spec, _NO_HOLD_RTL, RULE_HOLD) == []


def test_hold_rule_silent_on_plain_triangle_no_hold_clause_spec():
    # a triangle spec with NO explicit hold clause must not fire (under-fire)
    spec = ("Build a triangle waveform generator. The output ramps up to the "
            "maximum then ramps back down to the minimum, repeating.\n\n"
            " - input  clk\n - output [7:0] wave\n")
    assert _findings(spec, _NO_HOLD_RTL, RULE_HOLD) == []


# ===========================================================================
# cross-rule: an unrelated (non-shifter / non-waveform) design fires NEITHER
# ===========================================================================
def test_unrelated_design_fires_neither_rule():
    spec = ("Build a 4-bit binary up counter that increments every clock.\n\n"
            " - input  clk\n - output [3:0] cnt\n")
    rtl = ("module TopModule(input clk, output reg [3:0] cnt);\n"
           "  always @(posedge clk) cnt <= cnt + 1;\n"
           "endmodule\n")
    fs = _findings(spec, rtl)
    assert [f for f in fs if f.rule in (RULE_SHIFT, RULE_HOLD)] == []


# ===========================================================================
# subprocess CLI: returncode + JSON shape
# ===========================================================================
def _run_cli(tmp_path, spec_text, rtl, suffix=".md"):
    spec_f = tmp_path / ("spec" + suffix)
    spec_f.write_text(spec_text)
    rtl_f = tmp_path / "dut.v"
    rtl_f.write_text(rtl)
    out_json = tmp_path / "findings.json"
    r = subprocess.run(
        [sys.executable, str(PROGRAM), "--spec", str(spec_f),
         "--top", "TopModule", "--json", str(out_json), str(rtl_f)],
        capture_output=True, text=True, timeout=120)
    findings = json.loads(out_json.read_text()) if out_json.is_file() else []
    return r, findings


def test_cli_shift_rotate_fails_with_error(tmp_path):
    r, fnd = _run_cli(tmp_path, _SHIFT_SPEC, _ROTATE_OR_RTL)
    assert r.returncode == 1, r.stdout + r.stderr
    assert any(f["rule"] == RULE_SHIFT and f["severity"] == "ERROR"
               for f in fnd), fnd


def test_cli_logical_shift_passes(tmp_path):
    r, fnd = _run_cli(tmp_path, _SHIFT_SPEC, _LOGICAL_SHIFT_RTL)
    assert not any(f["rule"] == RULE_SHIFT for f in fnd), fnd


def test_cli_dropped_hold_fails_with_error(tmp_path):
    r, fnd = _run_cli(tmp_path, _TRI_HOLD_SPEC, _NO_HOLD_RTL)
    assert r.returncode == 1, r.stdout + r.stderr
    assert any(f["rule"] == RULE_HOLD and f["severity"] == "ERROR"
               for f in fnd), fnd


def test_cli_correct_hold_passes(tmp_path):
    r, fnd = _run_cli(tmp_path, _TRI_HOLD_SPEC, _PEAK_HOLD_RTL)
    assert not any(f["rule"] == RULE_HOLD for f in fnd), fnd


# ===========================================================================
# both rule names are wired into the emit-blocking set
# ===========================================================================
def test_both_rules_are_emit_blocking():
    src = GATES.read_text()
    # _BLOCKING_CONFORMANCE_RULES is a module-local set; assert by source.
    import re
    m = re.search(r"_BLOCKING_CONFORMANCE_RULES\s*=\s*\{(.*?)\}", src, re.S)
    assert m, "could not locate _BLOCKING_CONFORMANCE_RULES set"
    block_src = m.group(1)
    assert RULE_SHIFT in block_src, block_src
    assert RULE_HOLD in block_src, block_src


# ===========================================================================
# gates_atomic end-to-end: BLOCK the anti-patterns, EMIT the correct designs
# ===========================================================================
def _stage(tmp_path, prompt_text, sample_body):
    ds = tmp_path / "ds"; ds.mkdir(exist_ok=True)
    (ds / "ProbP_prompt.txt").write_text(prompt_text)
    wd = tmp_path / "run" / "work" / "ProbP"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "spec.yaml").write_text("design:\n  name: TopModule\n")
    (wd / "sample.sv").write_text(sample_body)
    return ds, tmp_path / "run"


def _run_gate(ds, run):
    return subprocess.run(
        [sys.executable, str(GATES), "--prob", "ProbP",
         "--workdir", str(run / "work"), "--dataset", str(ds),
         "--prompt-suffix", "_prompt.txt", "--top-module", "TopModule"],
        capture_output=True, text=True, timeout=300)


def _block_rules(run):
    gates = json.loads((run / "work" / "ProbP" / "gates.json").read_text())
    blk = gates["steps"].get("structural_emit_block", {})
    return gates, {f["rule"] for f in blk.get("findings", [])}


def test_gate_blocks_rotate_under_shift_spec(tmp_path):
    ds, run = _stage(tmp_path, _SHIFT_SPEC, _ROTATE_OR_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is False
    assert RULE_SHIFT in rules
    assert not (run / "samples" / "ProbP_sample01.sv").exists()


def test_gate_emits_logical_shift(tmp_path):
    ds, run = _stage(tmp_path, _SHIFT_SPEC, _LOGICAL_SHIFT_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is True
    assert RULE_SHIFT not in rules
    assert (run / "samples" / "ProbP_sample01.sv").exists()


def test_gate_blocks_dropped_hold_under_hold_spec(tmp_path):
    ds, run = _stage(tmp_path, _TRI_HOLD_SPEC, _NO_HOLD_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 1, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is False
    assert RULE_HOLD in rules
    assert not (run / "samples" / "ProbP_sample01.sv").exists()


def test_gate_emits_correct_peak_hold(tmp_path):
    ds, run = _stage(tmp_path, _TRI_HOLD_SPEC, _PEAK_HOLD_RTL)
    r = _run_gate(ds, run)
    assert r.returncode == 0, r.stdout + r.stderr
    gates, rules = _block_rules(run)
    assert gates["hard_gates_pass"] is True
    assert RULE_HOLD not in rules
    assert (run / "samples" / "ProbP_sample01.sv").exists()
