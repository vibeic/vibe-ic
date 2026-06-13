module TopModule (
  input clk,
  input in,
  output logic out
);
    // D flip-flop with no reset; D = in XOR out
    initial out = 1'b0;            // power-on value (no reset port exists)
    always @(posedge clk)
        out <= in ^ out;
endmodule
