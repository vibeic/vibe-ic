module TopModule (
    input  clk,
    input  reset,
    output reg [4:0] q
);
    // Galois LFSR shifting right. Bit i takes q[i+1]; MSB receives q[0].
    // Taps at positions 5 and 3 (1-indexed) -> bit indices 4 and 2.
    // Tapped bit next value = incoming bit XOR q[0].
    always @(posedge clk) begin
        if (reset)
            q <= 5'h1;
        else begin
            q[4] <= q[0];           // tap 5 (MSB) receives feedback q[0]
            q[3] <= q[4];
            q[2] <= q[3] ^ q[0];    // tap 3
            q[1] <= q[2];
            q[0] <= q[1];
        end
    end
endmodule
