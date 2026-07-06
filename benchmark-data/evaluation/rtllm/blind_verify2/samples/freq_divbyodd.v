module freq_divbyodd #(
    parameter NUM_DIV = 5
)(
    input  wire clk,
    input  wire rst_n,
    output wire clk_div
);

    reg [31:0] cnt1;
    reg [31:0] cnt2;
    reg        clk_div1;
    reg        clk_div2;

    // posedge-domain half-rate counter/level
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt1     <= 32'd0;
            clk_div1 <= 1'b1;
        end else begin
            if (cnt1 == NUM_DIV - 1)
                cnt1 <= 32'd0;
            else
                cnt1 <= cnt1 + 32'd1;
            clk_div1 <= (cnt1 < (NUM_DIV / 2));
        end
    end

    // negedge-domain half-rate counter/level
    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt2     <= 32'd0;
            clk_div2 <= 1'b1;
        end else begin
            if (cnt2 == NUM_DIV - 1)
                cnt2 <= 32'd0;
            else
                cnt2 <= cnt2 + 32'd1;
            clk_div2 <= (cnt2 < (NUM_DIV / 2));
        end
    end

    assign clk_div = clk_div1 | clk_div2;

endmodule
