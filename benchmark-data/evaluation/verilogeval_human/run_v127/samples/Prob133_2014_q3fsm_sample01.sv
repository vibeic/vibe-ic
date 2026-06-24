module TopModule (
  input  clk,
  input  reset,
  input  s,
  input  w,
  output reg z
);

  // Cycle-window FSM. Windows of 3 w-samples are back-to-back: the cycle that
  // reports z is also the first sample (position 1) of the next window.
  // State encodes (position-in-window, count-of-w=1-seen-so-far). z is Moore:
  // it is 1 only in the c1 state that was reached because the previous window
  // had exactly two ones (Bz).
  localparam A    = 4'd0;  // idle, z=0
  localparam B    = 4'd1;  // window c1, z=0
  localparam BZ   = 4'd2;  // window c1, z=1 (previous window had exactly two)
  localparam C2_0 = 4'd3;  // pos2, count 0
  localparam C2_1 = 4'd4;  // pos2, count 1
  localparam C3_0 = 4'd5;  // pos3, count 0
  localparam C3_1 = 4'd6;  // pos3, count 1
  localparam C3_2 = 4'd7;  // pos3, count 2

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      A:    next = s ? B : A;
      B:    next = w ? C2_1 : C2_0;
      BZ:   next = w ? C2_1 : C2_0;
      C2_0: next = w ? C3_1 : C3_0;
      C2_1: next = w ? C3_2 : C3_1;
      C3_0: next = B;                 // final count 0 or 1 -> z=0
      C3_1: next = w ? BZ : B;        // w=1 -> final 2 -> z; else final 1
      C3_2: next = w ? B : BZ;        // w=1 -> final 3 -> z=0; else final 2 -> z
      default: next = A;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= A;
    else
      state <= next;
  end

  always @(*) z = (state == BZ);

endmodule
