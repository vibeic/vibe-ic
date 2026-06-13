module TopModule (
    input        clk,
    input        reset,
    input        ena,
    output reg   pm,
    output reg [7:0] hh,
    output reg [7:0] mm,
    output reg [7:0] ss
);
    // BCD rollover detection
    wire ss_max = (ss == 8'h59);
    wire mm_max = (mm == 8'h59);

    // Inlined BCD increment next-values
    wire [7:0] ss_inc = (ss[3:0] == 4'd9) ? {ss[7:4] + 4'd1, 4'd0} : {ss[7:4], ss[3:0] + 4'd1};
    wire [7:0] mm_inc = (mm[3:0] == 4'd9) ? {mm[7:4] + 4'd1, 4'd0} : {mm[7:4], mm[3:0] + 4'd1};
    wire [7:0] hh_inc = (hh[3:0] == 4'd9) ? {hh[7:4] + 4'd1, 4'd0} : {hh[7:4], hh[3:0] + 4'd1};

    always @(posedge clk) begin
        if (reset) begin
            pm <= 1'b0;
            hh <= 8'h12;
            mm <= 8'h00;
            ss <= 8'h00;
        end else if (ena) begin
            // seconds
            if (ss_max) ss <= 8'h00;
            else        ss <= ss_inc;

            // minutes increment when seconds wrap
            if (ss_max) begin
                if (mm_max) mm <= 8'h00;
                else        mm <= mm_inc;
            end

            // hours increment when both seconds and minutes wrap
            if (ss_max && mm_max) begin
                if (hh == 8'h12) hh <= 8'h01;
                else             hh <= hh_inc;
                // pm toggles on the transition from 11:59:59 -> 12:00:00
                if (hh == 8'h11) pm <= ~pm;
            end
        end
    end
endmodule
