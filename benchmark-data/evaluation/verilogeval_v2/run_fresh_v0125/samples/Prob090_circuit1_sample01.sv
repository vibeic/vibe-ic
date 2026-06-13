module TopModule (
  input  a,
  input  b,
  output q
);

  // From waveform: q is 1 only when both a and b are 1 (AND)
  assign q = a & b;

endmodule
