module freq_divbyfrac (
    input  clk,
    input  rst_n,
    output clk_div
);
    // 3.5x fractional division using the double-edge clocking technique.
    // The counter cycles through 7 source clock cycles (MUL2_DIV_CLK = 7 = 2*3.5).
    parameter MUL2_DIV_CLK = 7;

    reg [2:0] cnt;
    reg       clk_div1;   // posedge-aligned intermediate clock
    reg       clk_div2;   // its half-source-period delayed copy (negedge)

    wire [2:0] cnt_next = (cnt == MUL2_DIV_CLK - 1) ? 3'd0 : cnt + 3'd1;

    // membership: high for counts {0,1,4,5}, low for {2,3,6}.
    // Yields two intermediate periods: 4 src cycles (0->4) and 3 src cycles (4->0),
    // averaging 3.5x. clk_div1 rises entering 0/4 and falls entering 2/6.
    function level;
        input [2:0] c;
        begin
            level = (c == 3'd0) || (c == 3'd1) || (c == 3'd4) || (c == 3'd5);
        end
    endfunction

    // 7-state counter on posedge
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) cnt <= 3'd0;
        else        cnt <= cnt_next;
    end

    // clk_div1 registered on posedge, holding the level for the count just entered
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) clk_div1 <= 1'b1;             // level(0) = 1
        else        clk_div1 <= level(cnt_next);
    end

    // clk_div2: clk_div1 delayed by half a source period (sampled on negedge)
    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) clk_div2 <= 1'b1;
        else        clk_div2 <= clk_div1;
    end

    // OR the two phase-shifted intermediate clocks for a uniform fractional clock.
    assign clk_div = clk_div1 | clk_div2;

endmodule
