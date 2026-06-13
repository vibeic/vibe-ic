module TopModule (
  input  clk,
  input  reset,
  output shift_ena
);
  // After reset, assert shift_ena for exactly 4 cycles, then hold 0 until reset.
  // Use a 4-bit one-hot/shift token initialised to 4 ones on reset; shift in 0.
  reg [3:0] cnt;
  assign shift_ena = |cnt;

  always @(posedge clk) begin
    if (reset)
      cnt <= 4'b1111;            // 4 cycles of enable
    else
      cnt <= {1'b0, cnt[3:1]};   // shift out one each cycle, then stays 0
  end
endmodule
