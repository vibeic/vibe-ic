module TopModule (
    input  clk,
    input  reset,
    output reg [31:0] q
);
    // Galois LFSR shifting right. Bit i takes q[i+1] (shift toward LSB).
    // MSB (bit 31) receives the shifted-out bit q[0].
    // Tap positions 32,22,2,1 (1-indexed) -> bit indices 31,21,1,0.
    // A tapped bit's next value = (incoming shifted bit) XOR q[0].
    always @(posedge clk) begin
        if (reset)
            q <= 32'h1;
        else begin
            q[31] <= q[0];            // tap 32: incoming feedback q[0], (^q[0] cancels at MSB feed)
            q[30:22] <= q[31:23];
            q[21] <= q[22] ^ q[0];    // tap 22
            q[20:2] <= q[21:3];
            q[1] <= q[2] ^ q[0];      // tap 2
            q[0] <= q[1] ^ q[0];      // tap 1
        end
    end
endmodule
