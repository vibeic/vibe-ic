module TopModule (
    input        clk,
    input  [7:0] in,
    output [7:0] anyedge
);

    reg [7:0] prev = 8'b0;
    reg [7:0] anyedge_r = 8'b0;

    always @(posedge clk) begin
        anyedge_r <= in ^ prev;   // 1 where the bit changed since last cycle
        prev      <= in;
    end

    assign anyedge = anyedge_r;

endmodule
