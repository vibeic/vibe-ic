module TopModule (
  input a,
  input b,
  output q
);

  // Per waveform, q is high only when both a and b are 1.
  assign q = a & b;

endmodule
