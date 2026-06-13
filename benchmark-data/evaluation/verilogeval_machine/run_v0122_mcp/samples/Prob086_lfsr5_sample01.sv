// Prob086_lfsr5 — 5-bit Galois LFSR, sync reset to 5'h1.
// q_next[3:0]=q[4:1]; q_next[4]=q[0]; q_next[2]^=q[0].
module TopModule (
  input clk,
  input reset,
  output reg [4:0] q
);

  reg [4:0] q_next;

  always @(*) begin
    q_next        = {1'b0, q[4:1]};  // q_next[3:0] = q[4:1], top bit placeholder
    q_next[4]     = q[0];
    q_next[2]     = q_next[2] ^ q[0];
  end

  always @(posedge clk) begin
    if (reset)
      q <= 5'h1;
    else
      q <= q_next;
  end

endmodule
