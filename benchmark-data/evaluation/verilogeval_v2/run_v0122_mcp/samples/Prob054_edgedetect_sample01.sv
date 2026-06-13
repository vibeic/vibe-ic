module TopModule (
    input        clk,
    input  [7:0] in,
    output reg [7:0] pedge
);

    reg [7:0] in_prev;

    always @(posedge clk) begin
        in_prev <= in;
        pedge   <= ~in_prev & in;  // 0->1 transition -> pulse next cycle
    end

endmodule
