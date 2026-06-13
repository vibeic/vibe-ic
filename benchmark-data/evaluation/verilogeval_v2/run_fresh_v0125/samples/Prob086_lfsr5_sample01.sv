module TopModule (
  input        clk,
  input        reset,
  output [4:0] q
);

  reg [4:0] q_reg;

  // 5-bit Galois LFSR shifting right, taps at positions 5 and 3.
  // Position 5 -> bit index 4, position 3 -> bit index 2.
  // Tapped positions XOR the shifted-out LSB q[0]; others shift right.
  always @(posedge clk) begin
    if (reset)
      q_reg <= 5'h1;
    else begin
      q_reg     <= q_reg >> 1;
      q_reg[4]  <= q_reg[0];
      q_reg[2]  <= q_reg[3] ^ q_reg[0];
    end
  end

  assign q = q_reg;

endmodule
