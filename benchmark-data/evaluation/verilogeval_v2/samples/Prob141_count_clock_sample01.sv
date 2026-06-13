module TopModule (
  input  clk,
  input  reset,
  input  ena,
  output reg pm,
  output reg [7:0] hh,
  output reg [7:0] mm,
  output reg [7:0] ss
);

  wire ss_max = (ss == 8'h59);
  wire mm_max = (mm == 8'h59);
  wire hh_max = (hh == 8'h12);  // 12 -> 1, with pm toggle when 11 -> 12

  // helper: increment a BCD value, wrapping at the given max
  function [7:0] bcd_inc;
    input [7:0] v;
    begin
      if (v[3:0] == 4'h9) bcd_inc = {v[7:4] + 4'h1, 4'h0};
      else                bcd_inc = {v[7:4], v[3:0] + 4'h1};
    end
  endfunction

  always @(posedge clk) begin
    if (reset) begin
      pm <= 1'b0;
      hh <= 8'h12;
      mm <= 8'h00;
      ss <= 8'h00;
    end else if (ena) begin
      // seconds
      if (ss_max) ss <= 8'h00;
      else        ss <= bcd_inc(ss);

      // minutes
      if (ss_max) begin
        if (mm_max) mm <= 8'h00;
        else        mm <= bcd_inc(mm);
      end

      // hours and pm
      if (ss_max && mm_max) begin
        if (hh == 8'h11) begin
          hh <= 8'h12;
          pm <= ~pm;            // 11 -> 12 toggles AM/PM
        end else if (hh == 8'h12) begin
          hh <= 8'h01;          // 12 -> 1, no pm change
        end else begin
          hh <= bcd_inc(hh);
        end
      end
    end
  end

endmodule
