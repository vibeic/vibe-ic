module TopModule (
    input            clk,
    input      [7:0] in,
    output reg [7:0] pedge
);
    reg [7:0] in_prev = 8'b0;
    initial pedge = 8'b0;
    always @(posedge clk) begin
        pedge   <= in & ~in_prev;  // 1 where bit went 0->1 since last cycle
        in_prev <= in;
    end
endmodule
