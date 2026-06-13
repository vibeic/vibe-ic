// fixed_priority_arbiter — spec-literal per work/docs/specification.md.
// Re-authored blind on v0.1.57; spec admits one canonical reading so the
// shape matches v0.1.56 (§ 4 Cat E doctrine: leave spec-faithful).
// Spec line 54: "Active-high synchronous reset (clears all outputs)".
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
    reg [7:0] sel, next_grant;
    reg       next_valid;
    reg [2:0] next_grant_index;
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

    always @(posedge clk) begin
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
