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
    reg [7:0]  hh_r, mm_r, ss_r;

    wire ss_max = (ss_r == 8'h59);
    wire mm_max = (mm_r == 8'h59);
    wire hh_max = (hh_r == 8'h12); // 12 -> rolls to 01
    wire hh_to12 = (hh_r == 8'h11); // 11 -> 12 toggles pm

    always @(posedge clk) begin
        if (reset) begin
            pm_r <= 1'b0;
            hh_r <= 8'h12;
            mm_r <= 8'h00;
            ss_r <= 8'h00;
        end else if (ena) begin
            // seconds
            if (ss_max) ss_r <= 8'h00;
            else if (ss_r[3:0] == 4'h9) ss_r <= {ss_r[7:4] + 4'd1, 4'h0};
            else ss_r <= ss_r + 8'h01;

            // minutes increment when seconds wrap
            if (ss_max) begin
                if (mm_max) mm_r <= 8'h00;
                else if (mm_r[3:0] == 4'h9) mm_r <= {mm_r[7:4] + 4'd1, 4'h0};
                else mm_r <= mm_r + 8'h01;
            end

            // hours increment when minutes and seconds wrap
            if (ss_max && mm_max) begin
                if (hh_max) hh_r <= 8'h01;
                else if (hh_r[3:0] == 4'h9) hh_r <= {hh_r[7:4] + 4'd1, 4'h0};
                else hh_r <= hh_r + 8'h01;
                // pm toggles when going from 11 to 12
                if (hh_to12) pm_r <= ~pm_r;
            end
        end
    end

    assign pm = pm_r;
    assign hh = hh_r;
    assign mm = mm_r;
    assign ss = ss_r;
endmodule
