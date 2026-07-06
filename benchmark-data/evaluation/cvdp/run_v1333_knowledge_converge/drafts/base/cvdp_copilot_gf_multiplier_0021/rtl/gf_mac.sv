module gf_mac #(
    parameter WIDTH = 32  // Input width, should be a multiple of 8
)(
    input  [WIDTH-1:0] a,          // Multiplicand
    input  [WIDTH-1:0] b,          // Multiplier
    output reg [7:0]   result,     // 8-bit XORed result of all GF multiplications
    output             error_flag, // 1 when WIDTH is not a multiple of 8
    output             valid_result// 1 when WIDTH is a multiple of 8 (result valid)
);

    // WIDTH validity is a compile-time property of the parameter.
    localparam WIDTH_VALID = (WIDTH % 8 == 0) ? 1'b1 : 1'b0;

    assign error_flag   = ~WIDTH_VALID;
    assign valid_result =  WIDTH_VALID;

    // Number of 8-bit segments (only meaningful when WIDTH_VALID).
    localparam NSEG = (WIDTH_VALID) ? (WIDTH / 8) : 0;

    integer i;
    reg [7:0] temp_result;
    wire [7:0] partial_results [0:(NSEG > 0 ? NSEG-1 : 0)];

    // Generate GF multipliers for each 8-bit segment (only when WIDTH is valid)
    genvar j;
    generate
        if (WIDTH_VALID) begin : gen_valid
            for (j = 0; j < NSEG; j = j + 1) begin : segment_mult
                gf_multiplier segment_mult (
                    .A(a[(j+1)*8-1 -: 8]),
                    .B(b[(j+1)*8-1 -: 8]),
                    .result(partial_results[j])
                );
            end
        end
    endgenerate

    // XOR all segment results; force 0 when WIDTH is invalid
    always @(*) begin
        if (!WIDTH_VALID) begin
            result = 8'b0;
        end else begin
            temp_result = 8'b0;
            for (i = 0; i < NSEG; i = i + 1) begin
                temp_result = temp_result ^ partial_results[i];
            end
            result = temp_result;
        end
    end
endmodule

module gf_multiplier (
    input  [7:0] A,
    input  [7:0] B,
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
