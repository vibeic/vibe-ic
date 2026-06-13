module TopModule (
  input        clk,
  input        reset,
  output [4:0] q
);

  reg [4:0] q_reg;

  // 5-bit Galois LFSR, shift right, taps at bit positions 5 and 3
  // (q_reg[4] and q_reg[2], 1-indexed). q[0] is the bit shifted out / feedback.
  wire [4:0] next;
  assign next[4] = q_reg[0];              // tap position 5, feedback in
  assign next[3] = q_reg[4];
  assign next[2] = q_reg[3] ^ q_reg[0];   // tap position 3
  assign next[1] = q_reg[2];
  assign next[0] = q_reg[1];

  always @(posedge clk) begin
    if (reset)
      q_reg <= 5'h1;
    else
      q_reg <= next;
  end

  assign q = q_reg;

endmodule
