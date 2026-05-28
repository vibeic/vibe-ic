module radix2_div (
    input             clk,
    input             rst,
    input             sign,
    input      [7:0]  dividend,
    input      [7:0]  divisor,
    input             opn_valid,
    output reg        res_valid,
    output reg [15:0] result      // {remainder[7:0], quotient[7:0]}
);

    // Saved inputs
    reg [7:0] dividend_r;
    reg [7:0] divisor_r;
    reg       sign_r;

    // Sign tracking
    reg dividend_neg;   // sign of dividend
    reg divisor_neg;    // sign of divisor

    // Shift register: holds {running_remainder[8:0], quotient_so_far[7:0]} = 17 bits
    reg [16:0] SR;
    reg [8:0]  NEG_DIVISOR;   // negated absolute value of divisor (9-bit)
    reg [4:0]  cnt;
    reg        start_cnt;

    // Absolute values of saved inputs
    wire [7:0] abs_dividend = (sign_r & dividend_r[7]) ? (~dividend_r + 8'd1) : dividend_r;
    wire [7:0] abs_divisor  = (sign_r & divisor_r[7])  ? (~divisor_r  + 8'd1) : divisor_r;

    // Subtraction step: current partial remainder (top 9 bits of SR) + NEG_DIVISOR
    wire [8:0] sub_result = SR[16:8] + NEG_DIVISOR;

    // Use the carry-out of the 9-bit add to decide quotient bit.
    wire [9:0] sub_ext = {1'b0, SR[16:8]} + {1'b0, NEG_DIVISOR};
    wire       cout    = sub_ext[9];           // 1 => remainder >= divisor (subtract kept)
    wire [8:0] new_rem = cout ? sub_result : SR[16:8];

    // Final magnitude results
    wire [7:0] q_mag = SR[7:0];
    wire [7:0] r_mag = SR[15:8];

    // Apply signs to results (signed mode)
    wire quotient_neg  = sign_r & (dividend_neg ^ divisor_neg);
    wire remainder_neg = sign_r & dividend_neg;     // remainder takes dividend's sign
    wire [7:0] q_signed = quotient_neg  ? (~q_mag + 8'd1) : q_mag;
    wire [7:0] r_signed = remainder_neg ? (~r_mag + 8'd1) : r_mag;

    always @(posedge clk) begin
        if (rst) begin
            res_valid   <= 1'b0;
            SR          <= 17'd0;
            NEG_DIVISOR <= 9'd0;
            cnt         <= 5'd0;
            start_cnt   <= 1'b0;
            result      <= 16'd0;
            dividend_r  <= 8'd0;
            divisor_r   <= 8'd0;
            sign_r      <= 1'b0;
            dividend_neg<= 1'b0;
            divisor_neg <= 1'b0;
        end else begin
            if (opn_valid && !res_valid && !start_cnt) begin
                // Operation start: save inputs, init SR and NEG_DIVISOR
                dividend_r   <= dividend;
                divisor_r    <= divisor;
                sign_r       <= sign;
                dividend_neg <= sign & dividend[7];
                divisor_neg  <= sign & divisor[7];
                // SR initialized with abs(dividend) shifted left by 1
                SR          <= {8'd0, ((sign & dividend[7]) ? (~dividend + 8'd1) : dividend), 1'b0};
                NEG_DIVISOR <= (~{1'b0, ((sign & divisor[7]) ? (~divisor + 8'd1) : divisor)} + 9'd1);
                cnt         <= 5'd1;
                start_cnt   <= 1'b1;
                res_valid   <= 1'b0;
            end else if (start_cnt) begin
                if (cnt[3]) begin
                    // cnt reached 8 -> division complete
                    cnt       <= 5'd0;
                    start_cnt <= 1'b0;
                    res_valid <= 1'b1;
                    result    <= {r_signed, q_signed};
                end else begin
                    cnt <= cnt + 5'd1;
                    // shift left, insert carry-out (quotient bit) at LSB
                    SR  <= {new_rem[7:0], SR[7:0], cout};
                end
            end else if (res_valid && !opn_valid) begin
                // result consumed when opn_valid drops
                res_valid <= 1'b0;
            end
        end
    end

endmodule
