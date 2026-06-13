module TopModule(
    input            clk,
    input            reset,
    output reg [4:0] q
);
    // 5-bit Galois right-shift LFSR. Taps at positions 5,3 -> bit indices 4,2.
    always @(posedge clk) begin
        if (reset)
            q <= 5'h1;
        else begin
            q[4] <= q[0];            // feedback into MSB (tap 5)
            q[3] <= q[4];            // plain shift
            q[2] <= q[3] ^ q[0];     // tap 3
            q[1] <= q[2];            // plain shift
            q[0] <= q[1];            // plain shift
        end
    end
endmodule
