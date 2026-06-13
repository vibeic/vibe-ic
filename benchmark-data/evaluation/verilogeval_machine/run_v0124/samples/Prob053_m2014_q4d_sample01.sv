module TopModule (
  input clk,
  input in,
  output logic out
);
  initial out = 1'b0;
  always @(posedge clk)
    out <= in ^ out;
endmodule
