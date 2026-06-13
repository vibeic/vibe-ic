// out = (NOT(in1 XOR in2)) XOR in3
module TopModule (
  input in1,
  input in2,
  input in3,
  output out
);

  assign out = (~(in1 ^ in2)) ^ in3;

endmodule
