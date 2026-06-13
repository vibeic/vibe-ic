module multi_pipe_4bit #(
    parameter size = 4
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire [size-1:0]   mul_a,
    input  wire [size-1:0]   mul_b,
    output wire [2*size-1:0] mul_out
);

    // Zero-extend operands to 2*size bits
    wire [2*size-1:0] mul_a_ext = {{size{1'b0}}, mul_a};
    wire [2*size-1:0] mul_b_ext = {{size{1'b0}}, mul_b};

    // Partial products
    wire [2*size-1:0] partial [0:size-1];
    genvar i;
    generate
        for (i = 0; i < size; i = i + 1) begin : gen_partial
            assign partial[i] = mul_b_ext[i] ? (mul_a_ext << i) : {(2*size){1'b0}};
        end
    endgenerate

    // Registered intermediate sums (one register per partial product)
    reg [2*size-1:0] sum [0:size-1];
    integer j;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (j = 0; j < size; j = j + 1)
                sum[j] <= {(2*size){1'b0}};
        end
        else begin
            for (j = 0; j < size; j = j + 1)
                sum[j] <= partial[j];
        end
    end

    // Combinational reduction of registered partial products
    integer k;
    reg [2*size-1:0] acc;
    always @(*) begin
        acc = {(2*size){1'b0}};
        for (k = 0; k < size; k = k + 1)
            acc = acc + sum[k];
    end

    // Final product register
    reg [2*size-1:0] mul_out_r;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            mul_out_r <= {(2*size){1'b0}};
        else
            mul_out_r <= acc;
    end

    assign mul_out = mul_out_r;

endmodule
