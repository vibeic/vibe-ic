module TopModule (
  input clk,
  input reset,
  output shift_ena
);

  // Count the 4 enabled cycles after reset. shift_ena high while count < 4.
  reg [2:0] count;

  always @(posedge clk) begin
    if (reset)
      count <= 3'd0;
    else if (count != 3'd4)
      count <= count + 3'd1;
  end

  assign shift_ena = (count != 3'd4);

endmodule
