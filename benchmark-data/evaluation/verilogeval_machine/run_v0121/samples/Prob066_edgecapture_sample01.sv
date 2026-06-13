module TopModule (
  input clk,
  input reset,
  input [31:0] in,
  output reg [31:0] out
);
  reg [31:0] d_last = 32'b0;

  always @(posedge clk) begin
    d_last <= in;                       // store previous value of in
    if (reset)
      out <= 32'b0;                     // synchronous reset
    else
      out <= out | (~in & d_last);      // capture 1->0 falling edge per bit
  end
endmodule
