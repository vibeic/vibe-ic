module TopModule (
  input  x3,
  input  x2,
  input  x1,
  output f
);
  // f=1 at (x3,x2,x1): 010,011,101,111
  assign f = (~x3 & x2 & ~x1) | (~x3 & x2 & x1) | (x3 & ~x2 & x1) | (x3 & x2 & x1);
endmodule
