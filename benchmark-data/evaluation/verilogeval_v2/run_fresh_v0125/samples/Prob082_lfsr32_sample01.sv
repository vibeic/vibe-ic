module TopModule (
  input         clk,
  input         reset,
  output [31:0] q
);

  reg [31:0] q_reg;

  // Galois LFSR shifting right. q[0] is the LSB output fed back.
  // Taps at bit positions 32, 22, 2, 1 (1-indexed) -> indices 31, 21, 1, 0.
  // Tapped bit positions XOR with the shifted-out LSB.
  always @(posedge clk) begin
    if (reset)
      q_reg <= 32'h1;
    else begin
      q_reg      <= q_reg >> 1;
      q_reg[31]  <= q_reg[0];
      q_reg[21]  <= q_reg[22] ^ q_reg[0];
      q_reg[1]   <= q_reg[2]  ^ q_reg[0];
      q_reg[0]   <= q_reg[1]  ^ q_reg[0];
    end
  end

  assign q = q_reg;

endmodule
