module TopModule (
  input        clk,
  input        reset,
  input        ena,
  output       pm,
  output [7:0] hh,
  output [7:0] mm,
  output [7:0] ss
);

  reg        pm_r;
  reg [7:0]  hh_r, mm_r, ss_r;

  wire ss_roll = (ss_r == 8'h59);
  wire mm_roll = (mm_r == 8'h59);
  wire hh_is12 = (hh_r == 8'h12);
  wire hh_is11 = (hh_r == 8'h11);

  // BCD increment helper for a two-digit 00..59 counter
  function [7:0] bcd_inc;
    input [7:0] v;
    begin
      if (v[3:0] == 4'd9)
        bcd_inc = {v[7:4] + 4'd1, 4'd0};
      else
        bcd_inc = {v[7:4], v[3:0] + 4'd1};
    end
  endfunction

  always @(posedge clk) begin
    if (reset) begin
      pm_r <= 1'b0;
      hh_r <= 8'h12;
      mm_r <= 8'h00;
      ss_r <= 8'h00;
    end else if (ena) begin
      // seconds
      if (ss_roll)
        ss_r <= 8'h00;
      else
        ss_r <= bcd_inc(ss_r);

      // minutes
      if (ss_roll) begin
        if (mm_roll)
          mm_r <= 8'h00;
        else
          mm_r <= bcd_inc(mm_r);
      end

      // hours and pm
      if (ss_roll && mm_roll) begin
        if (hh_is11) begin
          // 11 -> 12 toggles am/pm
          hh_r <= 8'h12;
          pm_r <= ~pm_r;
        end else if (hh_is12) begin
          // 12 -> 01
          hh_r <= 8'h01;
        end else begin
          hh_r <= bcd_inc(hh_r);
        end
      end
    end
  end

  assign pm = pm_r;
  assign hh = hh_r;
  assign mm = mm_r;
  assign ss = ss_r;

endmodule
