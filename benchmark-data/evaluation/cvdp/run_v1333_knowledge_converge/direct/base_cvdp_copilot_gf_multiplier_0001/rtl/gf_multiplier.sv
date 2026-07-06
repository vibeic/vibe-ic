// GF(2^4) multiplier using irreducible polynomial x^4 + x + 1 (5'b10011).
// Combinational shift-and-XOR algorithm per specification.
module gf_multiplier (
    input  wire [3:0] A,
    input  wire [3:0] B,
    output wire [3:0] result
);

    integer i;
    reg [3:0] result_r;
    reg [3:0] multiplicand;
    reg [4:0] shifted;

    always @(*) begin
        result_r     = 4'b0000;
        multiplicand = A;
        for (i = 0; i < 4; i = i + 1) begin
            // Conditionally accumulate the multiplicand into the result.
            if (B[i])
                result_r = result_r ^ multiplicand;
            else
                result_r = result_r ^ 4'b0000;

            // Shift multiplicand left by one bit (track carry-out in bit 4).
            shifted = {1'b0, multiplicand} << 1;

            // Polynomial reduction on overflow (MSB of shifted value set).
            if (shifted[4])
                shifted = shifted ^ 5'b10011;

            multiplicand = shifted[3:0];
        end
    end

    assign result = result_r;

endmodule
