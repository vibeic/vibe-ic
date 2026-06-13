module TopModule (
  input sel,
  input [7:0] a,
  input [7:0] b,
  output reg [7:0] out
);

  // Bug in original: 1-bit scalar select ANDed with 8-bit vectors.
  // Fix: select the full 8-bit operand with a proper mux.
  always @(*) begin
    out = sel ? b : a;
  end

endmodule
