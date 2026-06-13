module TopModule (
    input        clk,
    input        reset,
    input        ena,
    output reg       pm,
    output reg [7:0] hh,
    output reg [7:0] mm,
    output reg [7:0] ss
);
    // BCD helpers
    wire ss_max = (ss == 8'h59);
    wire mm_max = (mm == 8'h59);
    wire hh_max = (hh == 8'h12);   // hour 12 wraps to 1

    function [7:0] bcd_inc;          // increment a 2-digit BCD value (00..99)
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
            pm <= 1'b0;
            hh <= 8'h12;
            mm <= 8'h00;
            ss <= 8'h00;
        end else if (ena) begin
            // seconds
            if (ss_max) ss <= 8'h00;
            else        ss <= bcd_inc(ss);

            // minutes increment when seconds roll over
            if (ss_max) begin
                if (mm_max) mm <= 8'h00;
                else        mm <= bcd_inc(mm);
            end

            // hours increment when minutes roll over (i.e. ss & mm both maxed)
            if (ss_max && mm_max) begin
                if (hh_max) hh <= 8'h01;          // 12 -> 1
                else        hh <= bcd_inc(hh);
                // AM/PM toggles when going 11 -> 12
                if (hh == 8'h11) pm <= ~pm;
            end
        end
    end
endmodule
