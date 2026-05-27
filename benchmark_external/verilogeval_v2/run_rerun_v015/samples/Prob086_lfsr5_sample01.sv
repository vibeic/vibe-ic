module TopModule (
  input        clk,
  input        reset,
  output [4:0] q
);

  reg [4:0] q_reg;

  // 5-bit Galois LFSR, shift right, taps at positions 5 and 3
  // (bit indices 4 and 2). MSB gets q[0]; tapped bits XOR q[0].
  always @(posedge clk) begin
    if (reset)
      q_reg <= 5'h1;
    else begin
      q_reg[4] <= q_reg[0];              // tap 5: feedback into MSB
      q_reg[3] <= q_reg[4];
      q_reg[2] <= q_reg[3] ^ q_reg[0];   // tap 3
      q_reg[1] <= q_reg[2];
      q_reg[0] <= q_reg[1];
    end
  end

  assign q = q_reg;

endmodule
