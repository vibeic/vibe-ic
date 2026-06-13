module TopModule (
  input clk,
  input reset,
  input ena,
  output reg pm,
  output reg [7:0] hh,
  output reg [7:0] mm,
  output reg [7:0] ss
);

  // Rollover flags for the cascade of BCD counters.
  wire ss_roll = (ss == 8'h59);
  wire mm_roll = ss_roll && (mm == 8'h59);
  wire hh_roll = mm_roll && (hh == 8'h12); // 12 -> 01

  // Next BCD values (two-digit, lower digit 0..9).
  function [7:0] bcd_next;
    input [7:0] val;
    begin
      if (val[3:0] == 4'd9) bcd_next = {val[7:4] + 4'd1, 4'd0};
      else                  bcd_next = {val[7:4], val[3:0] + 4'd1};
    end
  endfunction

  always @(posedge clk) begin
    if (reset) begin
      pm <= 1'b0;
      hh <= 8'h12;
      mm <= 8'h00;
      ss <= 8'h00;
    end else if (ena) begin
      // seconds 00..59
      ss <= ss_roll ? 8'h00 : bcd_next(ss);
      // minutes 00..59 advance when seconds roll over
      if (ss_roll)
        mm <= mm_roll ? 8'h00 : bcd_next(mm);
      // hours 01..12 advance when minutes roll over
      if (mm_roll)
        hh <= (hh == 8'h12) ? 8'h01 : bcd_next(hh);
      // am/pm flips when hours go 11 -> 12
      if (mm_roll && (hh == 8'h11))
        pm <= ~pm;
    end
  end

endmodule
