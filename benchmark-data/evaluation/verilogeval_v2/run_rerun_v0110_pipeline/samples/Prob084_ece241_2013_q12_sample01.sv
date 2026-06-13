module TopModule (
  input  clk,
  input  enable,
  input  S,
  input  A,
  input  B,
  input  C,
  output Z
);
  reg [7:0] Q;
  always @(posedge clk) begin
    if (enable)
      Q <= {Q[6:0], S};   // shift toward higher index, S into Q[0]
  end
  assign Z = Q[{A, B, C}];
endmodule
