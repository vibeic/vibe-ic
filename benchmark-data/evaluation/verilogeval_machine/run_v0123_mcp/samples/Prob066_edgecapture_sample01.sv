module TopModule (
  input clk,
  input reset,
  input [31:0] in,
  output reg [31:0] out
);
  reg [31:0] d_last;
  always @(posedge clk) begin
    if (reset) begin
      out <= 32'b0;
    end else begin
      out <= out | (~in & d_last);
    end
    d_last <= in;
  end
endmodule
