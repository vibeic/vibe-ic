module gf_multiplier (
    input [3:0] A,     // Multiplicand
    input [3:0] B,     // Multiplier
    output reg [3:0] result // Result
);
    reg [3:0] temp_result;
    reg [4:0] multiplicand;
    reg [4:0] irreducible_poly = 5'b10011; // Irreducible polynomial x^4 + x + 1

    integer i;

    always @(*) begin
        temp_result = 4'b0000; // Initialize result to zero
        multiplicand = {1'b0, A}; // Initialize multiplicand, adding an extra bit to handle overflow

        // Perform multiplication using shift-and-add algorithm
        for (i = 0; i < 4; i = i + 1) begin
            if (B[i]) begin
                temp_result = temp_result ^ multiplicand[3:0]; // XOR the multiplicand with result
            end
            multiplicand = multiplicand << 1; // Shift the multiplicand left by 1
            if (multiplicand[4]) begin
                multiplicand = multiplicand ^ irreducible_poly; // Polynomial reduction if overflow occurs
            end
        end

        result = temp_result; // Output the final result
    end
endmodule