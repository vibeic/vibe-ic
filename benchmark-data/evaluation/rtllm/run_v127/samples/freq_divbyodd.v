// freq_divbyodd: divide input clock by an ODD number NUM_DIV (default 5),
// keeping a 50% duty cycle via the dual-edge (posedge + negedge) technique.
// Two counters each span 0..NUM_DIV-1; the two intermediate clocks use the
// LEVEL form (cnt < NUM_DIV/2) and are OR-ed. The intermediates reset HIGH so
// the output's first half-period after reset is HIGH (phase-correct first
// cycle); a toggle-from-0 form would be phase-inverted at cycle 0.
module freq_divbyodd #(
    parameter NUM_DIV = 5   // odd divide ratio
) (
    input  wire clk,
    input  wire rst_n,
    output wire clk_div
);

    reg [31:0] cnt1, cnt2;
    reg        clk_div1, clk_div2;

    // rising-edge counter / intermediate clock
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt1     <= 32'd0;
            clk_div1 <= 1'b1;
        end else begin
            if (cnt1 == NUM_DIV - 1)
                cnt1 <= 32'd0;
            else
                cnt1 <= cnt1 + 32'd1;
            clk_div1 <= (cnt1 < NUM_DIV/2);
        end
    end

    // falling-edge counter / intermediate clock (supplies the missing half cycle)
    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt2     <= 32'd0;
            clk_div2 <= 1'b1;
        end else begin
            if (cnt2 == NUM_DIV - 1)
                cnt2 <= 32'd0;
            else
                cnt2 <= cnt2 + 32'd1;
            clk_div2 <= (cnt2 < NUM_DIV/2);
        end
    end

    assign clk_div = clk_div1 | clk_div2;

endmodule
