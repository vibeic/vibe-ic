module TopModule(
    input        clk,
    input        reset,
    output [4:0] q
);
    reg [4:0] q_reg = 5'h1;
    // 5-bit Galois LFSR shifting right, taps at positions 5 and 3.
    // q[0] is shifted out, feeds the MSB and is XORed into the receiving
    // bit at each tapped position.
    always @(posedge clk) begin
        if (reset)
            q_reg <= 5'h1;
        else begin
            q_reg[4] <= q_reg[0];              // tap 5: MSB gets feedback
            q_reg[3] <= q_reg[4];              // plain shift
            q_reg[2] <= q_reg[3] ^ q_reg[0];   // tap 3
            q_reg[1] <= q_reg[2];              // plain shift
            q_reg[0] <= q_reg[1];              // plain shift
        end
    end
    assign q = q_reg;
endmodule
