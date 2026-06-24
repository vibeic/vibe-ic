// freq_divbyfrac: fractional (3.5x) clock divider via the double-edge
// technique. A mod-7 counter (MUL2_DIV_CLK = 2*3.5 = 7) drives two
// registered intermediate clocks: an "average" clock on the posedge and an
// "adjust" clock on the negedge (the negedge registration supplies the
// half-source-period phase shift). clk_div = clk_ave | clk_adjust.
// Pulse-SET phases (canonical golden, no one-count pre-compensation):
//   average (posedge): HIGH at cnt==0 and cnt==4
//   adjust  (negedge): HIGH at cnt==1 and cnt==4
// Both intermediates reset to 0 so the output starts LOW after reset.
module freq_divbyfrac #(
    parameter MUL2_DIV_CLK = 7   // 2 * 3.5
) (
    input  wire clk,
    input  wire rst_n,
    output wire clk_div
);

    reg [3:0] cnt;
    reg       clk_ave;     // posedge-registered "average/uneven" clock
    reg       clk_adjust;  // negedge-registered "adjust" clock

    // counter + average clock on the rising edge
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt     <= 4'd0;
            clk_ave <= 1'b0;
        end else begin
            if (cnt == MUL2_DIV_CLK - 1)
                cnt <= 4'd0;
            else
                cnt <= cnt + 4'd1;

            if (cnt == 4'd0 || cnt == 4'd4)
                clk_ave <= 1'b1;
            else
                clk_ave <= 1'b0;
        end
    end

    // adjust clock on the falling edge (half-period phase shift)
    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) begin
            clk_adjust <= 1'b0;
        end else begin
            if (cnt == 4'd1 || cnt == 4'd4)
                clk_adjust <= 1'b1;
            else
                clk_adjust <= 1'b0;
        end
    end

    assign clk_div = clk_ave | clk_adjust;

endmodule
