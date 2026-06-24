// multi_pipe_4bit: parameterized unsigned pipelined multiplier.
// Two register levels: stage-1 stores the per-bit partial products, stage-2
// produces the final sum. Parameter `size` (default 4) is declared so a harness
// can override it via #(.size(N)).
module multi_pipe_4bit #(
    parameter size = 4
)(
    input                       clk,
    input                       rst_n,
    input      [size-1:0]       mul_a,
    input      [size-1:0]       mul_b,
    output reg [2*size-1:0]     mul_out
);

    // Zero-extend operands to 2*size so the left-shifted partial products fit.
    wire [2*size-1:0] mul_a_ext = {{size{1'b0}}, mul_a};
    wire [2*size-1:0] mul_b_ext = {{size{1'b0}}, mul_b};

    // Partial products: pp[i] = mul_b[i] ? (mul_a_ext << i) : 0
    wire [2*size-1:0] pp [size-1:0];
    genvar i;
    generate
        for (i = 0; i < size; i = i + 1) begin : gen_pp
            assign pp[i] = mul_b_ext[i] ? (mul_a_ext << i) : {(2*size){1'b0}};
        end
    endgenerate

    // Level-1 registers: latch the partial products.
    reg [2*size-1:0] stage1 [size-1:0];
    integer k;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (k = 0; k < size; k = k + 1)
                stage1[k] <= {(2*size){1'b0}};
        end
        else begin
            for (k = 0; k < size; k = k + 1)
                stage1[k] <= pp[k];
        end
    end

    // Level-2 register: sum the latched partial products.
    integer m;
    reg [2*size-1:0] acc;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mul_out <= {(2*size){1'b0}};
        end
        else begin
            acc = {(2*size){1'b0}};
            for (m = 0; m < size; m = m + 1)
                acc = acc + stage1[m];
            mul_out <= acc;
        end
    end

endmodule
