module TopModule (
    input        clk,
    input        reset,
    output [4:0] q
);
    reg [4:0] q_reg = 5'h1;

    // Galois LFSR, shift right. Feedback = q[0].
    // Taps at positions 5 and 3 (1-indexed) -> bits 4 and 2 (0-indexed).
    wire [4:0] next;
    assign next[4] = q_reg[0];               // position 5 (top) <- feedback
    assign next[3] = q_reg[4];               // position 4 : plain shift
    assign next[2] = q_reg[3] ^ q_reg[0];    // position 3 : tap
    assign next[1] = q_reg[2];               // position 2 : plain shift
    assign next[0] = q_reg[1];               // position 1 : plain shift

    always @(posedge clk) begin
        if (reset)
            q_reg <= 5'h1;
        else
            q_reg <= next;
    end

    assign q = q_reg;
endmodule
