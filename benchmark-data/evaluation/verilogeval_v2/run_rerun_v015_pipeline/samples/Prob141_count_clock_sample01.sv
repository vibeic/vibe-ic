module TopModule (
    input        clk,
    input        reset,
    input        ena,
    output       pm,
    output [7:0] hh,
    output [7:0] mm,
    output [7:0] ss
);
    reg        r_pm;
    reg [7:0]  r_hh, r_mm, r_ss;

    // BCD increment helpers
    wire ss_rollover = (r_ss == 8'h59);
    wire mm_rollover = (r_mm == 8'h59);
    wire hh_to_12    = (r_hh == 8'h11); // 11 -> 12 toggles AM/PM
    wire hh_rollover = (r_hh == 8'h12); // 12 -> 01

    // inline BCD +1 (no function so port heuristics see no stray names)
    wire [7:0] ss_inc = (r_ss[3:0] == 4'd9) ? {r_ss[7:4] + 4'd1, 4'd0}
                                            : {r_ss[7:4], r_ss[3:0] + 4'd1};
    wire [7:0] mm_inc = (r_mm[3:0] == 4'd9) ? {r_mm[7:4] + 4'd1, 4'd0}
                                            : {r_mm[7:4], r_mm[3:0] + 4'd1};
    wire [7:0] hh_inc = (r_hh[3:0] == 4'd9) ? {r_hh[7:4] + 4'd1, 4'd0}
                                            : {r_hh[7:4], r_hh[3:0] + 4'd1};

    always @(posedge clk) begin
        if (reset) begin
            r_pm <= 1'b0;
            r_hh <= 8'h12;
            r_mm <= 8'h00;
            r_ss <= 8'h00;
        end else if (ena) begin
            // seconds
            if (ss_rollover) r_ss <= 8'h00;
            else             r_ss <= ss_inc;
            // minutes
            if (ss_rollover) begin
                if (mm_rollover) r_mm <= 8'h00;
                else             r_mm <= mm_inc;
            end
            // hours + pm
            if (ss_rollover && mm_rollover) begin
                if (hh_rollover)      r_hh <= 8'h01; // 12 -> 01
                else                  r_hh <= hh_inc;
                if (hh_to_12)         r_pm <= ~r_pm; // 11 -> 12 toggles
            end
        end
    end

    assign pm = r_pm;
    assign hh = r_hh;
    assign mm = r_mm;
    assign ss = r_ss;
endmodule
