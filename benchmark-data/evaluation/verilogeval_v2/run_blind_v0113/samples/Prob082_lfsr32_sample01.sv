module TopModule(
    input         clk,
    input         reset,
    output [31:0] q
);
    reg [31:0] q_reg = 32'h1;
    // Galois LFSR shifting right. Taps at positions 32,22,2,1 (1-indexed).
    // q[0] is the output bit shifted out; it feeds the MSB and is XORed
    // into the bit that receives the shift at each tapped position.
    always @(posedge clk) begin
        if (reset)
            q_reg <= 32'h1;
        else begin
            q_reg[31] <= q_reg[0];               // tap 32: MSB gets feedback
            q_reg[30:22] <= q_reg[31:23];        // plain shift right
            q_reg[21] <= q_reg[22] ^ q_reg[0];   // tap 22
            q_reg[20:2] <= q_reg[21:3];          // plain shift right
            q_reg[1]  <= q_reg[2]  ^ q_reg[0];   // tap 2
            q_reg[0]  <= q_reg[1]  ^ q_reg[0];   // tap 1
        end
    end
    assign q = q_reg;
endmodule
