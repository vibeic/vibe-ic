module TopModule(
    input        clk,
    input        reset,
    input        ena,
    output       pm,
    output [7:0] hh,
    output [7:0] mm,
    output [7:0] ss
);
    reg        pm_r;
    reg [7:0]  hh_r, mm_r, ss_r;   // BCD: [7:4]=tens, [3:0]=ones

    // BCD increment helper signals
    wire ss_roll = (ss_r == 8'h59);
    wire mm_roll = (mm_r == 8'h59);
    // hour rolls 12->01 ; 11->12 toggles pm
    wire hh_is_11 = (hh_r == 8'h11);
    wire hh_is_12 = (hh_r == 8'h12);

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
            pm_r <= 1'b0;
            hh_r <= 8'h12;
            mm_r <= 8'h00;
            ss_r <= 8'h00;
        end else if (ena) begin
            // seconds
            if (ss_roll) begin
                ss_r <= 8'h00;
                // minutes
                if (mm_roll) begin
                    mm_r <= 8'h00;
                    // hours: 1..12, pm toggles on 11->12
                    if (hh_is_11) begin
                        hh_r <= 8'h12;
                        pm_r <= ~pm_r;
                    end else if (hh_is_12) begin
                        hh_r <= 8'h01;
                    end else begin
                        hh_r <= bcd_inc(hh_r);
                    end
                end else begin
                    mm_r <= bcd_inc(mm_r);
                end
            end else begin
                ss_r <= bcd_inc(ss_r);
            end
        end
    end

    assign pm = pm_r;
    assign hh = hh_r;
    assign mm = mm_r;
    assign ss = ss_r;
endmodule
