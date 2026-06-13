// Prob089_ece241_2014_q5a — serial 2's-complementer Moore state machine.
// LSB-first: copy bits up to and including the first 1, invert all bits after.
// State register: A = "no 1 seen yet", B = "a 1 has been seen".
// Async active-high reset returns the state register to A.
// Output is COMBINATIONAL and input-dependent: z = x ^ (state==B).
module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);

  localparam A = 1'b0;  // no 1 seen yet
  localparam B = 1'b1;  // a 1 has been seen

  reg state;

  // Next-state: A --(x==1)--> B; B stays in B.
  wire next_state = (state == A) ? (x ? B : A) : B;

  // State register: posedge clk, positive-edge-triggered asynchronous
  // active-high reset to state A.
  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= A;
    else
      state <= next_state;
  end

  // Combinational input-dependent output:
  //   state A -> z = x       (copy, including the first 1)
  //   state B -> z = ~x      (invert)
  assign z = x ^ (state == B);

endmodule
