// Prob027_fadd — full adder. {cout,sum} = a + b + cin.
module TopModule (
  input a,
  input b,
  input cin,
  output cout,
  output sum
);

  assign {cout, sum} = a + b + cin;

endmodule
