module TopModule (
  input clk,
  input reset,
  output reg [4:0] q
);

  // Galois LFSR shifting right. Taps at positions 5 and 3 (1-indexed).
  always @(posedge clk) begin
    if (reset)
      q <= 5'h1;
    else begin
      q[4] <= q[0];
      q[3] <= q[4];
      q[2] <= q[3] ^ q[0];   // tap at position 3
      q[1] <= q[2];
      q[0] <= q[1];
    end
  end

endmodule
