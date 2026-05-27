module TopModule (
  input  a,
  input  b,
  output q
);

  // From the waveform q is high only when a=1 and b=1: AND
  assign q = a & b;

endmodule
