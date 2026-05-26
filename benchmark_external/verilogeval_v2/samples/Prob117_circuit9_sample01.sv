module TopModule (
  input        clk,
  input        a,
  output [2:0] q
);
  reg [2:0] r;
  always @(posedge clk) begin
    if (a)
      r <= 3'd4;
    else if (r == 3'd6)
      r <= 3'd0;
    else
      r <= r + 3'd1;
  end
  assign q = r;
endmodule
