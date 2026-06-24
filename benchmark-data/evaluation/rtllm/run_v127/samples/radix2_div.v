// radix2_div — simplified radix-2 (shift-subtract restoring) divider on 8-bit
// signed/unsigned operands. Produces a 16-bit result = {remainder[7:0],
// quotient[7:0]}. Sequential: one quotient bit per cycle over 8 cycles.
//
// On a valid request (opn_valid & ~res_valid) the inputs are latched and the
// magnitudes computed (|x| when sign=1 and the operand is negative). The
// restoring algorithm keeps a 16-bit shift register SR = {rem(8b), quo(8b)}
// pre-loaded with the |dividend| in the low byte. Each of 8 iterations:
//   1. shift SR left by one (rem gets dividend's next MSB),
//   2. if the running remainder >= |divisor|, subtract it and set the new
//      quotient LSB to 1, else leave 0 (restoring).
// After 8 cycles the magnitude quotient/remainder are sign-corrected:
// quotient sign = dividend_sign ^ divisor_sign; remainder takes dividend_sign
// (truncated division). res_valid asserts when done and holds until the result
// is consumed — the description manages res_valid by "whether the result has
// been consumed", i.e. a valid/ready handshake on res_ready.
module radix2_div (
    input  wire        clk,
    input  wire        rst,
    input  wire        sign,
    input  wire [7:0]  dividend,
    input  wire [7:0]  divisor,
    input  wire        opn_valid,
    input  wire        res_ready,
    output reg         res_valid,
    output reg  [15:0] result
);
    // State
    reg [15:0] SR;            // {remainder[15:8], quotient/dividend[7:0]}
    reg [7:0]  abs_divisor;
    reg [3:0]  cnt;           // 0..8 iterations
    reg        start_cnt;
    reg        dividend_sign; // sign of original dividend (sign-mode only)
    reg        divisor_sign;

    // Magnitudes of the freshly-presented operands.
    wire       d_neg = sign & dividend[7];
    wire       v_neg = sign & divisor[7];
    wire [7:0] abs_dividend_w = d_neg ? (~dividend + 8'd1) : dividend;
    wire [7:0] abs_divisor_w  = v_neg ? (~divisor  + 8'd1) : divisor;

    // One restoring step on the current SR: shift left, compare top byte.
    wire [15:0] sr_shifted = SR << 1;
    wire [7:0]  rem_trial  = sr_shifted[15:8];
    wire        ge         = (rem_trial >= abs_divisor);
    wire [7:0]  rem_next   = ge ? (rem_trial - abs_divisor) : rem_trial;
    // quotient LSB is the freshly shifted-in 0; set it to 1 on a successful sub.
    wire [15:0] sr_next    = {rem_next, sr_shifted[7:1], ge};

    // Sign-corrected outputs (combinational from the finished magnitudes).
    wire [7:0] q_abs = SR[7:0];
    wire [7:0] r_abs = SR[15:8];
    wire [7:0] q_fin = (dividend_sign ^ divisor_sign) ? (~q_abs + 8'd1) : q_abs;
    wire [7:0] r_fin = (dividend_sign)                ? (~r_abs + 8'd1) : r_abs;

    always @(posedge clk) begin
        if (rst) begin
            res_valid <= 1'b0;
            result    <= 16'd0;
            SR        <= 16'd0;
            cnt       <= 4'd0;
            start_cnt <= 1'b0;
        end else if (opn_valid && !res_valid && !start_cnt) begin
            // Latch & initialize: |dividend| in low byte, remainder cleared.
            SR            <= {8'd0, abs_dividend_w};
            abs_divisor   <= abs_divisor_w;
            dividend_sign <= d_neg;
            divisor_sign  <= v_neg;
            cnt           <= 4'd0;
            start_cnt     <= 1'b1;
        end else if (start_cnt) begin
            if (cnt == 4'd8) begin
                // Done: sign-correct and present.
                start_cnt <= 1'b0;
                res_valid <= 1'b1;
                result    <= {r_fin, q_fin};
            end else begin
                SR  <= sr_next;
                cnt <= cnt + 4'd1;
            end
        end else if (res_valid && res_ready) begin
            // Result consumed — drop res_valid so a new op can start.
            res_valid <= 1'b0;
        end
    end
endmodule
