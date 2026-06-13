// D flip-flop, positive-edge triggered, active-high ASYNCHRONOUS reset to 0.
module TopModule (
  input clk,
  input d,
  input ar,
  output logic q
);

  initial q = 1'b0;

  always @(posedge clk or posedge ar) begin
    if (ar)
      q <= 1'b0;
    else
      q <= d;
  end

endmodule
