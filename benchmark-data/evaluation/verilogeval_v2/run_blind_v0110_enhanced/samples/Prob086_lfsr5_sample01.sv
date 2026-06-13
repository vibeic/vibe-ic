module TopModule(
    input            clk,
    input            reset,
    output reg [4:0] q = 5'h1
);
    // Galois LFSR shift right. Taps at positions 5 and 3 (1-indexed)
    // => zero-indexed bits 4 and 2 are XORed with q[0] on shift-in.
    always @(posedge clk) begin
        if (reset)
            q <= 5'h1;
        else begin
            q[4] <= q[0];           // feedback into MSB
            q[3] <= q[4];
            q[2] <= q[3] ^ q[0];    // tap at position 3
            q[1] <= q[2];
            q[0] <= q[1];
        end
    end
endmodule
