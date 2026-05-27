module TopModule (
  input clk,
  input j,
  input k,
  output reg Q
);

  initial Q = 1'b0;

  always @(posedge clk) begin
    Q <= (j & ~Q) | (~k & Q);
  end

endmodule
