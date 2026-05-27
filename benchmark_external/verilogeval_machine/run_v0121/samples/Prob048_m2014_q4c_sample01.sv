module TopModule (
  input clk,
  input d,
  input r,
  output logic q
);

  initial q = 1'b0;

  always @(posedge clk) begin
    if (r)
      q <= 1'b0;
    else
      q <= d;
  end

endmodule
