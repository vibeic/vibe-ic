module TopModule (
    input        clk,
    input        reset,
    input        ena,
    output reg       pm,
    output reg [7:0] hh,
    output reg [7:0] mm,
    output reg [7:0] ss
);

    // BCD increment helper signals
    wire ss_max = (ss == 8'h59);
    wire mm_max = (mm == 8'h59);
    wire hh_max = (hh == 8'h12);  // wraps 12 -> 1
    wire hh_to12 = (hh == 8'h11); // 11 -> 12, where pm toggles

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
            if (ss_max) begin
                ss <= 8'h00;
                // minutes
                if (mm_max) begin
                    mm <= 8'h00;
                    // hours
                    if (hh_max) begin
                        hh <= 8'h01;
                    end else begin
                        hh <= bcd_inc(hh);
                    end
                    // pm toggles when going from 11 -> 12
                    if (hh_to12) begin
                        pm <= ~pm;
                    end
                end else begin
                    mm <= bcd_inc(mm);
                end
            end else begin
                ss <= bcd_inc(ss);
            end
        end
    end

endmodule
