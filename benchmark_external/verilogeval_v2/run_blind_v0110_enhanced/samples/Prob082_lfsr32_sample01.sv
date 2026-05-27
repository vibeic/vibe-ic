module TopModule(
    input         clk,
    input         reset,
    output reg [31:0] q = 32'h1
);
    // Galois LFSR, shift right. Taps at bit positions 32,22,2,1 (1-indexed)
    // => zero-indexed bits 31,21,1,0 are XORed with q[0] when shifted in.
    always @(posedge clk) begin
        if (reset)
            q <= 32'h1;
        else begin
            q[31] <= q[0];                 // feedback into MSB
            q[30] <= q[31];
            q[29:22] <= q[30:23];
            q[21] <= q[22] ^ q[0];         // tap at position 22
            q[20:2] <= q[21:3];
            q[1]  <= q[2] ^ q[0];          // tap at position 2
            q[0]  <= q[1] ^ q[0];          // tap at position 1
        end
    end
endmodule
