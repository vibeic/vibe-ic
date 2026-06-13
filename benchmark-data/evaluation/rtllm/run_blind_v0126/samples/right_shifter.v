module right_shifter (
    input            clk,
    input            d,
    output reg [7:0] q
);

    // Power-up initialization of q to 0 (no reset port in the spec)
    initial begin
        q = 8'b0;
    end

    always @(posedge clk) begin
        // shift right by one and insert d at the MSB
        q <= {d, q[7:1]};
    end

endmodule
