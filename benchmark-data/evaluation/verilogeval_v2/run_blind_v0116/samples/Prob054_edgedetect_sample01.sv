module TopModule (
    input        clk,
    input  [7:0] in,
    output [7:0] pedge
);

    reg [7:0] prev    = 8'b0;
    reg [7:0] pedge_r = 8'b0;

    always @(posedge clk) begin
        // 0->1 transition: was 0 last cycle, is 1 now.
        pedge_r <= ~prev & in;
        prev    <= in;
    end

    assign pedge = pedge_r;

endmodule
