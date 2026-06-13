module TopModule (
    input        clk,
    input        reset,
    input        ena,
    output       pm,
    output [7:0] hh,
    output [7:0] mm,
    output [7:0] ss
);
    reg       pm_r;
    reg [7:0] hh_r, mm_r, ss_r;

    // helper: increment a 2-digit BCD value with wrap at (max+1)
    // returns next value; carry indicates wrap-to-zero
    function [8:0] bcd_inc; // {carry, value[7:0]}
        input [7:0] v;
        input [7:0] maxv; // e.g. 8'h59
        reg [3:0] lo, hi;
        begin
            lo = v[3:0];
            hi = v[7:4];
            if (v == maxv) begin
                bcd_inc = {1'b1, 8'h00};
            end else if (lo == 4'd9) begin
                bcd_inc = {1'b0, hi + 4'd1, 4'd0};
            end else begin
                bcd_inc = {1'b0, hi, lo + 4'd1};
            end
        end
    endfunction

    reg [8:0] ss_n, mm_n;
    reg       sec_carry, min_carry;

    always @(*) begin
        ss_n      = bcd_inc(ss_r, 8'h59);
        sec_carry = ss_n[8];
        mm_n      = bcd_inc(mm_r, 8'h59);
        min_carry = mm_n[8];
    end

    always @(posedge clk) begin
        if (reset) begin
            pm_r <= 1'b0;
            hh_r <= 8'h12;
            mm_r <= 8'h00;
            ss_r <= 8'h00;
        end else if (ena) begin
            ss_r <= ss_n[7:0];
            if (sec_carry) begin
                mm_r <= mm_n[7:0];
                if (min_carry) begin
                    // advance hour
                    if (hh_r == 8'h11) begin
                        hh_r <= 8'h12;
                        pm_r <= ~pm_r;       // 11->12 toggles AM/PM
                    end else if (hh_r == 8'h12) begin
                        hh_r <= 8'h01;
                    end else if (hh_r[3:0] == 4'd9) begin
                        hh_r <= {hh_r[7:4] + 4'd1, 4'd0};
                    end else begin
                        hh_r <= {hh_r[7:4], hh_r[3:0] + 4'd1};
                    end
                end
            end
        end
    end

    assign pm = pm_r;
    assign hh = hh_r;
    assign mm = mm_r;
    assign ss = ss_r;

endmodule
