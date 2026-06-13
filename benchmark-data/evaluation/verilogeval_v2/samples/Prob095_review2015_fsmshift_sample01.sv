module TopModule (
  input  clk,
  input  reset,
  output shift_ena
);
  // Whenever reset is asserted, assert shift_ena for exactly the next 4 clock
  // cycles, then hold 0 forever (until reset again).
  reg [2:0] count;  // counts 0..4; shift_ena high while count < 4
  always @(posedge clk) begin
    if (reset)
      count <= 3'd0;
    else if (count < 3'd4)
      count <= count + 3'd1;
  end
  assign shift_ena = (count < 3'd4);
endmodule
