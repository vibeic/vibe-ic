// LFSR — 4-bit linear feedback shift register.
// Feedback = ~(out[3] ^ out[2]); shift left, feedback enters the LSB.
// Active-high reset clears the register to 0. Ports declared output-first
// to match the common positional-instantiation convention for this class.
module LFSR (
    output reg  [3:0] out,
    input  wire       clk,
    input  wire       rst
);
    wire feedback = ~(out[3] ^ out[2]);
    always @(posedge clk) begin
        if (rst)
            out <= 4'b0000;
        else
            out <= {out[2:0], feedback};   // shift left, feedback into LSB
    end
endmodule
