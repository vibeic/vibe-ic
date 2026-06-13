// Prob138_2012_q2fsm — 6-state Moore FSM, sync reset -> A, z=1 in E/F.
// w=0: A->A,B->D,C->D,D->A,E->D,F->D.  w=1: A->B,B->C,C->E,D->F,E->E,F->C.
module TopModule (
  input clk,
  input reset,
  input w,
  output z
);

  localparam A=3'd0, B=3'd1, C=3'd2, D=3'd3, E=3'd4, F=3'd5;
  reg [2:0] state, next;

  always @(*) begin
    case (state)
      A: next = w ? B : A;
      B: next = w ? C : D;
      C: next = w ? E : D;
      D: next = w ? F : A;
      E: next = w ? E : D;
      F: next = w ? C : D;
      default: next = A;
    endcase
  end

  always @(posedge clk) begin
    if (reset) state <= A;
    else       state <= next;
  end

  assign z = (state == E) || (state == F);

endmodule
