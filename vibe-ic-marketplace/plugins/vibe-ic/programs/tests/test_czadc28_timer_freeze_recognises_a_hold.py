"""timer_freeze_after_state_check: a freeze implemented as a HOLD is a freeze.

Two false positives on CORRECT RTL, measured 2026-09-06 on `u_hawaii_adc`
(ihp-sg13g2, image 0.3.46), fixed together here:

  1. The check only recognised a freeze written as an ASSIGNMENT of a
     constant to the counter in a `<state>`-keyed branch. A freeze written
     as a HOLD — the state-keyed branch simply not assigning the counter —
     is the same freeze and was flagged. The finding message named
     `if (!<state>)` as a remedy the code had never implemented.
  2. `_enclosing_block_text` searched back a FIXED 1500 characters for the
     enclosing `always` and, when it found none, analysed that 1500-character
     slice as though it were a block. On the real design both flagged
     counters sat far enough into a long `always` that the slice began
     mid-statement and could not contain the freeze branch at any polarity.

The direction each test pins was written down BEFORE it was run. Every
`must still FAIL` case below is a negative control: if the fix had made the
check unable to fail, these are what would have caught it. The headline
negative control — the v052 `wake_ctrl.v` specimen this gate was born from —
lives in `test_timer_freeze_after_state_check.py` and is unchanged.

NOT a whitelist, NOT an exemption: `// timer_freeze_check: ok-unconditional`
is untouched and unused here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "timer_freeze_after_state_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import timer_freeze_after_state_check as chk  # noqa: E402


def _audit(tmp_path: Path, name: str, src: str):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.v").write_text(src)
    return chk.audit(d)


# ---------------------------------------------------------------------------
# The shape the real design uses: freeze by HOLD, branch keyed on `!enable`.
# Reduced from `u_hawaii_adc_readout.v`; the serialiser's counters hold while
# `enable` is low and only the output strobes are cleared.
# ---------------------------------------------------------------------------
def _adc_readout(freeze_branch: bool) -> str:
    hold = """
        end else if (!enable) begin
            sample_valid <= 1'b0;
            frame_start  <= 1'b0;
            dout_valid   <= 1'b0;
""" if freeze_branch else ""
    return """\
module readout #(parameter integer DATA_WIDTH = 16, parameter integer CHANNELS = 6) (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  enable,
    input  wire                  window_last,
    output reg                   dout,
    output reg                   dout_valid,
    output reg                   frame_start,
    output reg  [DATA_WIDTH-1:0] sample,
    output reg  [2:0]            sample_ch,
    output reg                   sample_valid
);
    localparam integer BIT_W = 4;
    reg                  shifting;
    reg [BIT_W-1:0]      bit_count;
    reg [2:0]            ch_count;
    reg [DATA_WIDTH-1:0] shreg;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            shifting     <= 1'b0;
            bit_count    <= {BIT_W{1'b0}};
            ch_count     <= 3'd0;
            shreg        <= {DATA_WIDTH{1'b0}};
            dout         <= 1'b0;
            dout_valid   <= 1'b0;
            frame_start  <= 1'b0;
            sample       <= {DATA_WIDTH{1'b0}};
            sample_ch    <= 3'd0;
            sample_valid <= 1'b0;__HOLD__
        end else begin
            sample_valid <= 1'b0;
            frame_start  <= 1'b0;
            dout_valid   <= 1'b0;
            if (!shifting) begin
                if (enable && window_last) begin
                    shreg        <= {DATA_WIDTH{1'b0}};
                    sample       <= {DATA_WIDTH{1'b0}};
                    sample_ch    <= 3'd0;
                    sample_valid <= 1'b1;
                    shifting     <= 1'b1;
                    bit_count    <= {BIT_W{1'b0}};
                    ch_count     <= 3'd0;
                    frame_start  <= 1'b1;
                end
            end else begin
                dout       <= shreg[DATA_WIDTH-1];
                dout_valid <= 1'b1;
                shreg      <= {shreg[DATA_WIDTH-2:0], 1'b0};
                if (bit_count == DATA_WIDTH[BIT_W-1:0] - 1'b1) begin
                    bit_count <= {BIT_W{1'b0}};
                    if (ch_count == CHANNELS[2:0] - 3'd1) begin
                        shifting <= 1'b0;
                    end else begin
                        sample_ch    <= ch_count + 3'd1;
                        sample_valid <= 1'b1;
                        ch_count     <= ch_count + 3'd1;
                    end
                end else begin
                    bit_count <= bit_count + 1'b1;
                end
            end
        end
    end
endmodule
""".replace("__HOLD__", hold)


def test_freeze_by_hold_is_a_freeze(tmp_path):
    """The real design's shape. PASS is the expected direction.

    Proven by SIMULATION, not by assertion, before this test was written:
    with the `else if (!enable)` branch present a testbench that drops
    `enable` mid-frame holds `bit_count` at 4 and emits no further payload
    bit; with it removed `bit_count` runs 4 -> 12.
    """
    assert _audit(tmp_path, "held", _adc_readout(freeze_branch=True)) == []


def test_the_same_module_without_the_hold_branch_still_fails(tmp_path):
    """Negative control for the test above: the RTL that simulation showed
    keeps shifting must stay RED, and on BOTH counters."""
    findings = _audit(tmp_path, "unheld", _adc_readout(freeze_branch=False))
    assert {f.counter for f in findings} == {"bit_count", "ch_count"}
    assert {f.state_bit for f in findings} == {"enable"}


def test_the_freeze_branch_is_found_however_far_back_it_is(tmp_path):
    """Defect 2. The freeze branch sits >1500 characters before the
    increment; the old fixed-width lookback could not see it and had no way
    to say so — it analysed a slice that began mid-statement."""
    filler = "\n".join(
        f"            scratch[{i}] <= scratch[{i}] ^ 8'h{i:02x};" for i in range(120)
    )
    src = f"""\
module wide (input wire clk, input wire rst_n, input wire awake);
    reg [7:0] scratch [0:127];
    reg [23:0] cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 24'd0;
        end else if (awake) begin
{filler}
        end else begin
            cnt <= cnt + 24'd1;
        end
    end
endmodule
"""
    assert len(src) > 1500
    assert _audit(tmp_path, "wide", src) == []


def test_a_counter_that_advances_in_every_branch_is_not_gated(tmp_path):
    """The hole a bare `is the token mentioned on the path?` rule would open:
    both branches advance the counter, so no state of `awake` stops it. Must
    stay RED."""
    src = """\
module both (input wire clk, input wire awake);
    reg [9:0] cnt;
    always @(posedge clk) begin
        if (awake) cnt <= cnt + 10'd1;
        else       cnt <= cnt + 10'd1;
    end
endmodule
"""
    findings = _audit(tmp_path, "both", src)
    # BOTH increment sites are flagged: each is judged on its own.
    assert [(f.counter, f.state_bit) for f in findings] == [
        ("cnt", "awake"), ("cnt", "awake"),
    ]


def test_token_inside_a_sibling_branch_body_does_not_count(tmp_path):
    """The v052 shape, generalised: `awake` appears only in a condition
    NESTED inside a sibling branch, never in a branch condition of the chain
    that holds the increment. Must stay RED — this is the exact miss the
    strict shape existed to prevent."""
    src = """\
module nested (input wire clk, input wire porb, input wire cmd_valid,
               input wire [7:0] cmd_op, input wire awake, output reg req);
    reg [23:0] cnt;
    always @(posedge clk or negedge porb) begin
        if (!porb) begin
            cnt <= 24'd0;
        end else begin
            if (cmd_valid) begin
                if (!awake && cmd_op != 8'h74) req <= 1'b1;
            end else begin
                cnt <= cnt + 24'd1;
            end
        end
    end
endmodule
"""
    findings = _audit(tmp_path, "nested", src)
    assert [f.counter for f in findings] == ["cnt"]


def test_a_freeze_in_a_different_always_block_does_not_count(tmp_path):
    """A declared false negative of this heuristic stays a false negative
    rather than silently becoming a pass: the freeze branch is in another
    `always`, so the increment's own block is ungated. Must stay RED."""
    src = """\
module split (input wire clk, input wire awake);
    reg [9:0] cnt;
    reg       held;
    always @(posedge clk) begin
        if (awake) held <= 1'b1;
        else       held <= 1'b0;
    end
    always @(posedge clk) begin
        cnt <= cnt + 10'd1;
    end
endmodule
"""
    findings = _audit(tmp_path, "split", src)
    assert [f.counter for f in findings] == ["cnt"]


def test_the_remedy_the_finding_names_is_accepted(tmp_path):
    """`if (!<state>) <increment>` — named as a remedy by this gate's own
    docstring and by its finding message since v0.64, and rejected by the
    code until now. The counter cannot advance while the token is high."""
    src = """\
module gated (input wire clk, input wire awake);
    reg [9:0] cnt;
    always @(posedge clk) begin
        if (!awake) cnt <= cnt + 10'd1;
    end
endmodule
"""
    assert _audit(tmp_path, "gated", src) == []


@pytest.mark.parametrize("freeze", [
    "else if (awake) cnt <= 10'd0;",          # v0.64 shape: assign a constant
    "else if (awake) held <= 1'b1;",          # same branch, HOLD instead
    "else if (!awake) held <= 1'b1;",         # the ADC's polarity, HOLD
])
def test_every_accepted_freeze_shape_passes(tmp_path, freeze):
    src = f"""\
module shapes (input wire clk, input wire rst_n, input wire awake);
    reg [9:0] cnt;
    reg       held;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) cnt <= 10'd0;
        {freeze}
        else cnt <= cnt + 10'd1;
    end
endmodule
"""
    assert _audit(tmp_path, "shapes", src) == []


def test_dropping_the_freeze_from_each_shape_reddens_it(tmp_path):
    """Mutation control for the parametrised test above: with the middle
    branch gone every shape must FAIL. A check that cannot fail is not a
    check."""
    src = """\
module shapes (input wire clk, input wire rst_n, input wire awake);
    reg [9:0] cnt;
    reg       held;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) cnt <= 10'd0;
        else cnt <= cnt + 10'd1;
    end
endmodule
"""
    findings = _audit(tmp_path, "shapes_mut", src)
    assert [f.counter for f in findings] == ["cnt"]


def test_the_finding_still_says_freeze(tmp_path):
    """The message is the only thing an author reads. It must keep naming
    the remedy, and it must now name the HOLD form too."""
    src = """\
module m (input wire clk, input wire enable);
    reg [7:0] tick;
    always @(posedge clk) tick <= tick + 8'd1;
endmodule
"""
    findings = _audit(tmp_path, "msg", src)
    assert len(findings) == 1
    reason = findings[0].reason.lower()
    assert "freeze" in reason
    assert "hold" in reason
    assert "enable" in reason
