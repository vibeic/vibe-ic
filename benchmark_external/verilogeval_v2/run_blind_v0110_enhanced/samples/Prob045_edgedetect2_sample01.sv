module TopModule (
    input         clk,
    input  [7:0]  in,
    output reg [7:0] anyedge = 8'b0
);
    reg [7:0] prev = 8'b0;
    always @(posedge clk) begin
        anyedge <= in ^ prev;   // 1 where bit changed since last cycle
        prev    <= in;
    end
endmodule
