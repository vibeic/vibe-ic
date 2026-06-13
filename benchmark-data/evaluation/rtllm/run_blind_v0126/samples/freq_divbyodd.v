module freq_divbyodd #(
    parameter NUM_DIV = 5
) (
    input  clk,
    input  rst_n,
    output clk_div
);

    reg [3:0] cnt1;
    reg [3:0] cnt2;
    reg       clk_div1;
    reg       clk_div2;

    // Positive edge counter and divider
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt1 <= 4'd0;
        end else if (cnt1 == NUM_DIV - 1) begin
            cnt1 <= 4'd0;
        end else begin
            cnt1 <= cnt1 + 4'd1;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            clk_div1 <= 1'b0;
        end else if (cnt1 == (NUM_DIV-1)/2) begin
            clk_div1 <= ~clk_div1;
        end else if (cnt1 == NUM_DIV - 1) begin
            clk_div1 <= ~clk_div1;
        end
    end

    // Negative edge counter and divider
    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt2 <= 4'd0;
        end else if (cnt2 == NUM_DIV - 1) begin
            cnt2 <= 4'd0;
        end else begin
            cnt2 <= cnt2 + 4'd1;
        end
    end

    always @(negedge clk or negedge rst_n) begin
        if (!rst_n) begin
            clk_div2 <= 1'b0;
        end else if (cnt2 == (NUM_DIV-1)/2) begin
            clk_div2 <= ~clk_div2;
        end else if (cnt2 == NUM_DIV - 1) begin
            clk_div2 <= ~clk_div2;
        end
    end

    assign clk_div = clk_div1 | clk_div2;

endmodule
