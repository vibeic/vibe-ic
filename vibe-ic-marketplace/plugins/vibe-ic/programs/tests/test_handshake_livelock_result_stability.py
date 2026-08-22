"""ORGANIC #523 — multi-cycle valid/ready handshake structural checks.

Two recurring author bugs in an N-cycle valid/ready datapath that pass the
author's OWN testbench but hang / corrupt under a standard always-ready
consumer:
  * CHECK 1 LIVELOCK   — a load/kick-off arm guarded by a valid trigger but
                         missing a busy-exclusion term → re-arms every cycle
                         under an always-ready consumer → counter never reaches
                         terminal → hang.
  * CHECK 2 RESULT     — a result output driven by a free-running working
    INSTABILITY          shift/accumulate register → the value moves on after
                         valid → a next-cycle consumer reads corruption.

The #511 no-leak property is LOAD-BEARING here: both are GUARD-adding fixes, so
a false flag would block a correct design. The check therefore gates on the
presence of a `*valid` output + `*ready` input handshake pair and uses the
self-set-busy-flag discriminator (the correct radix2_div is saved by `~start_cnt`
which it self-sets in the load arm; the buggy author drops it).

chip-AGNOSTIC: synthetic Verilog + the real correct-design corpus when on-host.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import handshake_livelock_result_stability_check as H  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402


def _errs(rtl):
    fl, st = H.check_text(rtl)
    return st, [(x.rule, x.symbol) for x in fl if x.severity == "ERROR"]


# ---- correct reference (radix2_div-shaped): load guarded by ~start_cnt -------
_CORRECT = """\
module mcdiv(
  input wire clk, input wire rst,
  input wire [7:0] a, input wire [7:0] b,
  input wire opn_valid, output reg res_valid,
  input wire res_ready, output wire [15:0] result);
  reg [15:0] SR; reg [3:0] cnt; reg start_cnt;
  assign result = SR;
  always @(posedge clk) begin
    if (rst) begin SR<=0; cnt<=0; start_cnt<=1'b0; end
    else if (~start_cnt & opn_valid & ~res_valid) begin
      cnt <= 1; start_cnt <= 1'b1; SR <= {8'b0, a};
    end else if (start_cnt) begin
      if (cnt[3]) begin cnt <= 0; start_cnt <= 1'b0; SR <= SR + b; end
      else begin cnt <= cnt + 1; SR <= {SR[14:0], 1'b0}; end
    end
  end
  always @(posedge clk) res_valid <= rst ? 1'b0 : cnt[3] ? 1'b1 :
                                     (res_valid & res_ready) ? 1'b0 : res_valid;
endmodule
"""

# ---- BUG 1: same design but load drops the ~start_cnt busy-exclusion ----------
_LIVELOCK = _CORRECT.replace("~start_cnt & opn_valid & ~res_valid",
                             "opn_valid & ~res_valid")

# ---- BUG 2: result driven by a FREE-RUNNING shift register -------------------
_RESULT_UNSTABLE = """\
module mcacc(
  input wire clk, input wire rst,
  input wire din, input wire opn_valid,
  output reg res_valid, input wire res_ready,
  output wire [15:0] result);
  reg [15:0] shifter; reg [3:0] cnt; reg start_cnt;
  assign result = shifter;
  always @(posedge clk) begin
    if (rst) begin cnt<=0; start_cnt<=1'b0; end
    else if (~start_cnt & opn_valid) begin cnt<=1; start_cnt<=1'b1; end
    else if (start_cnt) begin
      if (cnt[3]) begin cnt<=0; start_cnt<=1'b0; end
      else cnt<=cnt+1;
    end
  end
  // free-running: shifter updates EVERY cycle (no busy/state guard) → keeps
  // moving after res_valid → a next-cycle consumer reads corruption.
  always @(posedge clk) begin
    if (rst) shifter <= 0;
    else shifter <= {shifter[14:0], din};
  end
  always @(posedge clk) res_valid <= rst ? 1'b0 : cnt[3] ? 1'b1 :
                                     (res_valid & res_ready) ? 1'b0 : res_valid;
endmodule
"""


def test_correct_handshake_is_clean():
    st, errs = _errs(_CORRECT)
    assert st == "CHECKED"
    assert errs == [], errs


def test_livelock_flagged():
    st, errs = _errs(_LIVELOCK)
    assert st == "CHECKED"
    assert any(r == "handshake-load-livelock" for r, _ in errs), errs


def test_result_instability_flagged():
    st, errs = _errs(_RESULT_UNSTABLE)
    assert st == "CHECKED"
    assert any(r == "handshake-result-unstable" for r, _ in errs), errs


def test_no_handshake_ports_is_skipped():
    # a streaming bit-serial multiplier (spm-shaped): no valid/ready ports.
    rtl = """\
module spm(input wire clk, input wire rst, input wire [31:0] x,
           input wire y, output reg p);
  reg [32:0] acc;
  wire [32:0] full = acc + (y ? {1'b0,x} : 33'b0);
  always @(posedge clk) begin
    if (rst) begin acc<=0; p<=0; end
    else begin p <= full[0]; acc <= {1'b0, full[32:1]}; end
  end
endmodule
"""
    st, errs = _errs(rtl)
    assert st.startswith("SKIP")
    assert errs == []


def test_idle_state_guard_is_not_livelock():
    # a load guarded by state==IDLE (instead of ~start_cnt) is a valid
    # busy-exclusion → must NOT fire.
    rtl = """\
module m(input wire clk, input wire rst, input wire opn_valid,
         output reg res_valid, input wire res_ready, output wire [7:0] result);
  localparam IDLE=2'd0, RUN=2'd1; reg [1:0] state; reg [3:0] cnt; reg [7:0] acc;
  assign result = acc;
  always @(posedge clk) begin
    if (rst) begin state<=IDLE; cnt<=0; acc<=0; res_valid<=0; end
    else case (state)
      IDLE: if (opn_valid) begin cnt <= 1; state <= RUN; end
      RUN:  if (cnt[3]) begin state<=IDLE; res_valid<=1'b1; acc<=acc+1; end
            else cnt <= cnt + 1;
    endcase
  end
endmodule
"""
    st, errs = _errs(rtl)
    assert st == "CHECKED"
    assert not any(r == "handshake-load-livelock" for r, _ in errs), errs


def test_no_false_positive_on_correct_corpus():
    # #523 NEGATIVE acceptance (#511 no-leak, load-bearing): the existing correct
    # multi-cycle / streaming designs must produce ZERO findings when on-host.
    import pytest
    base = require_corpus()
    globs = [
        "spm_e2e_v0320/phase2/stage1/rtl",
        "sha256_e2e_v0320/phase2/stage1/rtl",
        "subservient_e2e_v0320/phase2/stage1/rtl",
        "_extbench/RTLLM/Arithmetic/Divider/radix2_div",
    ]
    files = []
    for g in globs:
        d = base / g
        if d.is_dir():
            files += [p for p in d.rglob("*.v") if p.is_file()]
    if not files:
        pytest.skip("correct RTL corpus not on this host")
    pairs, _ = H.check_paths(files)
    errs = [(str(fp), fd.rule, fd.symbol) for fp, fd in pairs
            if fd.severity == "ERROR"]
    assert errs == [], f"false-positive on known-good corpus: {errs}"


def test_cli_negative_corpus_exit_zero(tmp_path):
    # the acceptance NEGATIVE command shape: running the checker over the correct
    # corpus exits 0. Off-host we synthesise the correct design and assert exit 0.
    f = tmp_path / "correct.v"
    f.write_text(_CORRECT)
    rc = H.main([str(f)])
    assert rc == 0


def test_cli_positive_livelock_exit_one(tmp_path):
    f = tmp_path / "bug.v"
    f.write_text(_LIVELOCK)
    rc = H.main([str(f)])
    assert rc == 1


def _spec_conf_rules(tmp_path, rtl):
    import json
    import spec_conformance_check as S
    (tmp_path / "d.v").write_text(rtl)
    spec = tmp_path / "spec.json"
    spec.write_text('{"fsm_output_style": null}')
    S.main(["--rtl-dir", str(tmp_path), "--spec", str(spec),
            "--json", str(tmp_path / "out.json")])
    out = json.loads((tmp_path / "out.json").read_text())
    findings = out if isinstance(out, list) else out.get("findings", [])
    return [f.get("rule") for f in findings]


def test_wired_into_spec_conformance_fires(tmp_path):
    # the #517/#518 non-dormant lesson: the check must actually FIRE via
    # spec_conformance, not just standalone.
    rules = _spec_conf_rules(tmp_path, _LIVELOCK)
    assert "handshake-load-livelock" in rules, rules


def test_wired_into_spec_conformance_clean_on_correct(tmp_path):
    rules = _spec_conf_rules(tmp_path, _CORRECT)
    assert "handshake-load-livelock" not in rules
    assert "handshake-result-unstable" not in rules
