module TopModule (
  input a,
  input b,
  input c,
  input d,
  output reg out
);

  // K-map is a checkerboard pattern: out = a ^ b ^ c ^ d
  always @(*) begin
    out = a ^ b ^ c ^ d;
  end

endmodule
