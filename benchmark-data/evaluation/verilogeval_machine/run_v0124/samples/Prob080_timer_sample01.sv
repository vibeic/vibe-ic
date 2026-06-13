module TopModule (
  input clk,
  input load,
  input [9:0] data,
  output tc
);
  reg [9:0] count;
  always @(posedge clk) begin
    if (load)
      count <= data;
    else if (count != 10'd0)
      count <= count - 10'd1;
  end
  assign tc = (count == 10'd0);

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    count = 0;
  end

endmodule
