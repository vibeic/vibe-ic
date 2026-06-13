// fixed_priority_arbiter — spec-literal synchronous reset variant
// Authored blind per docs/specification.md + phase1/generated_docs/L*.json
// (CVDP N=1, Shape D, plugin v0.1.53)
//
// Spec semantics:
//   - lowest index in req has highest priority
//   - if priority_override != 0: grant the lowest-index set bit of priority_override
//     (the spec's "highest-priority bit" = lowest index, same priority scheme)
//   - else: grant the lowest-index set bit of req
//   - valid = 1 iff a grant was issued
//   - grant_index = binary index of the granted bit
//   - reset (active-high SYNCHRONOUS per Port Description line): clears all outputs
//   - single-cycle arbitration latency
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
    reg [7:0] sel;             // the input to scan (override or req)
    integer   i;

    always @(*) begin
        // Choose source: override takes precedence when non-zero
        sel              = (priority_override != 8'b0) ? priority_override : req;
        next_grant       = 8'b0;
        next_valid       = 1'b0;
        next_grant_index = 3'b0;
        // Scan low-to-high; first set bit wins
        for (i = 0; i < 8; i = i + 1) begin
            if (sel[i] && !next_valid) begin
                next_grant[i]    = 1'b1;
                next_valid       = 1'b1;
                next_grant_index = i[2:0];
            end
        end
    end

    // Spec: "Active-high synchronous reset (clears all outputs)"
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
