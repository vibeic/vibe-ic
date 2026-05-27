module TopModule (
  input a,
  input b,
  input c,
  output out
);

  // K-map: out is 0 only when a=0,b=0,c=0; 1 otherwise => out = a | b | c
  assign out = a | b | c;

endmodule
