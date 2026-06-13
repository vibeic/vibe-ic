// Prob145_circuit8 — one negedge flip-flop (q) + one transparent latch (p).
//
// q: captured on the NEGATIVE (falling) edge of clock -> @(negedge clock).
//
// p: "triggered on any change of a, assigns a to p if clock is high". This is
// a level-sensitive transparent latch that reacts to BOTH a AND clock. Coding
// it as `always @(a) if(clock) p=a;` would silently miss clock-edge updates
// (broken latch). v0.1.22 skill: level-sensitive logic must use a COMPLETE
// sensitivity list -> always @(*) with blocking assignment.
module TopModule (
  input clock,
  input a,
  output reg p,
  output reg q = 1'b0   // power-up init: deterministic 0 (avoids X at t=0)
);

  // Falling-edge flip-flop.
  always @(negedge clock)
    q <= a;

  // Transparent latch: while clock high, p follows a.
  always @(*)
    if (clock)
      p = a;

endmodule
