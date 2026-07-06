// DB-informed re-author: reviewed IC-Expert-DB craft for this design class;
// verified by hand-trace that the existing implementation already satisfies the
// relevant DB lesson (or the lesson does not apply here) -- kept functionally unchanged.
module radix2_div (
    input        clk,
    input        rst,
    input        sign,
    input  [7:0] dividend,
    input  [7:0] divisor,
    input        opn_valid,
    output reg       res_valid,
    output reg [15:0] result
);

    reg        busy;
    reg [3:0]  cnt;
    reg        dvd_sign;
    reg        quot_sign;
    reg [7:0]  abs_dvs;
    reg [8:0]  rem_r;
    reg [7:0]  quo_r;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            busy      <= 1'b0;
            cnt       <= 4'd0;
            res_valid <= 1'b0;
            dvd_sign  <= 1'b0;
            quot_sign <= 1'b0;
            abs_dvs   <= 8'd0;
            rem_r     <= 9'd0;
            quo_r     <= 8'd0;
        end else begin
            if (opn_valid && !busy && !res_valid) begin
                dvd_sign  <= sign & dividend[7];
                quot_sign <= sign & (dividend[7] ^ divisor[7]);
                abs_dvs   <= (sign & divisor[7])  ? (~divisor  + 8'd1) : divisor;
                quo_r     <= (sign & dividend[7]) ? (~dividend + 8'd1) : dividend;
                rem_r     <= 9'd0;
                cnt       <= 4'd0;
                busy      <= 1'b1;
                res_valid <= 1'b0;
            end else if (busy) begin
                if ({rem_r[7:0], quo_r[7]} >= {1'b0, abs_dvs}) begin
                    rem_r <= {rem_r[7:0], quo_r[7]} - {1'b0, abs_dvs};
                    quo_r <= {quo_r[6:0], 1'b1};
                end else begin
                    rem_r <= {rem_r[7:0], quo_r[7]};
                    quo_r <= {quo_r[6:0], 1'b0};
                end

                if (cnt == 4'd7) begin
                    busy      <= 1'b0;
                    res_valid <= 1'b1;
                end
                cnt <= cnt + 4'd1;
            end else if (res_valid) begin
                res_valid <= 1'b0;
            end
        end
    end

    always @(*) begin
        if (res_valid) begin
            result = { (dvd_sign  ? (~rem_r[7:0] + 8'd1) : rem_r[7:0]),
                       (quot_sign ? (~quo_r      + 8'd1) : quo_r) };
        end else begin
            result = 16'd0;
        end
    end

endmodule
