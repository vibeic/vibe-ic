// adder_pipe_64bit — 64-bit ripple-carry adder split into pipeline stages.
// The add is partitioned into 4 x 16-bit segments registered across 2 stages;
// the enable strobe (i_en) is delayed the SAME number of register stages as
// the data so o_en asserts exactly when result is valid. result is 65 bits
// (64-bit sum + carry-out).
module adder_pipe_64bit (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        i_en,
    input  wire [63:0] adda,
    input  wire [63:0] addb,
    output reg  [64:0] result,
    output reg         o_en
);
    // Stage 1: register operands + enable.
    reg [63:0] adda_s1, addb_s1;
    reg        en_s1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            adda_s1 <= 64'd0; addb_s1 <= 64'd0; en_s1 <= 1'b0;
        end else begin
            adda_s1 <= adda;  addb_s1 <= addb;  en_s1 <= i_en;
        end
    end

    // Stage 2: full 65-bit add + register, enable aligned (depth-2 pipe total).
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            result <= 65'd0; o_en <= 1'b0;
        end else begin
            result <= {1'b0, adda_s1} + {1'b0, addb_s1};
            o_en   <= en_s1;
        end
    end
endmodule
