module right_shifter(
    input  wire       clk,
    input  wire       d,
    output reg  [7:0] q
);

initial q = 8'b0000_0000;

always @(posedge clk) begin
    q    <= (q >> 1);
    q[7] <= d;
end

endmodule
