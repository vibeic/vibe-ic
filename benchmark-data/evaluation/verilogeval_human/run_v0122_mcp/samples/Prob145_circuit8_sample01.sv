module TopModule (
  input      clock,
  input      a,
  output reg p,
  output reg q
);

  initial q = 1'b0;   // deterministic power-up for the negedge FF (separate initial block)

  // p: positive level-sensitive latch — transparent (p=a) while clock high, holds when low.
  // always_latch marks the inferred latch as intentional (avoids Verilator LATCH warning).
  always_latch
    if (clock)
      p = a;

  // q: negative-edge-triggered flip-flop capturing p on clock falling edge.
  always @(negedge clock)
    q <= p;

endmodule
