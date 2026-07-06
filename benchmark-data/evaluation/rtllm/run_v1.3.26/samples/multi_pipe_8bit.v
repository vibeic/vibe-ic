module multi_pipe_8bit (
    input             clk,
    input             rst_n,
    input             mul_en_in,
    input      [7:0]  mul_a,
    input      [7:0]  mul_b,
    output            mul_en_out,
    output     [15:0] mul_out
);

    reg [2:0] mul_en_out_reg;
    reg [7:0] mul_a_reg;
    reg [7:0] mul_b_reg;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            mul_en_out_reg <= 3'b0;
        else
            mul_en_out_reg <= {mul_en_out_reg[1:0], mul_en_in};
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mul_a_reg <= 8'd0;
            mul_b_reg <= 8'd0;
        end else if (mul_en_in) begin
            mul_a_reg <= mul_a;
            mul_b_reg <= mul_b;
        end
    end

    wire [15:0] temp [0:7];
    genvar gi;
    generate
        for (gi = 0; gi < 8; gi = gi + 1) begin : gen_pp
            assign temp[gi] = mul_b_reg[gi] ? ({8'd0, mul_a_reg} << gi) : 16'd0;
        end
    endgenerate

    reg [15:0] sum [0:3];
    integer k;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (k = 0; k < 4; k = k + 1)
                sum[k] <= 16'd0;
        end else begin
            sum[0] <= temp[0] + temp[1];
            sum[1] <= temp[2] + temp[3];
            sum[2] <= temp[4] + temp[5];
            sum[3] <= temp[6] + temp[7];
        end
    end

    reg [15:0] mul_out_reg;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            mul_out_reg <= 16'd0;
        else
            mul_out_reg <= sum[0] + sum[1] + sum[2] + sum[3];
    end

    assign mul_en_out = mul_en_out_reg[2];
    assign mul_out = mul_en_out ? mul_out_reg : 16'd0;

endmodule
