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
  always @(posedge clk) begin
    if (enable) begin
      Q[0] <= S;
      Q[7:1] <= Q[6:0];
    end
  end
  always @(*) begin
    Z = Q[{A, B, C}];
  end
endmodule
