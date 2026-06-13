module TopModule(
    input             clk,
    input             reset,
    output reg [31:0] q
);
    // Galois right-shift LFSR. Taps at positions 32,22,2,1 -> bit indices 31,21,1,0.
    // On each shift the bit below a tapped position is XORed with the outgoing LSB (q[0]).
    always @(posedge clk) begin
        if (reset)
            q <= 32'h1;
        else begin
            q[31] <= q[0];                 // feedback into MSB (tap 32)
            q[30:22] <= q[31:23];          // plain shift
            q[21] <= q[22] ^ q[0];         // tap 22
            q[20:2] <= q[21:3];            // plain shift
            q[1]  <= q[2] ^ q[0];          // tap 2
            q[0]  <= q[1] ^ q[0];          // tap 1
        end
    end
endmodule
