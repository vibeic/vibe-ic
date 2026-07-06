module TopModule (
  input clk,
  input reset,
  input ena,
  output reg pm,
  output reg [7:0] hh,
  output reg [7:0] mm,
  output reg [7:0] ss
);

  always @(posedge clk) begin
    if (reset) begin
      pm <= 1'b0;
      hh <= 8'h12;
      mm <= 8'h00;
      ss <= 8'h00;
    end else if (ena) begin
      // pm toggles at 11:59:59 -> 12:00:00
      if (hh == 8'h11 && mm == 8'h59 && ss == 8'h59)
        pm <= ~pm;
      // hours: 12 -> 01 ; else +1 (BCD) on minute+second rollover
      if (mm == 8'h59 && ss == 8'h59) begin
        if (hh == 8'h12)
          hh <= 8'h01;
        else if (hh[3:0] == 4'h9)
          hh <= hh + 8'h07;   // x9 -> (x+1)0 in BCD
        else
          hh <= hh + 8'h01;
      end
      // minutes: 00..59 BCD
      if (ss == 8'h59) begin
        if (mm == 8'h59)
          mm <= 8'h00;
        else if (mm[3:0] == 4'h9)
          mm <= mm + 8'h07;
        else
          mm <= mm + 8'h01;
      end
      // seconds: 00..59 BCD
      if (ss == 8'h59)
        ss <= 8'h00;
      else if (ss[3:0] == 4'h9)
        ss <= ss + 8'h07;
      else
        ss <= ss + 8'h01;
    end
  end

endmodule
