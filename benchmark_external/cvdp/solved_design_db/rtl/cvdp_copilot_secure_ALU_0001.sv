module alu_seq (
    input        i_clk,          // Clock signal
    input        i_rst_b,        // Active-low asynchronous reset
    input  [3:0] i_operand_a,    // 4-bit input operand A
    input  [3:0] i_operand_b,    // 4-bit input operand B
    input  [2:0] i_opcode,       // 3-bit operation code
    input  [7:0] i_key_in,       // 8-bit security key input
    output reg [7:0] o_result    // 8-bit operation result
);

    // Configurable internal 8-bit security key (default 0xAA)
    parameter [7:0] p_key = 8'hAA;

    always @(posedge i_clk or negedge i_rst_b) begin
        if (!i_rst_b) begin
            o_result <= 8'b0;
        end else begin
            if (i_key_in == p_key) begin
                case (i_opcode)
                    3'b000: o_result <= i_operand_a + i_operand_b;   // Addition
                    3'b001: o_result <= i_operand_a - i_operand_b;   // Subtraction
                    3'b010: o_result <= i_operand_a * i_operand_b;   // Multiplication
                    3'b011: o_result <= i_operand_a & i_operand_b;   // AND
                    3'b100: o_result <= i_operand_a | i_operand_b;   // OR
                    // NOT/XNOR operate on the 4-bit operands. The complement
                    // is taken at 4-bit width (self-determined inside the
                    // concatenation) and zero-extended, otherwise the 8-bit
                    // assignment context would sign/zero-extend the operand
                    // first and invert the upper nibble too.
                    3'b101: o_result <= {4'b0, ~i_operand_a};                 // NOT
                    3'b110: o_result <= i_operand_a ^ i_operand_b;            // XOR
                    3'b111: o_result <= {4'b0, ~(i_operand_a ^ i_operand_b)}; // XNOR
                    default: o_result <= 8'b0;
                endcase
            end else begin
                // Key mismatch: no operation, output held at zero
                o_result <= 8'b0;
            end
        end
    end

endmodule
