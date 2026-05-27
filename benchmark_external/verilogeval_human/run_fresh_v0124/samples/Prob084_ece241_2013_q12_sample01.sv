module TopModule (
  input clk,
  input enable,
  input S,
  input A,
  input B,
  input C,
  output reg Z
);

  reg [7:0] Q;

  // S feeds Q[0]; on enable, bits shift up (Q[k] <= Q[k-1]), Q[0] <= S.
  always @(posedge clk) begin
    if (enable)
      Q <= {Q[6:0], S};
  end

  // Z selects Q[ABC], with A as the MSB of the 3-bit index.
  always @(*) begin
    Z = Q[{A, B, C}];
  end

endmodule
