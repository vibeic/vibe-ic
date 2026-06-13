// Prob088_ece241_2014_q5b — 2-state FSM, async reset to A.
// A->B on x else A; B stays B. z = (A & x) | (B & ~x).
module TopModule (
  input clk,
  input areset,
  input x,
  output z
);

  localparam A = 1'b0, B = 1'b1;
  reg state;

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= A;
    else begin
      case (state)
        A:       state <= x ? B : A;
        B:       state <= B;
        default: state <= A;
      endcase
    end
  end

  assign z = (state == A && x) || (state == B && !x);

endmodule
