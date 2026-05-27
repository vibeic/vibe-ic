module TopModule (
    input        clk,
    input        reset,
    input        ena,
    output reg       pm,
    output reg [7:0] hh,
    output reg [7:0] mm,
    output reg [7:0] ss
);
    // BCD digits: hh,mm,ss each two BCD digits (high nibble = tens, low nibble = units)
    wire ss_max = (ss == 8'h59);
    wire mm_max = (mm == 8'h59);
    wire hh_max = (hh == 8'h12);

    // helper increment-with-rollover for a two-digit BCD value bounded at 59
    function [7:0] bcd_inc59;
        input [7:0] v;
        begin
            if (v[3:0] == 4'd9) begin
                if (v[7:4] == 4'd5) bcd_inc59 = 8'h00;
                else                bcd_inc59 = {v[7:4] + 4'd1, 4'd0};
            end else
                bcd_inc59 = {v[7:4], v[3:0] + 4'd1};
        end
    endfunction

    // hour increment 1..12 -> wrap to 1 (BCD)
    function [7:0] hh_inc;
        input [7:0] v;
        begin
            if (v == 8'h12)      hh_inc = 8'h01;
            else if (v[3:0]==4'd9) hh_inc = {v[7:4] + 4'd1, 4'd0};
            else                 hh_inc = {v[7:4], v[3:0] + 4'd1};
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
            if (ss_max) begin
                ss <= 8'h00;
                if (mm_max) begin
                    mm <= 8'h00;
                    // hour rolls; toggle pm when crossing from 11 to 12
                    if (hh == 8'h11)
                        pm <= ~pm;
                    hh <= hh_inc(hh);
                end else begin
                    mm <= bcd_inc59(mm);
                end
            end else begin
                ss <= bcd_inc59(ss);
            end
        end
    end
endmodule
