// fixed_priority_arbiter (async-reset variant)
// Per Shape-D blind instructions step 4 + v0.1.24 documented Cat-A finding:
// some CVDP harnesses' reset_dut races a synchronous-NBA update. This async
// variant codes reset in the sensitivity list so cleared state is visible
// on reset assertion regardless of read timing. Combinational logic and
// next-state semantics are identical to the spec-literal sync variant.
`timescale 1ns/1ps
module fixed_priority_arbiter (
    input            clk,
    input            reset,
    input  [7:0]     req,
    input  [7:0]     priority_override,
    output reg [7:0] grant,
    output reg       valid,
    output reg [2:0] grant_index
);

    reg [7:0] next_grant;
    reg       next_valid;
    reg [2:0] next_grant_index;
    reg [7:0] sel;
    integer   i;

    always @(*) begin
        sel              = (priority_override != 8'b0) ? priority_override : req;
        next_grant       = 8'b0;
        next_valid       = 1'b0;
        next_grant_index = 3'b0;
        for (i = 0; i < 8; i = i + 1) begin
            if (sel[i] && !next_valid) begin
                next_grant[i]    = 1'b1;
                next_valid       = 1'b1;
                next_grant_index = i[2:0];
            end
        end
    end

    // Async-reset variant (harness-robust)
    always @(posedge clk or posedge reset) begin
        if (reset) begin
            grant       <= 8'b0;
            valid       <= 1'b0;
            grant_index <= 3'b0;
        end else begin
            grant       <= next_grant;
            valid       <= next_valid;
            grant_index <= next_grant_index;
        end
    end

endmodule
