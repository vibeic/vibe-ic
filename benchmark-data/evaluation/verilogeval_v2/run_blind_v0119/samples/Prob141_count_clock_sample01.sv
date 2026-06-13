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
    wire hh_max = (hh == 8'h12); // 12 -> 01 rollover point on hour increment

    // increment a 2-digit BCD value
    function [7:0] bcd_inc;
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
            if (ss_max) begin
                ss <= 8'h00;
                // minutes
                if (mm_max) begin
                    mm <= 8'h00;
                    // hours: 12-hour cycle 1..12, toggle pm when going 11 -> 12
                    if (hh == 8'h12)
                        hh <= 8'h01;
                    else
                        hh <= bcd_inc(hh);
                    if (hh == 8'h11)
                        pm <= ~pm;
                end else begin
                    mm <= bcd_inc(mm);
                end
            end else begin
                ss <= bcd_inc(ss);
            end
        end
    end
endmodule
