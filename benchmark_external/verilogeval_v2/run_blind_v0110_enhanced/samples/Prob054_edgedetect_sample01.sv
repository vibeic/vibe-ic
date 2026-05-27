module TopModule (
    input         clk,
    input  [7:0]  in,
    output reg [7:0] pedge = 8'b0
);
    reg [7:0] prev = 8'b0;
    always @(posedge clk) begin
        pedge <= in & ~prev;   // 1 where bit went 0->1 since last cycle
        prev  <= in;
    end
endmodule
