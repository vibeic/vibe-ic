module TopModule (
    input         clk,
    input         reset,
    output [31:0] q
);
    reg [31:0] q_reg = 32'h1;

    // Galois LFSR, shift right. Feedback = q[0] (LSB shifted out).
    // Taps at positions 32,22,2,1 (1-indexed) -> bits 31,21,1,0 (0-indexed).
    // Tapped bit i takes q[i+1] ^ q[0]; bit 31 (top) is loaded with q[0].
    wire [31:0] next;
    assign next[31] = q_reg[0];                 // position 32 (top) <- feedback
    assign next[30:22] = q_reg[31:23];          // positions 31..23 : plain shift
    assign next[21] = q_reg[22] ^ q_reg[0];     // position 22 : tap
    assign next[20:2] = q_reg[21:3];            // positions 21..3 : plain shift
    assign next[1] = q_reg[2] ^ q_reg[0];       // position 2 : tap
    assign next[0] = q_reg[1] ^ q_reg[0];       // position 1 : tap

    always @(posedge clk) begin
        if (reset)
            q_reg <= 32'h1;
        else
            q_reg <= next;
    end

    assign q = q_reg;
endmodule
