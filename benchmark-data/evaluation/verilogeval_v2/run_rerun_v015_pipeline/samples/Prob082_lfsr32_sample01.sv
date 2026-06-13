module TopModule (
  input         clk,
  input         reset,
  output [31:0] q
);
  reg [31:0] q_reg;
  // Galois LFSR, shifts right. Taps at bit positions 32,22,2,1 (1-indexed)
  // -> q indices 31,21,1,0. Tapped bits XOR with q[0] on shift.
  always @(posedge clk) begin
    if (reset)
      q_reg <= 32'h1;
    else begin
      q_reg        <= q_reg >> 1;
      q_reg[31]    <= q_reg[0];            // feedback into MSB
      q_reg[21]    <= q_reg[22] ^ q_reg[0];
      q_reg[1]     <= q_reg[2]  ^ q_reg[0];
      q_reg[0]     <= q_reg[1]  ^ q_reg[0];
    end
  end
  assign q = q_reg;
endmodule
