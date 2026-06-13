module TopModule (
  input clk,
  input reset,
  input ena,
  output reg pm,
  output reg [7:0] hh,
  output reg [7:0] mm,
  output reg [7:0] ss
);
    // BCD helpers
    wire ss_max = (ss == 8'h59);
    wire mm_max = (mm == 8'h59);
    wire hh_max = (hh == 8'h12);

    // increment a 2-digit BCD value
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
            if (ss_max) ss <= 8'h00;
            else        ss <= bcd_inc(ss);
            // minutes
            if (ss_max) begin
                if (mm_max) mm <= 8'h00;
                else        mm <= bcd_inc(mm);
            end
            // hours + pm
            if (ss_max && mm_max) begin
                if (hh_max)       hh <= 8'h01;       // 12 -> 01
                else if (hh == 8'h11) begin          // 11 -> 12 : toggle pm
                    hh <= 8'h12;
                    pm <= ~pm;
                end else          hh <= bcd_inc(hh);
            end
        end
    end
endmodule
