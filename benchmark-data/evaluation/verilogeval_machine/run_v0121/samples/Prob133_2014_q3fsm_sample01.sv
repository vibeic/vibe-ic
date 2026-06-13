module TopModule (
  input clk,
  input reset,   // synchronous reset to state A
  input s,
  input w,
  output reg z
);
  localparam A=4'd0, B=4'd1, C=4'd2,
             S10=4'd3, S11=4'd4,
             S20=4'd5, S21=4'd6, S22=4'd7;
  reg [3:0] state, next;

  always @(*) begin
    case (state)
      A:   next = s ? B   : A;
      B:   next = w ? S11 : S10;
      C:   next = w ? S11 : S10;
      S10: next = w ? S21 : S20;
      S11: next = w ? S22 : S21;
      S20: next = B;
      S21: next = w ? C   : B;
      S22: next = w ? B   : C;
      default: next = A;
    endcase
  end

  // SPEC DEFECT: prose gives no z definition. Canonical 2014_q3fsm: z=1 in accepting state S22.
  always @(*) z = (state == S22);

  always @(posedge clk) begin
    if (reset) state <= A;
    else       state <= next;
  end
endmodule
