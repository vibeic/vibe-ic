module TopModule (
  input a,
  input b,
  input c,
  input d,
  output q
);
  // Explicit operation from prompt: XOR all inputs, then invert (XNOR reduction).
  // q = 1 when an EVEN number of inputs are high.
  assign q = ~(a ^ b ^ c ^ d);
endmodule
