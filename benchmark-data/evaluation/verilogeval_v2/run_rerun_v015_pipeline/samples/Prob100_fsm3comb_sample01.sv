module TopModule (
  input        in,
  input  [1:0] state,
  output reg [1:0] next_state,
  output       out
);
  // Moore FSM combinational logic. Encoding A=00, B=01, C=10, D=11.
  //  A: 0->A,1->B | B: 0->C,1->B | C: 0->A,1->D | D: 0->C,1->B
  localparam A = 2'b00, B = 2'b01, C = 2'b10, D = 2'b11;

  always @(*) begin
    case (state)
      A: next_state = in ? B : A;
      B: next_state = in ? B : C;
      C: next_state = in ? D : A;
      D: next_state = in ? B : C;
      default: next_state = A;
    endcase
  end

  // Moore output: 1 only in state D.
  assign out = (state == D);
endmodule
