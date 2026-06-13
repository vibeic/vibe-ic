module TopModule (
  input clk,
  input resetn,
  input x,
  input y,
  output f,
  output g
);

  // State-transition table (from prose):
  //   A  -> B                 (unconditional)
  //   B  -> S0                (unconditional)
  //   S0 -> x?S1 :S0
  //   S1 -> x?S1 :S10
  //   S10-> x?G1 :S0
  //   G1 -> y?P1 :G2
  //   G2 -> y?P1 :P0
  //   P0 -> P0                (sink)
  //   P1 -> P1                (sink)
  // Outputs (Moore):
  //   f = 1 when state == B
  //   g = 1 when state == G1 | G2 | P1
  // resetn active-low; reset state is A (head of the A->B->S0 chain).

  localparam [3:0] A   = 4'd0,
                   B   = 4'd1,
                   S0  = 4'd2,
                   S1  = 4'd3,
                   S10 = 4'd4,
                   G1  = 4'd5,
                   G2  = 4'd6,
                   P0  = 4'd7,
                   P1  = 4'd8;

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      A:   next = B;
      B:   next = S0;
      S0:  next = x ? S1  : S0;
      S1:  next = x ? S1  : S10;
      S10: next = x ? G1  : S0;
      G1:  next = y ? P1  : G2;
      G2:  next = y ? P1  : P0;
      P0:  next = P0;
      P1:  next = P1;
      default: next = A;
    endcase
  end

  always @(posedge clk) begin
    if (!resetn)
      state <= A;
    else
      state <= next;
  end

  assign f = (state == B);
  assign g = (state == G1) || (state == G2) || (state == P1);

endmodule
