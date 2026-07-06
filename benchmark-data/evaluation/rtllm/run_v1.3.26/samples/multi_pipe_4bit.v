module multi_pipe_4bit #(
    parameter size = 4
) (
    input                    clk,
    input                    rst_n,
    input      [size-1:0]    mul_a,
    input      [size-1:0]    mul_b,
    output reg [2*size-1:0]  mul_out
);

    wire [2*size-1:0] mul_a_ext = {{size{1'b0}}, mul_a};
    wire [2*size-1:0] mul_b_ext = {{size{1'b0}}, mul_b};

    wire [2*size-1:0] partial [0:size-1];

    genvar i;
    generate
        for (i = 0; i < size; i = i + 1) begin : gen_pp
            assign partial[i] = mul_b_ext[i] ? (mul_a_ext << i) : {2*size{1'b0}};
        end
    endgenerate

    reg [2*size-1:0] stage1_sum [0:1];

    integer k;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (k = 0; k < 2; k = k + 1)
                stage1_sum[k] <= {2*size{1'b0}};
        end else begin
            stage1_sum[0] <= partial[0] + partial[1];
            stage1_sum[1] <= partial[2] + partial[3];
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            mul_out <= {2*size{1'b0}};
        else
            mul_out <= stage1_sum[0] + stage1_sum[1];
    end

endmodule
