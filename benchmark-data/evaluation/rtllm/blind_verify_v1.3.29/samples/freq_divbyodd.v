module freq_divbyodd #(
    parameter NUM_DIV = 5
) (
    input  wire clk,
    input  wire rst_n,
    output wire clk_div
);

    reg [31:0] cnt1;
    reg [31:0] cnt2;
    reg        clk_div1;
    reg        clk_div2;

    // posedge-clk counter/divider (registered output, toggles on limit)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt1 <= 32'd0;
        end else if (cnt1 == NUM_DIV - 1) begin
            cnt1 <= 32'd0;
        end else begin
            cnt1 <= cnt1 + 32'd1;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            clk_div1 <= 1'b0;
        end else if ((cnt1 == (NUM_DIV - 1) / 2) || (cnt1 == NUM_DIV - 1)) begin
            clk_div1 <= ~clk_div1;
        end
    end

    // negedge-clk counter/divider (registered output, toggles on limit)
    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt2 <= 32'd0;
        end else if (cnt2 == NUM_DIV - 1) begin
            cnt2 <= 32'd0;
        end else begin
            cnt2 <= cnt2 + 32'd1;
        end
    end

    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) begin
            clk_div2 <= 1'b0;
        end else if ((cnt2 == (NUM_DIV - 1) / 2) || (cnt2 == NUM_DIV - 1)) begin
            clk_div2 <= ~clk_div2;
        end
    end

    assign clk_div = clk_div1 | clk_div2;

endmodule
