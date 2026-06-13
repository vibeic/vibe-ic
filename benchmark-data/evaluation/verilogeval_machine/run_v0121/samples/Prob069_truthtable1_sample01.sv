module TopModule (
  input x3,
  input x2,
  input x1,
  output f
);
  // minterms 2,3,5,7 -> minimal SOP via QM:
  //   01- = ~x3 & x2   (essential, covers 2,3)
  //   1-1 =  x3 & x1   (essential, covers 5,7)
  assign f = (~x3 & x2) | (x3 & x1);
endmodule
