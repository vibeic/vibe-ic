module TopModule (
  input  clk,
  input  reset,
  input  [31:0] in,
  output reg [31:0] out
);
  reg [31:0] in_prev;
  always @(posedge clk) begin
    if (reset) begin
      out <= 32'b0;
    end else begin
      // capture each bit that went 1 -> 0; remain set until reset
      out <= out | (in_prev & ~in);
    end
    in_prev <= in;
  end
endmodule
