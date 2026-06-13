module TopModule (
  input clk,
  input reset,
  output reg [31:0] q
);

  // Galois LFSR, shift right. q[0] is the output bit XORed into tapped positions.
  // Taps at bit positions 32, 22, 2, 1 (1-indexed) => bits q[31], q[21], q[1], q[0].
  always @(posedge clk) begin
    if (reset)
      q <= 32'h1;
    else begin
      q <= q >> 1;
      q[31] <= q[0];                 // MSB filled with shifted-out bit
      q[21] <= q[22] ^ q[0];         // tap at position 22
      q[1]  <= q[2]  ^ q[0];         // tap at position 2
      q[0]  <= q[1]  ^ q[0];         // tap at position 1
    end
  end

endmodule
