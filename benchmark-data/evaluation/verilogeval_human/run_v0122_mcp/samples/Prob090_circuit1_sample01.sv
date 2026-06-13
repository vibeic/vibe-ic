// Waveform decode: q is high only when both a and b are 1 -> q = a & b.
module TopModule (
  input a,
  input b,
  output q
);

  assign q = a & b;

endmodule
