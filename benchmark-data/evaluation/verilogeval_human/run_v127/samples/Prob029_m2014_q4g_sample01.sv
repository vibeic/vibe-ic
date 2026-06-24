module TopModule (
  input in1,
  input in2,
  input in3,
  output logic out
);

  // Two-input XNOR feeds one input of a two-input XOR; in3 is the other.
  assign out = (in1 ~^ in2) ^ in3;

endmodule
