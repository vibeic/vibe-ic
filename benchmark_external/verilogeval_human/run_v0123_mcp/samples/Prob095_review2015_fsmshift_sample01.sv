module TopModule (
  input clk,
  input reset,
  output shift_ena
);
  // After reset, assert shift_ena for 4 cycles, then 0 forever.
  reg [2:0] cnt;   // counts cycles since reset (saturates)
  always @(posedge clk) begin
    if (reset)
      cnt <= 3'd0;
    else if (cnt < 3'd4)
      cnt <= cnt + 3'd1;
  end
  assign shift_ena = (cnt < 3'd4);
endmodule
