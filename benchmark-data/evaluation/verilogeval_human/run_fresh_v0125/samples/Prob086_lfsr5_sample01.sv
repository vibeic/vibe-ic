module TopModule (
  input clk,
  input reset,
  output reg [4:0] q
);

  // Galois LFSR shift right. q[0] feedback XORed into tapped positions.
  // Taps at positions 5 and 3 (1-indexed) => bits q[4] and q[2].
  always @(posedge clk) begin
    if (reset)
      q <= 5'h1;
    else begin
      q <= q >> 1;
      q[4] <= q[0];          // MSB filled with shifted-out bit
      q[2] <= q[3] ^ q[0];   // tap at position 3
    end
  end

endmodule
