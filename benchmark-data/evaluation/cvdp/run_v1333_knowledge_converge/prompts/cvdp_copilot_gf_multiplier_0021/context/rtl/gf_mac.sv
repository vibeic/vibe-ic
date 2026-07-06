module gf_mac #(
    parameter WIDTH = 32  // Input width, should be a multiple of 8
)(
    input [WIDTH-1:0] a,  // Multiplicand
    input [WIDTH-1:0] b,  // Multiplier
    output reg [7:0] result // 8-bit XORed result of all GF multiplications
);

    integer i;
    reg [7:0] temp_result;
    wire [7:0] partial_results [(WIDTH/8)-1:0];

    // Generate GF multipliers for each 8-bit segment
    genvar j;
    generate
        for (j = 0; j < WIDTH/8; j = j + 1) begin : segment_mult
            gf_multiplier segment_mult (
                .A(a[(j+1)*8-1:j*8]),
                .B(b[(j+1)*8-1:j*8]),
                .result(partial_results[j])
            );
        end
    endgenerate

    // XOR all segment results
    always @(*) begin
        temp_result = 8'b0;
        for (i = 0; i < WIDTH/8; i = i + 1) begin
            temp_result = temp_result ^ partial_results[i];
        end
        result = temp_result;
    end
endmodule

module gf_multiplier (
    input [7:0] A,
    input [7:0] B,
    output reg [7:0] result
);
    reg [7:0] temp_result;
    reg [8:0] multiplicand;
    reg [8:0] irreducible_poly = 9'b100011011; // x^8 + x^4 + x^3 + x + 1

    integer i;

    always @(*) begin
        temp_result = 8'b00000000;
        multiplicand = {1'b0, A};
        for (i = 0; i < 8; i = i + 1) begin
            if (B[i]) begin
                temp_result = temp_result ^ multiplicand[7:0];
            end
            multiplicand = multiplicand << 1;
            if (multiplicand[8]) begin
                multiplicand = multiplicand ^ irreducible_poly;
            end
        end
        result = temp_result;
    end
endmodule