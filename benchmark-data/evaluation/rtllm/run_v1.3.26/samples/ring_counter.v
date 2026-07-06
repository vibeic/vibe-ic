module ring_counter(
    input  wire       clk,
    input  wire       reset,
    output reg  [7:0] out
);

always @(posedge clk or posedge reset) begin
    if (reset)
        out <= 8'b0000_0001;
    else
        out <= {out[6:0], out[7]};
end

endmodule
