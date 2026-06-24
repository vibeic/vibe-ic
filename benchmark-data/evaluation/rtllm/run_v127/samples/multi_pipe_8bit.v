// multi_pipe_8bit: unsigned 8-bit pipelined multiplier.
// Pipeline: input-register stage -> partial-sum stage -> final-accumulate stage.
// The enable strobe mul_en_in is delayed through a shift register the SAME depth
// as the datapath; mul_en_out is the MSB (aligned with the final product cycle).
module multi_pipe_8bit (
    input             clk,
    input             rst_n,
    input             mul_en_in,
    input      [7:0]  mul_a,
    input      [7:0]  mul_b,
    output            mul_en_out,
    output     [15:0] mul_out
);

    // Enable pipeline: 3 stages deep to match input-reg / sum-reg / final-reg.
    reg [2:0] mul_en_out_reg;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            mul_en_out_reg <= 3'b0;
        else
            mul_en_out_reg <= {mul_en_out_reg[1:0], mul_en_in};
    end
    assign mul_en_out = mul_en_out_reg[2];

    // Input registers, updated only when enabled.
    reg [7:0] mul_a_reg, mul_b_reg;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mul_a_reg <= 8'b0;
            mul_b_reg <= 8'b0;
        end
        else if (mul_en_in) begin
            mul_a_reg <= mul_a;
            mul_b_reg <= mul_b;
        end
    end

    // Partial products (combinational): temp[i] = mul_b_reg[i] ? (mul_a_reg << i) : 0
    wire [15:0] temp [7:0];
    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin : gen_temp
            assign temp[i] = mul_b_reg[i] ? ({8'b0, mul_a_reg} << i) : 16'b0;
        end
    endgenerate

    // Partial-sum stage: group the eight partial products into four sums.
    reg [15:0] sum0, sum1, sum2, sum3;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sum0 <= 16'b0; sum1 <= 16'b0; sum2 <= 16'b0; sum3 <= 16'b0;
        end
        else begin
            sum0 <= temp[0] + temp[1];
            sum1 <= temp[2] + temp[3];
            sum2 <= temp[4] + temp[5];
            sum3 <= temp[6] + temp[7];
        end
    end

    // Final-accumulate stage.
    reg [15:0] mul_out_reg;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            mul_out_reg <= 16'b0;
        else
            mul_out_reg <= sum0 + sum1 + sum2 + sum3;
    end

    assign mul_out = mul_en_out ? mul_out_reg : 16'b0;

endmodule
