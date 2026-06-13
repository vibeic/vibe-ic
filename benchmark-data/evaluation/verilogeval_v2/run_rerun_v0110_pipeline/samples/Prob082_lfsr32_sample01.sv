module TopModule (
  input         clk,
  input         reset,
  output reg [31:0] q
);
  // Galois LFSR, right shift. Taps at positions 32,22,2,1 (1-indexed).
  // q[0] is the LSB output that feeds back into tapped positions.
  always @(posedge clk) begin
    if (reset)
      q <= 32'h1;
    else begin
      // MSB (position 32) gets the feedback bit
      q[31] <= q[0];
      // positions 31..1 shift right; tapped positions XOR with q[0]
      q[30:22] <= q[31:23];
      q[21]    <= q[22] ^ q[0];   // tap at position 22 (index 21)
      q[20:2]  <= q[21:3];
      q[1]     <= q[2] ^ q[0];    // tap at position 2 (index 1)
      q[0]     <= q[1] ^ q[0];    // tap at position 1 (index 0)
    end
  end
endmodule
