// AND of a,b via continuous assign AND via combinational always block.
module TopModule (
  input a,
  input b,
  output out_assign,
  output reg out_alwaysblock
);

  assign out_assign = a & b;

  always @(*)
    out_alwaysblock = a & b;

endmodule
