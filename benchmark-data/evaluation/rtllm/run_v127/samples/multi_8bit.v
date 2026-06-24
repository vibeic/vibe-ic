// multi_8bit: 8-bit unsigned multiplier via shift-and-add.
// Combinational: for each set bit of the multiplier B, add the multiplicand A
// shifted left to the corresponding position. product = A * B (16 bits).
module multi_8bit (
    input  [7:0]  A,
    input  [7:0]  B,
    output [15:0] product
);

    wire [15:0] pp [7:0];

    // Partial products: pp[i] = B[i] ? (A << i) : 0
    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin : gen_pp
            assign pp[i] = B[i] ? ({8'b0, A} << i) : 16'b0;
        end
    endgenerate

    assign product = pp[0] + pp[1] + pp[2] + pp[3]
                   + pp[4] + pp[5] + pp[6] + pp[7];

endmodule
