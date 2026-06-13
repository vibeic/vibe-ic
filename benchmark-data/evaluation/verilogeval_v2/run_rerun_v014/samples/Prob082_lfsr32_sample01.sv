module TopModule (
  input         clk,
  input         reset,
  output [31:0] q
);

  reg [31:0] q_reg;

  // Galois LFSR shifting right. Taps at bit positions 32, 22, 2, 1 (1-indexed),
  // i.e. q_reg[31], q_reg[21], q_reg[1], q_reg[0]. The bit shifted out is q[0],
  // and the MSB q[31] receives that feedback bit.
  wire [31:0] next;
  assign next[31] = q_reg[0];                 // tap position 32, feedback in
  assign next[30:22] = q_reg[31:23];
  assign next[21] = q_reg[22] ^ q_reg[0];     // tap position 22
  assign next[20:2] = q_reg[21:3];
  assign next[1] = q_reg[2] ^ q_reg[0];       // tap position 2
  assign next[0] = q_reg[1] ^ q_reg[0];       // tap position 1

  always @(posedge clk) begin
    if (reset)
      q_reg <= 32'h1;
    else
      q_reg <= next;
  end

  assign q = q_reg;

endmodule
