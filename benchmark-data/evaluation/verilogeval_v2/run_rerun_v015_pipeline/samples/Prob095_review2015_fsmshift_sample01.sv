module TopModule (
  input  clk,
  input  reset,
  output shift_ena
);
  // After synchronous active-high reset, assert shift_ena for exactly 4 cycles, then 0 forever.
  // Use a 2-bit counter that counts the 4 active cycles then saturates.
  reg [1:0] count;
  reg       active;

  always @(posedge clk) begin
    if (reset) begin
      count  <= 2'd0;
      active <= 1'b1;
    end else if (active) begin
      if (count == 2'd3) begin
        active <= 1'b0;   // after 4th asserted cycle, stop
      end
      count <= count + 2'd1;
    end
  end

  assign shift_ena = active;
endmodule
