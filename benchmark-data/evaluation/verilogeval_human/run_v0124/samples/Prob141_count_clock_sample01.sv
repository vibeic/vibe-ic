module TopModule (
  input clk,
  input reset,
  input ena,
  output reg pm,
  output reg [7:0] hh,
  output reg [7:0] mm,
  output reg [7:0] ss
);

  // Carry/wrap conditions (combinational)
  wire ss_wrap = (ss == 8'h59);
  wire mm_wrap = (mm == 8'h59);
  // hours wrap from 12 -> happens when carrying into hours
  wire sec_carry = ena & ss_wrap;            // minutes advance
  wire min_carry = sec_carry & mm_wrap;      // hours advance

  always @(posedge clk) begin
    if (reset) begin
      pm <= 1'b0;
      hh <= 8'h12;
      mm <= 8'h00;
      ss <= 8'h00;
    end else if (ena) begin
      // seconds 00-59 BCD
      if (ss_wrap)
        ss <= 8'h00;
      else if (ss[3:0] == 4'd9)
        ss <= {ss[7:4] + 4'd1, 4'd0};
      else
        ss <= {ss[7:4], ss[3:0] + 4'd1};

      // minutes 00-59 BCD, advance on seconds wrap
      if (sec_carry) begin
        if (mm_wrap)
          mm <= 8'h00;
        else if (mm[3:0] == 4'd9)
          mm <= {mm[7:4] + 4'd1, 4'd0};
        else
          mm <= {mm[7:4], mm[3:0] + 4'd1};
      end

      // hours 01-12 with am/pm toggle, advance on minutes wrap
      if (min_carry) begin
        if (hh == 8'h12)
          hh <= 8'h01;
        else if (hh == 8'h11) begin
          hh <= 8'h12;
          pm <= ~pm;
        end else if (hh[3:0] == 4'd9)
          hh <= {hh[7:4] + 4'd1, 4'd0};
        else
          hh <= {hh[7:4], hh[3:0] + 4'd1};
      end
    end
  end

endmodule
