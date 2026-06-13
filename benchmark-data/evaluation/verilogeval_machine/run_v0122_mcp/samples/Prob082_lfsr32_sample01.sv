// Prob082_lfsr32 — 32-bit Galois LFSR, taps at 32,22,2 (0-idx 21,1,0).
// Sync reset to 32'h1. Shift right with feedback from q[0].
module TopModule (
  input clk,
  input reset,
  output reg [31:0] q
);

  reg [31:0] q_next;

  always @(*) begin
    q_next       = {q[0], q[31:1]};
    q_next[21]   = q[22] ^ q[0];
    q_next[1]    = q[2]  ^ q[0];
    q_next[0]    = q[1]  ^ q[0];
  end

  always @(posedge clk) begin
    if (reset)
      q <= 32'h1;
    else
      q <= q_next;
  end

endmodule
