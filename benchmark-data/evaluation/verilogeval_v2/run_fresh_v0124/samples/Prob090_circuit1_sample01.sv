module TopModule (
  input  a,
  input  b,
  output q
);
  // From the waveform q is 1 only when a=1 and b=1 => AND
  assign q = a & b;
endmodule
