module TopModule(
    input        clk,
    input        reset,
    input        ena,
    output reg   pm,
    output reg [7:0] hh,
    output reg [7:0] mm,
    output reg [7:0] ss
);
    wire ss_max = (ss == 8'h59);
    wire mm_max = (mm == 8'h59);

    // BCD +1 for each two-digit field (combinational helper wires)
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
            if (!ss_max) begin
                ss <= ss_inc;
            end else begin
                ss <= 8'h00;
                if (!mm_max) begin
                    mm <= mm_inc;
                end else begin
                    mm <= 8'h00;
                    // hour rollover: 1..11 -> increment ; 11->12 toggles pm ; 12->1
                    if (hh == 8'h12) begin
                        hh <= 8'h01;
                    end else if (hh == 8'h11) begin
                        hh <= 8'h12;
                        pm <= ~pm;
                    end else begin
                        hh <= hh_inc;
                    end
                end
            end
        end
    end
endmodule
