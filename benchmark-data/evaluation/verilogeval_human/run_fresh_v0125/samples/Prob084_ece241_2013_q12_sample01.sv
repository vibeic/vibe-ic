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

  // Shift register: S feeds Q[0]; on enable, shift toward higher index.
  always @(posedge clk) begin
    if (enable)
      Q <= {Q[6:0], S};
  end

  // 8:1 mux selecting Q[{A,B,C}]
  always @(*) begin
    Z = Q[{A, B, C}];
  end

endmodule
