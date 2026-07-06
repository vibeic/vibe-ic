// DB-informed re-author: reviewed IC-Expert-DB craft for this design class;
// verified by hand-trace that the existing implementation already satisfies the
// relevant DB lesson (or the lesson does not apply here) -- kept functionally unchanged.
module LFSR(
    input  wire       clk,
    input  wire       rst,
    output reg  [3:0] out
);

wire feedback = ~(out[3] ^ out[2]);

always @(posedge clk) begin
    if (rst)
        out <= 4'b0000;
    else
        out <= {out[2:0], feedback};
end

endmodule
