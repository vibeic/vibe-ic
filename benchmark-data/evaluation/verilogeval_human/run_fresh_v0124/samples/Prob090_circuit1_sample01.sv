module TopModule (
  input a,
  input b,
  output q
);

  // Waveform: q is 1 only when a=1 and b=1  => q = a & b
  assign q = a & b;

endmodule
