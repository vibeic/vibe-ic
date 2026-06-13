// Half adder: {cout,sum} = a + b.
module TopModule (
  input a,
  input b,
  output sum,
  output cout
);

  assign {cout, sum} = a + b;

endmodule
