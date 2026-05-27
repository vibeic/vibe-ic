module TopModule (
  input  clk,
  input  reset,
  output shift_ena
);

  // After (synchronous, active-high) reset, assert shift_ena for exactly
  // 4 clock cycles, then 0 forever until reset again.
  reg [2:0] count;  // counts cycles since reset, saturates at 4

  always @(posedge clk) begin
    if (reset)
      count <= 3'd0;
    else if (count < 3'd4)
      count <= count + 3'd1;
  end

  assign shift_ena = (count < 3'd4);

endmodule
