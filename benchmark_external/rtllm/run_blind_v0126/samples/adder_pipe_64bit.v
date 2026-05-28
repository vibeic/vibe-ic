module adder_pipe_64bit (
    input              clk,
    input              rst_n,
    input              i_en,
    input      [63:0]  adda,
    input      [63:0]  addb,
    output reg [64:0]  result,
    output reg         o_en
);

    // Two-stage pipeline: split the 64-bit add into low/high 32-bit halves.

    // Stage 1 registers
    reg         en_s1;
    reg [32:0]  sum_low_s1;     // 32-bit sum + carry-out of low half
    reg [31:0]  adda_high_s1;
    reg [31:0]  addb_high_s1;

    // Stage 1: add low half, latch high-half operands
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            en_s1        <= 1'b0;
            sum_low_s1   <= 33'd0;
            adda_high_s1 <= 32'd0;
            addb_high_s1 <= 32'd0;
        end else begin
            en_s1        <= i_en;
            sum_low_s1   <= {1'b0, adda[31:0]} + {1'b0, addb[31:0]};
            adda_high_s1 <= adda[63:32];
            addb_high_s1 <= addb[63:32];
        end
    end

    // Stage 2: add high half with carry from stage 1, form 65-bit result
    wire [32:0] sum_high = {1'b0, adda_high_s1} + {1'b0, addb_high_s1} + sum_low_s1[32];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            o_en   <= 1'b0;
            result <= 65'd0;
        end else begin
            o_en   <= en_s1;
            result <= {sum_high, sum_low_s1[31:0]};
        end
    end

endmodule
