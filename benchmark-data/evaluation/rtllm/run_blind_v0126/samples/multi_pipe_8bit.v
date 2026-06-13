module multi_pipe_8bit (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        mul_en_in,
    input  wire [7:0]  mul_a,
    input  wire [7:0]  mul_b,
    output wire        mul_en_out,
    output wire [15:0] mul_out
);

    // Enable pipeline register: shift the enable through the pipeline depth.
    // Pipeline depth here is 2 stages (partial sum stage + final sum stage).
    reg [2:0] mul_en_out_reg;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            mul_en_out_reg <= 3'd0;
        else
            mul_en_out_reg <= {mul_en_out_reg[1:0], mul_en_in};
    end
    assign mul_en_out = mul_en_out_reg[2];

    // Input registers, updated only when enable active
    reg [7:0] mul_a_reg;
    reg [7:0] mul_b_reg;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mul_a_reg <= 8'd0;
            mul_b_reg <= 8'd0;
        end
        else if (mul_en_in) begin
            mul_a_reg <= mul_a;
            mul_b_reg <= mul_b;
        end
    end

    // Partial products: temp[i] = mul_b_reg[i] ? (mul_a_reg << i) : 0
    wire [15:0] temp [0:7];
    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin : gen_pp
            assign temp[i] = mul_b_reg[i] ? ({8'd0, mul_a_reg} << i) : 16'd0;
        end
    endgenerate

    // Partial sum stage: pairwise add into 4 sum registers
    reg [15:0] sum0, sum1, sum2, sum3;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sum0 <= 16'd0;
            sum1 <= 16'd0;
            sum2 <= 16'd0;
            sum3 <= 16'd0;
        end
        else begin
            sum0 <= temp[0] + temp[1];
            sum1 <= temp[2] + temp[3];
            sum2 <= temp[4] + temp[5];
            sum3 <= temp[6] + temp[7];
        end
    end

    // Final product stage
    reg [15:0] mul_out_reg;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            mul_out_reg <= 16'd0;
        else
            mul_out_reg <= sum0 + sum1 + sum2 + sum3;
    end

    // Output assignment gated by enable
    assign mul_out = mul_en_out ? mul_out_reg : 16'd0;

endmodule
