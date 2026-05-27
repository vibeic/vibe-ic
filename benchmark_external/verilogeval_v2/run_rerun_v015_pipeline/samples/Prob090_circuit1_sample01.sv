module TopModule (
  input  a,
  input  b,
  output q
);
  // From waveform: q = 1 only when a=1 and b=1 -> q = a AND b
  assign q = a & b;
endmodule
