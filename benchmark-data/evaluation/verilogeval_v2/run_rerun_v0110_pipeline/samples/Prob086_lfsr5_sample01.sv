module TopModule (
  input            clk,
  input            reset,
  output reg [4:0] q
);
  // Galois LFSR, right shift. Taps at positions 5 and 3 (1-indexed => indices 4,2).
  always @(posedge clk) begin
    if (reset)
      q <= 5'h1;
    else begin
      q[4] <= q[0];          // position 5 tap (MSB feedback)
      q[3] <= q[4];
      q[2] <= q[3] ^ q[0];   // position 3 tap (index 2)
      q[1] <= q[2];
      q[0] <= q[1];
    end
  end
endmodule
