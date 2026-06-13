module ring_counter (
    input            clk,
    input            reset,
    output reg [7:0] out
);

    always @(posedge clk) begin
        if (reset) begin
            out <= 8'b0000_0001;
        end else begin
            // rotate the single set bit toward the MSB, wrap MSB -> LSB
            out <= {out[6:0], out[7]};
        end
    end

endmodule
