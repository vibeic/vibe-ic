module TopModule (
    input        clk,
    input        reset,
    input        ena,
    output reg   pm,
    output reg [7:0] hh,
    output reg [7:0] mm,
    output reg [7:0] ss
);
    // BCD increment helper: returns carry for two-digit BCD wrapping at modulo
    // ss, mm count 00-59 ; hh counts 01-12 ; pm toggles when rolling 11->12
    wire ss_carry = (ss == 8'h59);
    wire mm_carry = (mm == 8'h59) && ss_carry;
    wire hh_carry = (hh == 8'h12) && mm_carry; // wrap 12 -> 01

    // PM toggles when going from 11:59:59 -> 12:00:00
    wire pm_toggle = (hh == 8'h11) && mm_carry;

    function [7:0] bcd_inc;
        input [7:0] v;
        reg [3:0] lo, hi;
        begin
            lo = v[3:0];
            hi = v[7:4];
            if (lo == 4'd9) begin
                lo = 4'd0;
                hi = hi + 4'd1;
            end else begin
                lo = lo + 4'd1;
            end
            bcd_inc = {hi, lo};
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
            if (ss_carry) ss <= 8'h00;
            else          ss <= bcd_inc(ss);

            // minutes
            if (ss_carry) begin
                if (mm == 8'h59) mm <= 8'h00;
                else             mm <= bcd_inc(mm);
            end

            // hours
            if (mm_carry) begin
                if (hh == 8'h12) hh <= 8'h01;
                else             hh <= bcd_inc(hh);
            end

            // pm indicator
            if (pm_toggle) pm <= ~pm;
        end
    end
endmodule
