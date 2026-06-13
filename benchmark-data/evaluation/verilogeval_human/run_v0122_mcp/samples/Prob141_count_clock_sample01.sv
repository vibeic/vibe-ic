module TopModule (
  input             clk,
  input             reset,
  input             ena,
  output reg        pm,
  output reg [7:0]  hh,
  output reg [7:0]  mm,
  output reg [7:0]  ss
);

  // BCD increment helpers
  wire ss_roll = (ss == 8'h59);
  wire mm_roll = (mm == 8'h59);
  // hour rolls 12 -> 1; pm toggles on the 11 -> 12 transition
  wire hr_at_11 = (hh == 8'h11);
  wire hr_at_12 = (hh == 8'h12);

  // next-second BCD
  function [7:0] bcd_inc;
    input [7:0] v;
    begin
      if (v[3:0] == 4'd9) bcd_inc = {v[7:4] + 4'd1, 4'd0};
      else                bcd_inc = {v[7:4], v[3:0] + 4'd1};
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
      if (ss_roll) ss <= 8'h00;
      else         ss <= bcd_inc(ss);

      // minutes advance when seconds roll
      if (ss_roll) begin
        if (mm_roll) mm <= 8'h00;
        else         mm <= bcd_inc(mm);
      end

      // hours advance when minutes roll (i.e. seconds and minutes both roll)
      if (ss_roll && mm_roll) begin
        if (hr_at_11) begin
          hh <= 8'h12;
          pm <= ~pm;            // toggle am/pm crossing 11->12
        end else if (hr_at_12) begin
          hh <= 8'h01;
        end else begin
          hh <= bcd_inc(hh);
        end
      end
    end
  end

endmodule
