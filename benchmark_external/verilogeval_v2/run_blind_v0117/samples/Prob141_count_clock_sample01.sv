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
    wire hh_max = (hh == 8'h12);

    // increment a 2-digit BCD counter (helpers via functions)
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
            if (!ss_max) begin
                ss <= bcd_inc(ss);
            end else begin
                ss <= 8'h00;
                if (!mm_max) begin
                    mm <= bcd_inc(mm);
                end else begin
                    mm <= 8'h00;
                    // hour rollover
                    if (hh == 8'h11) begin
                        hh <= 8'h12;
                        pm <= ~pm;       // 11:59:59 -> 12:00:00 toggles AM/PM
                    end else if (hh == 8'h12) begin
                        hh <= 8'h01;     // 12 -> 1, no toggle
                    end else begin
                        hh <= bcd_inc(hh);
                    end
                end
            end
        end
    end
endmodule
