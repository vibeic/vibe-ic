module TopModule (
  input clk,
  input slowena,
  input reset,
  output reg [3:0] q
);
  always @(posedge clk or posedge reset) begin
    if (reset)
      q <= 4'd0;
    else if (slowena) begin
      if (q == 4'd9)
        q <= 4'd0;
      else
        q <= q + 4'd1;
    end
    // slowena low: hold
  end
endmodule
