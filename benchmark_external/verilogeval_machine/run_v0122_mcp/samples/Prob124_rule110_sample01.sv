module TopModule (
    input  clk,
    input  load,
    input  [511:0] data,
    output reg [511:0] q
);
    // Reset-less registered output: power-up value via separate initial block.
    initial q = 512'b0;

    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= ~(
                ( q[511:1] &  q[511:0] &  {q[510:0], 1'b0}) |
                (~q[511:1] & ~q[511:0] & ~{q[510:0], 1'b0}) |
                ( q[511:1] & ~q[511:0] & ~{q[510:0], 1'b0})
            );
    end
endmodule
