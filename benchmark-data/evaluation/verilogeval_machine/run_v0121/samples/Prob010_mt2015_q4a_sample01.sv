module TopModule (
  input  x,
  input  y,
  output z
);
  // z = (x XOR y) AND x  ==  x & ~y
  assign z = (x ^ y) & x;
endmodule
