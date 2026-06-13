module edge_detect (
    input  clk,
    input  rst_n,
    input  a,
    output reg rise,
    output reg down
);

    reg a_prev;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_prev <= 1'b0;
            rise   <= 1'b0;
            down   <= 1'b0;
        end else begin
            a_prev <= a;
            rise   <= (~a_prev) & a;   // 0 -> 1
            down   <= a_prev & (~a);   // 1 -> 0
        end
    end

endmodule
