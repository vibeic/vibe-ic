module gf_mac #(
    parameter integer WIDTH = 32   // Input width, must be a multiple of 8
) (
    input  [WIDTH-1:0] a,          // Multiplicand, segmented into 8-bit blocks
    input  [WIDTH-1:0] b,          // Multiplier, segmented into 8-bit blocks
    output [7:0]       result      // Final 8-bit GF MAC result
);

    localparam integer NUM_SEG = WIDTH / 8;

    // Per-segment GF multiplication products
    wire [7:0] seg_result [0:NUM_SEG-1];

    genvar g;
    generate
        for (g = 0; g < NUM_SEG; g = g + 1) begin : gen_gf_mult
            gf_multiplier u_gf_multiplier (
                .A     (a[g*8 +: 8]),
                .B     (b[g*8 +: 8]),
                .result(seg_result[g])
            );
        end
    endgenerate

    // XOR-accumulate all segment products (GF addition = XOR)
    reg [7:0] temp_result;
    integer j;
    always @(*) begin
        temp_result = 8'b0;
        for (j = 0; j < NUM_SEG; j = j + 1) begin
            temp_result = temp_result ^ seg_result[j];
        end
    end

    assign result = temp_result;

endmodule


module gf_multiplier (
    input [7:0] A,     // 8-bit Multiplicand
    input [7:0] B,     // 8-bit Multiplier
    output reg [7:0] result // 8-bit Result
);
    reg [7:0] temp_result;
    reg [8:0] multiplicand;
    reg [8:0] irreducible_poly = 9'b100011011; // Irreducible polynomial x^8 + x^4 + x^3 + x + 1

    integer i;

    always @(*) begin
        temp_result = 8'b00000000; // Initialize result to zero
        multiplicand = {1'b0, A};  // Initialize multiplicand with an extra bit for overflow

        // Perform multiplication using shift-and-add algorithm
        for (i = 0; i < 8; i = i + 1) begin
            if (B[i]) begin
                temp_result = temp_result ^ multiplicand[7:0]; // XOR multiplicand with result
            end
            multiplicand = multiplicand << 1; // Shift multiplicand left by 1
            if (multiplicand[8]) begin
                multiplicand = multiplicand ^ irreducible_poly; // Polynomial reduction if overflow occurs
            end
        end

        result = temp_result; // Output the final result
    end
endmodule
