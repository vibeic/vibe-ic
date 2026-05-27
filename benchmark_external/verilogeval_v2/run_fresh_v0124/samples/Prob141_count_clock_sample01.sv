module TopModule (
    input        clk,
    input        reset,
    input        ena,
    output reg   pm,
    output reg [7:0] hh,
    output reg [7:0] mm,
    output reg [7:0] ss
);
    // BCD counters. hh 01-12, mm 00-59, ss 00-59, pm am/pm flag.
    wire ss_rollover = (ss == 8'h59);
    wire mm_rollover = (mm == 8'h59);
    wire hh_is_11    = (hh == 8'h11);
    wire hh_is_12    = (hh == 8'h12);

    // helper task-like inline BCD increment via functions
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
            if (ss_rollover) ss <= 8'h00;
            else             ss <= bcd_inc(ss);
            // minutes
            if (ss_rollover) begin
                if (mm_rollover) mm <= 8'h00;
                else             mm <= bcd_inc(mm);
            end
            // hours and pm
            if (ss_rollover && mm_rollover) begin
                if (hh_is_11) begin
                    hh <= 8'h12;
                    pm <= ~pm;          // 11 -> 12 toggles am/pm
                end else if (hh_is_12) begin
                    hh <= 8'h01;        // 12 -> 1
                end else begin
                    hh <= bcd_inc(hh);
                end
            end
        end
    end
endmodule
