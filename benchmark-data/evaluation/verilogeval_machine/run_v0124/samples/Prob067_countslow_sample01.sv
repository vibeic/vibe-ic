module TopModule (
  input clk,
  input slowena,
  input reset,
  output reg [3:0] q
);

  // Structure beats the adjective: the prose calls reset "asynchronous" but
  // describes a block "triggered on the rising edge of the clock" that
  // "first checks the reset signal". A reset checked INSIDE an
  // @(posedge clk)-only block (not in the sensitivity list) is SYNCHRONOUS.
  // Therefore reset is NOT in the sensitivity list.
  always @(posedge clk) begin
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
