module TopModule (
  input a,
  input b,
  input c,
  input d,
  output q
);

  // Stated operation: XOR the inputs, then invert the result (even-parity / XNOR).
  assign q = ~(a ^ b ^ c ^ d);

endmodule
