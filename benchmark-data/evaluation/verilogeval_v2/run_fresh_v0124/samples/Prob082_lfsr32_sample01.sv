module TopModule (
  input         clk,
  input         reset,
  output [31:0] q
);
  reg [31:0] q_reg;
  assign q = q_reg;

  // Galois LFSR, shift right. q[0] is the LSB output bit fed back.
  // Taps at bit positions 32, 22, 2, 1 (1-indexed) => bits 31,21,1,0 XOR feedback.
  always @(posedge clk) begin
    if (reset)
      q_reg <= 32'h1;
    else begin
      q_reg[31] <= q_reg[0];          // tap 32
      q_reg[30:22] <= q_reg[31:23];
      q_reg[21] <= q_reg[22] ^ q_reg[0]; // tap 22
      q_reg[20:2] <= q_reg[21:3];
      q_reg[1] <= q_reg[2] ^ q_reg[0];   // tap 2
      q_reg[0] <= q_reg[1] ^ q_reg[0];   // tap 1
    end
  end
endmodule
