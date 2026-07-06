module TopModule (
  input clk,
  input load,
  input [9:0] data,
  output tc
);

  reg [9:0] count_value;
  always @(posedge clk) begin
    if (load)
      count_value <= data;
    else if (count_value != 0)
      count_value <= count_value - 1;
  end
  assign tc = (count_value == 0);


  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    count_value = 0;
  end

endmodule
