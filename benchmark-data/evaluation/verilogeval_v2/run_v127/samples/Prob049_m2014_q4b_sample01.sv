module TopModule (
  input clk,
  input ar,
  input d,
  output reg q
);

  always @(posedge clk, posedge ar)
    if (ar)
      q <= 1'b0;
    else
      q <= d;

endmodule
